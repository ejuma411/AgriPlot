import json
import logging
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.core.exceptions import ValidationError
from django.db import connection, transaction
from django.db.models import Count, Q, Sum
from django.http import Http404, HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from django.views.generic import CreateView, DetailView, ListView, TemplateView

try:
    from accounts.access_control import resolve_access_profile
except ImportError:
    resolve_access_profile = None
from accounts.validators import validate_kenyan_phone
from listings.models import Plot, UserInterest
from notifications.notification_service import NotificationService

from .forms import (
    PaymentRequestForm,
    PaymentMilestoneForm,
    PaymentDisputeForm,
    PaymentClosingStepForm,
)
from .models import (
    BankTransferRequest,
    PaymentRequest,
    PaymentClosingStep,
    PaymentDisbursement,
    PaymentDispute,
    PaymentMilestone,
    Wallet,
    WalletTransaction,
)
from .daraja import DarajaError, daraja_ready, extract_callback_metadata, initiate_stk_push
from .permissions import (
    describe_payment_actor,
    step_allowed_actor_labels,
    step_requires_admin_action,
    user_can_add_milestone,
    user_can_create_payment,
    user_can_open_dispute,
    user_can_start_inline_step_checkout,
    user_can_update_closing_steps,
    user_can_update_specific_closing_step,
    user_can_transition_payment,
    user_can_view_payment,
    user_is_finance_admin,
    user_is_escrow_admin,
)
from .wallet_service import WalletService
from .presenters import PaymentPresenter

logger = logging.getLogger(__name__)


PAYMENT_METHOD_CARDS = [
    {
        "name": "Bank Transfer",
        "slug": PaymentRequest.Method.BANK_TRANSFER,
        "description": (
            "Primary payment method. Transfer funds directly to the AgriPlot settlement account. "
            "Secure, traceable, and suitable for all transaction sizes."
        ),
        "tone": "blue",
        "badge": "Recommended",
        "icon": "fa-building-columns",
        "priority": 1,
    },
    {
        "name": "AgriPlot Wallet",
        "slug": PaymentRequest.Method.WALLET,
        "description": (
            "Pay instantly from your AgriPlot wallet balance. "
            "Top up via M-Pesa, then use your wallet for fast, fee-free platform payments."
        ),
        "tone": "purple",
        "badge": None,
        "icon": "fa-wallet",
        "priority": 2,
    },
    {
        "name": "M-Pesa STK",
        "slug": PaymentRequest.Method.MPESA_STK,
        "description": (
            "M-Pesa STK push for live checkout in the Safaricom sandbox or production environment. "
            "The payment stays pending until Daraja confirms the callback."
        ),
        "tone": "green",
        "badge": "Live Flow",
        "icon": "fa-mobile-screen-button",
        "priority": 3,
    },
]


def _active_payment_provider():
    return getattr(settings, "PAYMENT_PROVIDER", "daraja").lower()


def _gateway_ready():
    if _active_payment_provider() == "daraja":
        return daraja_ready()
    return False


def _active_bank_transfer_provider():
    return getattr(settings, "BANK_TRANSFER_PROVIDER", "jenga").lower()


def _bank_transfer_ready():
    return bool(
        getattr(settings, "BANK_TRANSFER_ENABLED", False)
        and getattr(settings, "BANK_TRANSFER_BEARER_TOKEN", "").strip()
    )


def _bank_transfer_requests_for_payment(payment):
    """Return a safe queryset for the payment's bank transfer requests."""
    try:
        if BankTransferRequest._meta.db_table not in connection.introspection.table_names():
            return []
        return payment.bank_transfer_requests.select_related(
            "beneficiary", "disbursement"
        ).order_by("-created_at")
    except Exception as exc:
        logger.warning(
            "Bank transfer requests unavailable for payment %s: %s",
            getattr(payment, "pk", payment),
            exc,
        )
        return []


def _payment_method_backend_enabled(method):
    if method == PaymentRequest.Method.BANK_TRANSFER:
        return getattr(settings, "BANK_TRANSFER_ENABLED", False)
    if method == PaymentRequest.Method.WALLET:
        return getattr(settings, "WALLET_ENABLED", True)
    if method == PaymentRequest.Method.MPESA_STK:
        return _gateway_ready()
    if method == PaymentRequest.Method.CARD:
        return getattr(settings, "CARD_PAYMENTS_ENABLED", False)
    if method == PaymentRequest.Method.AIRTEL_MONEY:
        return getattr(settings, "AIRTEL_MONEY_ENABLED", False)
    if method == PaymentRequest.Method.MANUAL_ESCROW:
        return True
    return False


def _payment_method_unavailable_message(method):
    messages_map = {
        PaymentRequest.Method.BANK_TRANSFER: "Bank transfer is not yet configured. Contact support to add your settlement account details.",
        PaymentRequest.Method.WALLET: "The AgriPlot Wallet is currently disabled in backend settings.",
        PaymentRequest.Method.MPESA_STK: "M-Pesa STK is not available right now.",
        PaymentRequest.Method.CARD: "Card payments are not yet configured.",
        PaymentRequest.Method.AIRTEL_MONEY: "Airtel Money is not yet configured.",
    }
    return messages_map.get(method, "This payment method is not configured yet.")


def _user_phone_number(user):
    """Return the best available phone number for a user/profile pair."""
    if not user or not getattr(user, "is_authenticated", False):
        return ""

    profile = getattr(user, "profile", None)
    if profile:
        for attr_name in ("phone_number", "phone"):
            value = getattr(profile, attr_name, "")
            if value:
                return value

    for attr_name in ("phone_number", "phone"):
        value = getattr(user, attr_name, "")
        if value:
            return value

    return ""


def _payment_counterparty(payment):
    return payment.seller


def _payment_timeline_label(payment):
    label = payment.get_transaction_type_display().lower()
    if (
        payment.transaction_type == PaymentRequest.TransactionType.LEASE
        and payment.lease_start_date
        and payment.lease_end_date
    ):
        return (
            f"{label} from {payment.lease_start_date:%b %d, %Y} "
            f"to {payment.lease_end_date:%b %d, %Y}"
        )
    return label


def _is_provider_timeout_error(exc):
    message = str(exc or "").lower()
    return "timed out" in message or "awaiting provider confirmation" in message


def _mark_payment_provider_confirmation_pending(payment, provider, actor=None, *, context="checkout"):
    metadata = dict(payment.metadata or {})
    metadata.update(
        {
            "provider_start_status": "pending_provider_confirmation",
            "provider_start_provider": provider,
            "provider_start_context": context,
            "provider_start_recorded_at": timezone.now().isoformat(),
        }
    )
    payment.metadata = metadata
    payment.save(update_fields=["metadata", "updated_at"])
    payment.add_event(
        "provider_confirmation_pending",
        f"{provider.title()} did not confirm the payment start immediately. AgriPlot kept the checkout pending for follow-up.",
        actor=actor,
    )


def _notify_payment_activity(payment, event):
    recipient = _payment_counterparty(payment)
    if not recipient:
        return

    plot_title = payment.plot.title if payment.plot else payment.title
    transaction_label = _payment_timeline_label(payment)
    buyer_name = (
        payment.buyer.get_full_name() or payment.buyer.username
        if payment.buyer
        else "A buyer"
    )
    payment_url = reverse("payments:detail", kwargs={"pk": payment.pk})

    if event == "initiated":
        title = f"Buyer initiated {transaction_label}"
        message = (
            f"{buyer_name} started a {transaction_label} payment flow for '{plot_title}'. "
            f"Reference: {payment.internal_reference}. Status: {payment.get_status_display()}."
        )
        subject = f"AgriPlot: Buyer initiated {payment.get_transaction_type_display()} for {plot_title}"
    elif event == "paid":
        title = f"Buyer payment confirmed for {plot_title}"
        message = (
            f"{buyer_name} has completed payment {payment.internal_reference} for "
            f"the {transaction_label} flow on '{plot_title}'. Seller action may now be required."
        )
        subject = f"AgriPlot: Payment confirmed for {plot_title}"
    else:
        return

    site_url = getattr(settings, "SITE_URL", "").rstrip("/")
    workspace_url = f"{site_url}{payment_url}" if site_url else payment_url
    full_message = f"{message} Open payment workspace: {workspace_url}"

    NotificationService.create_notification(
        user=recipient,
        notification_type="plot_stage_update",
        title=title,
        message=full_message,
        metadata={"plot_id": payment.plot.id if payment.plot else None}
    )


def _notify_buyer_payment_success(payment):
    """Send buyer/tenant payment success acknowledgement."""
    buyer = payment.buyer
    if not buyer:
        return

    plot_title = payment.plot.title if payment.plot else payment.title
    payment_label = payment.get_transaction_type_display().lower()
    category_label = payment.get_category_display().lower()
    title = "Payment received successfully"
    message = (
        f"Your {category_label} payment of KES {payment.amount:,.2f} for '{plot_title}' "
        f"({payment_label}) was successful. Reference: {payment.internal_reference}. "
        "Thank you for partnering with AgriPlot."
    )
    NotificationService.create_notification(
        user=buyer,
        notification_type="payment_update",
        title=title,
        message=message,
        metadata={"payment_id": payment.id}
    )


def _handle_successful_gateway_payment(payment, provider, verification, actor=None):
    _ensure_payment_workflow_seeded(payment)
    anchor = payment.workflow_anchor_payment
    metadata = dict(payment.metadata or {})
    metadata[f"{provider}_verification"] = verification
    if (
        payment.transaction_type == PaymentRequest.TransactionType.PURCHASE
        and "due_diligence_lock_expires_at" not in metadata
    ):
        lock_anchor = payment.paid_at or timezone.now()
        metadata["due_diligence_lock_expires_at"] = (
            lock_anchor + timedelta(days=7)
        ).isoformat()
        metadata["due_diligence_pack_ready"] = True
    payment.metadata = metadata

    if payment.status == PaymentRequest.Status.PENDING:
        payment.apply_transition("mark_paid", actor=actor)
        _notify_payment_activity(payment, "paid")
        _notify_buyer_payment_success(payment)

    if anchor.pk != payment.pk:
        category_to_step = {
            PaymentRequest.Category.AGREEMENT_DEPOSIT: "agreement",
            PaymentRequest.Category.ESCROW_DEPOSIT: "payment_security",
            PaymentRequest.Category.COMPLETION_BALANCE: "completion_docs",
        }
        target_code = category_to_step.get(payment.category)
        if target_code:
            target_step = anchor.closing_steps.filter(code=target_code).first()
            if target_step:
                note_line = (
                    f"Payment recorded on {timezone.localtime(timezone.now()):%b %d, %Y %I:%M %p}: "
                    f"{payment.get_category_display()} ({payment.internal_reference}) for KES {payment.amount:,.2f}."
                )
                existing_notes = target_step.notes.strip()
                target_step.notes = f"{existing_notes}\n{note_line}".strip() if existing_notes else note_line
                if target_step.code == "payment_security" and target_step.can_mark_complete_with_current_evidence():
                    target_step.save(update_fields=["notes", "updated_at"])
                    target_step.set_status(
                        PaymentClosingStep.Status.COMPLETED,
                        actor=actor,
                        notes=target_step.notes,
                    )
                else:
                    if target_step.status == PaymentClosingStep.Status.PENDING:
                        target_step.status = PaymentClosingStep.Status.IN_PROGRESS
                    target_step.save(update_fields=["notes", "status", "updated_at"])
                anchor.add_event(
                    "stage_payment_recorded",
                    f"{payment.get_category_display()} recorded for {target_step.display_title}: KES {payment.amount:,.2f}.",
                    actor=actor,
                )

    if anchor and anchor.pk != payment.pk:
        anchor.sync_plot_market_state()

    _maybe_auto_complete_test_deal(payment)
    payment.save(update_fields=["metadata", "updated_at"])


def _journey_context():
    return {
        "journey_steps": [
            {
                "eyebrow": "Buyer journey",
                "title": "Buyer commits with a real payment signal",
                "copy": "The buyer picks a payment method and receives a clear commitment receipt.",
                "icon": "fa-magnifying-glass-location",
            },
            {
                "eyebrow": "AgriPlot control",
                "title": "AgriPlot records the deal state centrally",
                "copy": "The platform stores the payment method, amount, milestone schedule, and next action so the transaction no longer lives in private chats.",
                "icon": "fa-vault",
            },
            {
                "eyebrow": "Seller journey",
                "title": "Seller completes milestone-backed obligations",
                "copy": "Documents, viewing attendance, negotiation readiness, and verification evidence become payout gates rather than verbal promises.",
                "icon": "fa-file-signature",
            },
            {
                "eyebrow": "Resolution",
                "title": "AgriPlot releases, refunds, or disputes with traceability",
                "copy": "Every transition gets logged so the platform can prove why money moved, why it paused, or why it was refunded.",
                "icon": "fa-scale-balanced",
            },
        ],
        "revenue_streams": [
            "Viewing fees from serious buyer requests",
            "Reservation deposits attached to a listing opportunity",
            "Verification packages for title search coordination and document readiness",
            "Escrow facilitation commissions when milestones are released",
            "Premium seller tools such as faster verification and featured exposure",
        ],
        "mpesa_touchpoints": [
            {
                "title": "STK push for mobile-first checkout",
                "copy": "Capture intent directly on the buyer's phone when the deal starts moving.",
            },
            {
                "title": "Manual Paybill fallback",
                "copy": "Support buyers who still prefer typing a Paybill or Till manually while keeping the same AgriPlot reference.",
            },
            {
                "title": "Refund-aware records",
                "copy": "Keep a traceable path from original collection to refund or reversal decision.",
            },
        ],
        "dispute_rules": [
            "Escalate when the seller misses a promised document or viewing commitment.",
            "Refund the buyer when seller-side obligations are not met in time.",
            "Hold funds when either side contests evidence or payment recognition.",
            "Create a permanent audit trail for manual review and repeat-offender checks.",
        ],
        "platform_principles": [
            "Start with milestone payments before full land purchase handling.",
            "Use payment events to trigger platform actions and notifications.",
            "Prefer transparent payout rules over open-ended negotiation after money is sent.",
        ],
    }


def _build_default_milestones(payment):
    milestone_templates = {
        PaymentRequest.Category.AGREEMENT_DEPOSIT: [
            "Agreement deposit confirmed",
            "Sale agreement signed",
            "Escrow instructions recorded",
        ],
        PaymentRequest.Category.RESERVATION_DEPOSIT: [
            "Reservation acknowledged",
            "Seller uploads title and supporting documents",
            "Reservation released or refunded",
        ],
        PaymentRequest.Category.VERIFICATION_PACKAGE: [
            "Payment confirmed",
            "Verification task assigned",
            "Verification result delivered",
        ],
        PaymentRequest.Category.ESCROW_DEPOSIT: [
            "Funds placed in escrow",
            "Seller milestone evidence submitted",
            "Escrow released on approval",
        ],
        PaymentRequest.Category.STAMP_DUTY: [
            "Stamp duty paid to KRA via iTax",
            "Receipt uploaded for verification",
            "Tax evidence logged",
        ],
        PaymentRequest.Category.COMPLETION_BALANCE: [
            "Completion balance confirmed",
            "Completion documents exchanged",
            "Registration ready",
        ],
        PaymentRequest.Category.SERVICE_FEE: [
            "Payment confirmed",
            "Service delivered",
            "Receipt and closure",
        ],
    }
    titles = milestone_templates.get(payment.category, milestone_templates.get(PaymentRequest.Category.AGREEMENT_DEPOSIT, []))
    milestones = []
    for index, title in enumerate(titles, start=1):
        milestones.append(
            PaymentMilestone(
                payment=payment,
                title=title,
                sequence=index,
                due_at=payment.due_at if index == len(titles) else None,
            )
        )
    PaymentMilestone.objects.bulk_create(milestones)
    payment.add_event("milestones_seeded", "Default milestones were created for this payment flow.")


def _ensure_payment_workflow_seeded(payment):
    anchor = payment.workflow_anchor_payment
    anchor.ensure_closing_steps()
    if anchor.status in {
        PaymentRequest.Status.PAID,
        PaymentRequest.Status.IN_ESCROW,
        PaymentRequest.Status.PARTIALLY_RELEASED,
        PaymentRequest.Status.RELEASED,
    }:
        started_steps = anchor.closing_steps.exclude(status=PaymentClosingStep.Status.PENDING)
        if not started_steps.exists():
            first_step = anchor.closing_steps.order_by("sequence").first()
            if first_step:
                first_step.status = PaymentClosingStep.Status.IN_PROGRESS
                first_step.notes = (
                    "AgriPlot activated this transaction workspace after the checkout payment succeeded."
                )
                first_step.save(update_fields=["status", "notes", "updated_at"])
                anchor.add_event(
                    "closing_step_assigned",
                    f"Transaction workspace activated: {first_step.display_title} is now in progress.",
                )
    if not payment.milestones.exists():
        _build_default_milestones(payment)
    anchor.ensure_transaction_artifacts()


def _maybe_auto_complete_test_deal(payment):
    if not getattr(settings, "MPESA_TEST_MODE", False):
        return
    if payment.transaction_type == PaymentRequest.TransactionType.PURCHASE:
        payment.add_event(
            "test_mode_payment_recorded",
            "Test-mode payment was recorded, but AgriPlot left the legal stages untouched so the tracker stays truthful.",
        )
        return
    if payment.status == PaymentRequest.Status.PAID:
        payment.apply_transition("move_escrow")
    if payment.status in {
        PaymentRequest.Status.IN_ESCROW,
        PaymentRequest.Status.PARTIALLY_RELEASED,
    }:
        payment.apply_transition("release")
        payment.add_event(
            "auto_released",
            "Test-mode auto release completed so the plot status reflects the demo transaction.",
        )


def _payment_next_workspace_url(payment):
    anchor = payment.workflow_anchor_payment
    _ensure_payment_workflow_seeded(anchor)
    next_step = anchor.next_closing_step
    if next_step:
        return reverse(
            "payments:closing_step_workspace",
            kwargs={"pk": anchor.pk, "step_id": next_step.pk},
        )
    return reverse("payments:detail", kwargs={"pk": anchor.pk})


def _resolve_workspace_payment(pk):
    payment = get_object_or_404(
        PaymentRequest.objects.select_related("plot", "buyer", "seller").prefetch_related("closing_steps"),
        pk=pk,
    )
    anchor = payment.workflow_anchor_payment
    if anchor.pk == payment.pk:
        return payment
    return PaymentRequest.objects.select_related("plot", "buyer", "seller").prefetch_related("closing_steps").get(pk=anchor.pk)


def _create_workspace_stage_payment(payment, step, phone_number, actor):
    anchor = payment.workflow_anchor_payment

    payment_category = STEP_PAYMENT_CATEGORY_MAP.get(step.code)
    if not payment_category:
        raise ValidationError("This stage does not support direct checkout.")

    # Validate phone number
    checkout_phone = str(phone_number or "").strip()
    if not checkout_phone:
        raise ValidationError("Enter the M-Pesa number that should receive the STK push.")

    checkout_phone = validate_kenyan_phone(checkout_phone)

    # Calculate amount
    if (
        anchor.transaction_type == PaymentRequest.TransactionType.LEASE
        and step.code == "payment_security"
    ):
        stage_amount = anchor.lease_security_deposit or anchor.amount
    else:
        stage_amount = PaymentRequestForm.calculate_amount(
            anchor.plot,
            anchor.transaction_type,
            payment_category,
        )

    if not stage_amount:
        raise ValidationError("Unable to calculate the amount for this stage.")

    # Create child payment
    child_payment = PaymentRequest(
        buyer=anchor.buyer,
        seller=anchor.seller,
        plot=anchor.plot,
        title=PaymentRequestForm.build_title(
            anchor.plot,
            anchor.transaction_type,
            payment_category
        ),
        description=(
            f"Checkout for "
            f"{dict(PaymentRequest.Category.choices).get(payment_category, 'payment').lower()}."
        ),
        amount=stage_amount,
        category=payment_category,
        method=PaymentRequest.Method.MPESA_STK,
        transaction_type=anchor.transaction_type,
        status=PaymentRequest.Status.PENDING,
        phone_number=checkout_phone,
        lease_start_date=anchor.lease_start_date,
        lease_end_date=anchor.lease_end_date,
        intended_use=anchor.intended_use,
        lease_security_deposit=anchor.lease_security_deposit,
        notice_period_days=anchor.notice_period_days,
        good_husbandry_required=anchor.good_husbandry_required,
        soil_exit_test_required=anchor.soil_exit_test_required,
        subject_to_sale=anchor.subject_to_sale,
        escrow_enabled=True,
        due_at=PaymentRequestForm.calculate_due_at(
            anchor.transaction_type,
            payment_category,
            anchor.lease_start_date,
        ),
        metadata={
            "workflow_root_id": anchor.pk,
            "workspace_step_code": step.code,
            "workspace_step_id": step.pk,
        },
    )

    child_payment.full_clean()
    child_payment.save()

    child_payment.add_event(
        "created",
        "Workspace checkout created for the active step.",
        actor=actor,
    )

    _ensure_payment_workflow_seeded(child_payment)

    # Initiate STK push
    callback_url = settings.MPESA_CALLBACK_URL or (
        f"{settings.SITE_URL.rstrip('/')}{reverse('payments:daraja_callback')}"
    )

    try:
        stk_data = initiate_stk_push(child_payment, callback_url)
    except DarajaError as exc:
        if not _is_provider_timeout_error(exc):
            raise
        _mark_payment_provider_confirmation_pending(
            child_payment,
            "daraja",
            actor=actor,
            context="workspace_step_checkout",
        )
        return child_payment, {
            "CustomerMessage": (
                "Checkout was created, but Safaricom has not confirmed the STK push yet. "
                "Payment is marked as pending for follow-up."
            )
        }

    # Store provider response
    child_payment.provider_reference = (
        stk_data.get("CheckoutRequestID")
        or stk_data.get("MerchantRequestID")
        or child_payment.internal_reference
    )

    metadata = dict(child_payment.metadata or {})
    metadata.update(
        {
            "daraja_checkout_request_id": stk_data.get("CheckoutRequestID", ""),
            "daraja_merchant_request_id": stk_data.get("MerchantRequestID", ""),
            "daraja_customer_message": stk_data.get("CustomerMessage", ""),
            "daraja_response_description": stk_data.get("ResponseDescription", ""),
        }
    )

    child_payment.metadata = metadata
    child_payment.save(update_fields=["provider_reference", "metadata", "updated_at"])

    child_payment.add_event(
        "daraja_stk_initialized",
        "Safaricom Daraja STK push sent from workspace step.",
        actor=actor,
    )

    _notify_payment_activity(child_payment, "initiated")

    return child_payment, stk_data


def _active_deal_for_buyer_plot(user, plot, transaction_type):
    if not getattr(user, "is_authenticated", False) or not plot:
        return None
    deal = (
        PaymentRequest.objects.filter(
            buyer=user,
            plot=plot,
            transaction_type=transaction_type,
        )
        .exclude(
            status__in=[
                PaymentRequest.Status.REFUNDED,
                PaymentRequest.Status.CANCELLED,
                PaymentRequest.Status.FAILED,
            ]
        )
        .prefetch_related("closing_steps")
        .order_by("-created_at")
        .first()
    )
    if deal:
        anchor = deal.workflow_anchor_payment
        _ensure_payment_workflow_seeded(anchor)
        return anchor
    return deal


def _recommended_payment_category(plot, user, transaction_type):
    active_deal = _active_deal_for_buyer_plot(user, plot, transaction_type)
    if transaction_type == PaymentRequest.TransactionType.PURCHASE:
        if not active_deal:
            return PaymentRequest.Category.AGREEMENT_DEPOSIT, None
        next_step = active_deal.next_closing_step
        if not next_step:
            return None, active_deal
        step_to_category = {
            "agreement": PaymentRequest.Category.AGREEMENT_DEPOSIT,
            "completion_docs": PaymentRequest.Category.COMPLETION_BALANCE,
        }
        return step_to_category.get(next_step.code), active_deal
    if transaction_type == PaymentRequest.TransactionType.LEASE:
        if not active_deal:
            return PaymentRequest.Category.RESERVATION_DEPOSIT, None
        next_step = active_deal.next_closing_step
        if not next_step:
            return None, active_deal
        step_to_category = {
            "offer": PaymentRequest.Category.RESERVATION_DEPOSIT,
            "payment_security": PaymentRequest.Category.ESCROW_DEPOSIT,
        }
        return step_to_category.get(next_step.code), active_deal
    return PaymentRequest.Category.AGREEMENT_DEPOSIT, None


STEP_PAYMENT_CATEGORY_MAP = {
    "due_diligence": PaymentRequest.Category.VERIFICATION_PACKAGE,
    "agreement": PaymentRequest.Category.AGREEMENT_DEPOSIT,
    "payment_security": PaymentRequest.Category.ESCROW_DEPOSIT,
    "completion_docs": PaymentRequest.Category.COMPLETION_BALANCE,
}


class PaymentFlowOverviewView(TemplateView):
    template_name = "payments/flow_overview.html"

    def get_selected_transaction_type(self, plot):
        """Get transaction type based on plot listing type"""
        if not plot:
            return 'lease'

        if plot.listing_type == "sale":
            return 'purchase'
        if plot.listing_type == "lease":
            return 'lease'
        if plot.listing_type == "both":
            return 'lease'

        return 'lease'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(_journey_context())
        context["method_cards"] = PAYMENT_METHOD_CARDS
        context["dashboard_url"] = reverse("payments:dashboard")

        plot = None
        plot_id = self.request.GET.get("plot")
        payment_amount = None
        current_stage = None
        current_stage_label = None
        current_stage_message = None
        selected_transaction_type = 'lease'

        if plot_id:
            try:
                plot = Plot.objects.select_related("landowner__user", "agent__user").get(pk=plot_id)

                selected_transaction_type = self.get_selected_transaction_type(plot)

                from payments.models import PaymentRequest

                existing_payments = PaymentRequest.objects.filter(
                    plot=plot,
                    buyer=self.request.user
                ).order_by('-created_at')

                if not existing_payments.filter(category=PaymentRequest.Category.AGREEMENT_DEPOSIT).exists():
                    current_stage = 'agreement_deposit'
                    current_stage_label = 'Agreement Deposit (10%)'
                    current_stage_message = 'Pay 10% deposit to proceed with the sale agreement. Funds held in escrow.'
                    payment_amount = PaymentRequestForm.calculate_amount(
                        plot,
                        selected_transaction_type,
                        PaymentRequest.Category.AGREEMENT_DEPOSIT
                    )

                elif not existing_payments.filter(category=PaymentRequest.Category.COMPLETION_BALANCE).exists():
                    current_stage = 'completion_balance'
                    current_stage_label = 'Completion Balance (90%)'
                    current_stage_message = 'Final payment before transfer of ownership. Funds held in escrow until registration.'
                    payment_amount = PaymentRequestForm.calculate_amount(
                        plot,
                        selected_transaction_type,
                        PaymentRequest.Category.COMPLETION_BALANCE
                    )

                else:
                    current_stage_label = 'Completed'
                    current_stage_message = 'All payments for this transaction have been completed. Awaiting registration and disbursement.'
                    payment_amount = Decimal('0.00')

            except (Plot.DoesNotExist, ValueError, TypeError) as e:
                plot = None
                payment_amount = None

        if plot:
            context["is_both_listing"] = plot.listing_type == "both"
            context["transaction_type_display"] = (
                "Lease (Purchase option also available)"
                if plot.listing_type == "both"
                else ("Purchase" if plot.listing_type == "sale" else "Lease")
            )

        context["selected_plot"] = plot
        context["selected_transaction_type"] = selected_transaction_type
        context["payment_amount"] = payment_amount
        context["current_stage"] = current_stage
        context["current_payment_stage_label"] = current_stage_label
        context["current_payment_stage_message"] = current_stage_message
        context["workflow_start_url"] = (
            f"{reverse('payments:create_request')}?plot={plot.pk}" if plot else reverse("payments:create_request")
        )
        return context


class PaymentDashboardView(ListView):
    template_name = "accounts/dashboard/dashboard.html"
    model = PaymentRequest
    context_object_name = "payments"
    paginate_by = 12

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect("login")
        return redirect(f"{reverse('listings:dashboard_router')}?section=finance")

    def get_queryset(self):
        if not self.request.user.is_authenticated:
            return PaymentRequest.objects.none()

        queryset = (
            PaymentRequest.objects.select_related("buyer", "seller", "plot")
            .prefetch_related("milestones", "closing_steps")
            .order_by("-created_at")
        )
        if not user_is_finance_admin(self.request.user):
            queryset = queryset.filter(
                Q(buyer=self.request.user) | Q(seller=self.request.user)
            )
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        payments = self.object_list
        for payment in payments:
            _ensure_payment_workflow_seeded(payment)
        is_finance = user_is_finance_admin(self.request.user)
        focus_payment = next(
            (
                payment
                for payment in payments
                if payment.transaction_type in {
                    PaymentRequest.TransactionType.PURCHASE,
                    PaymentRequest.TransactionType.LEASE,
                }
            ),
            payments[0] if payments else None,
        )
        aggregates = payments.aggregate(
            total_amount=Sum("amount"),
            paid_count=Count("id", filter=Q(status=PaymentRequest.Status.PAID)),
            escrow_count=Count("id", filter=Q(status=PaymentRequest.Status.IN_ESCROW)),
            disputed_count=Count("id", filter=Q(status=PaymentRequest.Status.DISPUTED)),
        )
        purchase_tracker_count = payments.filter(
            transaction_type=PaymentRequest.TransactionType.PURCHASE
        ).count()
        context["stats"] = {
            "total_payments": payments.count(),
            "total_amount": aggregates["total_amount"] or 0,
            "paid_count": aggregates["paid_count"] or 0,
            "escrow_count": aggregates["escrow_count"] or 0,
            "disputed_count": aggregates["disputed_count"] or 0,
            "purchase_tracker_count": purchase_tracker_count,
        }
        context["method_cards"] = PAYMENT_METHOD_CARDS
        context["show_scope_notice"] = not self.request.user.is_authenticated
        context["focus_payment"] = focus_payment
        admin_step_queue = []
        if is_finance:
            for payment in payments:
                for step in payment.closing_steps.exclude(status=PaymentClosingStep.Status.COMPLETED).order_by("sequence"):
                    owner_label = step.responsible_party_label
                    if step_requires_admin_action(step):
                        admin_step_queue.append(
                            {
                                "payment": payment,
                                "step": step,
                                "owner_label": owner_label,
                                "is_current": payment.current_assigned_step and payment.current_assigned_step.pk == step.pk,
                            }
                        )
        context["is_finance_admin"] = is_finance
        context["admin_step_queue"] = admin_step_queue
        context["admin_task_count"] = len(admin_step_queue)
        return context


class PaymentRequestCreateView(LoginRequiredMixin, CreateView):
    model = PaymentRequest
    form_class = PaymentRequestForm
    template_name = "payments/create_request.html"
    success_url = reverse_lazy("payments:dashboard")

    def get_selected_plot(self):
        plot_id = self.request.GET.get("plot") or self.request.POST.get("plot")
        if not plot_id:
            return None
        try:
            return Plot.objects.get(pk=plot_id)
        except (Plot.DoesNotExist, ValueError, TypeError):
            return None

    def get_selected_transaction_type(self):
        selected_plot = self.get_selected_plot()
        requested_type = self.request.GET.get("transaction_type") or ""

        if selected_plot:
            if selected_plot.listing_type == "sale":
                return PaymentRequest.TransactionType.PURCHASE
            if selected_plot.listing_type == "lease":
                return PaymentRequest.TransactionType.LEASE
            if selected_plot.listing_type == "both":
                if requested_type == PaymentRequest.TransactionType.PURCHASE:
                    return PaymentRequest.TransactionType.PURCHASE
                return PaymentRequest.TransactionType.LEASE

        if requested_type in {PaymentRequest.TransactionType.PURCHASE, PaymentRequest.TransactionType.LEASE}:
            return requested_type
        return PaymentRequest.TransactionType.LEASE

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user
        kwargs["selected_plot"] = self.get_selected_plot()
        
        # Determine if we're just starting a workflow (not creating a payment)
        selected_plot = self.get_selected_plot()
        selected_transaction_type = self.get_selected_transaction_type()
        
        # Check if there's already an existing legal transaction
        existing_transaction = None
        if selected_plot and self.request.user.is_authenticated:
            from transactions.models import Transaction
            existing_transaction = Transaction.objects.filter(
                plot=selected_plot,
                buyer=self.request.user,
                transaction_type=selected_transaction_type
            ).exclude(
                stage__in=[Transaction.Stage.COMPLETED, Transaction.Stage.CANCELLED]
            ).first()
        
        # If no existing transaction, we're starting a new workflow
        # Pass start_workflow_only=True to the form
        kwargs["start_workflow_only"] = (existing_transaction is None)
        
        kwargs.setdefault("initial", {})
        kwargs["initial"]["transaction_type"] = selected_transaction_type
        stage_gate = self.get_stage_gate()
        kwargs["forced_category"] = stage_gate["forced_category"]
        kwargs["active_deal"] = stage_gate["active_deal"]
        kwargs["forced_amount"] = stage_gate["forced_amount"]
        return kwargs

    def get_stage_gate(self):
        selected_plot = self.get_selected_plot()
        transaction_type = self.get_selected_transaction_type()
        requested_workflow_root = self.get_requested_workflow_root()
        
        if not selected_plot:
            return {
                "forced_category": None,
                "active_deal": None,
                "forced_amount": None,
                "payment_required": False,
                "stage_title": "",
                "stage_message": "",
            }
        
        if requested_workflow_root and requested_workflow_root.plot_id == selected_plot.pk:
            active_deal = requested_workflow_root.workflow_anchor_payment
            next_step = active_deal.next_closing_step
            if transaction_type == PaymentRequest.TransactionType.PURCHASE:
                step_to_category = {
                    "agreement": PaymentRequest.Category.AGREEMENT_DEPOSIT,
                    "completion_docs": PaymentRequest.Category.COMPLETION_BALANCE,
                }
            else:
                step_to_category = {
                    "offer": PaymentRequest.Category.RESERVATION_DEPOSIT,
                    "payment_security": PaymentRequest.Category.ESCROW_DEPOSIT,
                }
            forced_category = step_to_category.get(next_step.code) if next_step else None
        else:
            forced_category, active_deal = _recommended_payment_category(
                selected_plot,
                self.request.user,
                transaction_type,
            )
        
        stage_title = ""
        stage_message = ""
        payment_required = bool(forced_category) and forced_category not in {PaymentRequest.Category.STAMP_DUTY, None}
        forced_amount = self.get_forced_stage_amount(active_deal, forced_category)
        
        if forced_category == PaymentRequest.Category.STAMP_DUTY:
            payment_required = False
            stage_title = "Stamp Duty (Paid to KRA)"
            stage_message = (
                "Stamp duty must be paid directly to KRA via iTax. After payment, upload the receipt for verification."
            )
        elif forced_category:
            stage_title = dict(PaymentRequest.Category.choices).get(forced_category, "Current payment stage")
            stage_message = (
                f"AgriPlot has locked this checkout to {stage_title.lower()} based on the current legal step, "
                "so the buyer cannot accidentally pay for the wrong stage."
            )
        
        return {
            "forced_category": forced_category,
            "active_deal": active_deal,
            "forced_amount": forced_amount,
            "payment_required": payment_required,
            "stage_title": stage_title,
            "stage_message": stage_message,
        }

    def get_requested_workflow_root(self):
        workflow_root_id = self.request.GET.get("workflow_root_id") or self.request.POST.get("workflow_root_id")
        if not workflow_root_id:
            return None
        try:
            return PaymentRequest.objects.select_related("plot", "buyer", "seller").get(pk=workflow_root_id)
        except (PaymentRequest.DoesNotExist, ValueError, TypeError):
            return None

    def get_forced_stage_amount(self, active_deal, forced_category):
        if not active_deal or not forced_category:
            return None
        if forced_category == PaymentRequest.Category.STAMP_DUTY:
            return None
        return None

    def build_payment_stage_cards(self, transaction_type, checkout_amounts):
        amount_bucket = checkout_amounts.get(transaction_type, {})
        return [
            {
                "code": "agreement_deposit",
                "step": "1",
                "title": "Agreement",
                "subtitle": "Deposit (10%)",
                "amount": amount_bucket.get("agreement_deposit", ""),
            },
            {
                "code": "completion_balance",
                "step": "2",
                "title": "Completion",
                "subtitle": "Balance (90%)",
                "amount": amount_bucket.get("completion_balance", ""),
            },
        ]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["method_cards"] = PAYMENT_METHOD_CARDS
        context["selected_plot"] = self.get_selected_plot()
        context["selected_transaction_type"] = self.get_selected_transaction_type()
        context["can_set_lease_terms"] = getattr(context.get("form"), "allow_lease_term_entry", False)
        stage_gate = self.get_stage_gate()
        context["stage_gate"] = stage_gate
        context["forced_category"] = stage_gate["forced_category"]
        context["forced_amount"] = stage_gate["forced_amount"]
        context["current_stage"] = stage_gate["forced_category"]
        context["current_payment_stage_label"] = stage_gate["stage_title"]
        context["current_payment_stage_message"] = stage_gate["stage_message"]

        from .wallet_service import WalletService
        context["wallet_balance"] = WalletService.get_balance(self.request.user)
        context["has_wallet_pin"] = WalletService.has_pin(self.request.user)

        context["plot_listing_types"] = {
            str(plot.pk): plot.listing_type
            for plot in context["form"].fields["plot"].queryset
        }
        context["plot_checkout_contexts"] = {
            str(plot.pk): {
                "listing_type": plot.listing_type,
                "land_type": plot.land_type,
                "land_type_display": plot.get_land_type_display(),
                "market_zone_display": plot.get_market_zone_display(),
                "title": plot.title,
            }
            for plot in context["form"].fields["plot"].queryset
        }
        context["selected_plot_availability"] = (
            context["selected_plot"].availability_summary
            if context["selected_plot"]
            else ""
        )
        
        form_amount = context["form"].fields["amount"].initial
        context["mpesa_allowed"] = PaymentRequestForm.mpesa_allowed_for_amount(form_amount)
        context["allowed_method_slugs"] = PaymentRequestForm.allowed_methods_for_amount(form_amount)
        context["default_method_slug"] = PaymentRequestForm.preferred_method_for_amount(form_amount)
        
        selected_plot = context["selected_plot"]
        context["checkout_amounts"] = {
            "purchase": {
                "agreement_deposit": str(PaymentRequestForm.calculate_amount(
                    selected_plot,
                    PaymentRequest.TransactionType.PURCHASE,
                    PaymentRequest.Category.AGREEMENT_DEPOSIT,
                ) or ""),
                "reservation_deposit": str(PaymentRequestForm.calculate_amount(
                    selected_plot,
                    PaymentRequest.TransactionType.PURCHASE,
                    PaymentRequest.Category.RESERVATION_DEPOSIT,
                ) or ""),
                "escrow_deposit": str(PaymentRequestForm.calculate_amount(
                    selected_plot,
                    PaymentRequest.TransactionType.PURCHASE,
                    PaymentRequest.Category.ESCROW_DEPOSIT,
                ) or ""),
                "stamp_duty": "Pay to KRA",
                "completion_balance": str(PaymentRequestForm.calculate_amount(
                    selected_plot,
                    PaymentRequest.TransactionType.PURCHASE,
                    PaymentRequest.Category.COMPLETION_BALANCE,
                ) or ""),
            },
            "lease": {
                "reservation_deposit": str(PaymentRequestForm.calculate_amount(
                    selected_plot,
                    PaymentRequest.TransactionType.LEASE,
                    PaymentRequest.Category.RESERVATION_DEPOSIT,
                ) or ""),
                "agreement_deposit": str(PaymentRequestForm.calculate_amount(
                    selected_plot,
                    PaymentRequest.TransactionType.LEASE,
                    PaymentRequest.Category.AGREEMENT_DEPOSIT,
                ) or ""),
                "escrow_deposit": str(PaymentRequestForm.calculate_amount(
                    selected_plot,
                    PaymentRequest.TransactionType.LEASE,
                    PaymentRequest.Category.ESCROW_DEPOSIT,
                ) or ""),
                "completion_balance": str(PaymentRequestForm.calculate_amount(
                    selected_plot,
                    PaymentRequest.TransactionType.LEASE,
                    PaymentRequest.Category.COMPLETION_BALANCE,
                ) or ""),
            },
        }
        context["payment_stage_cards"] = self.build_payment_stage_cards(
            context["selected_transaction_type"],
            context["checkout_amounts"],
        )
        
        bound_form = context.get("form")
        selected_method = ""
        if bound_form and getattr(bound_form, "is_bound", False):
            selected_method = (
                bound_form.data.get("method")
                or bound_form.data.get("payment_method")
                or ""
            )
        context["selected_method_slug"] = (
            selected_method if selected_method in context["allowed_method_slugs"] else context["default_method_slug"]
        )
        return context

    def dispatch(self, request, *args, **kwargs):
        decision = user_can_create_payment(request.user)
        if not decision.allowed:
            messages.error(request, decision.reason)
            return redirect("payments:dashboard")
        
        selected_plot = self.get_selected_plot()
        selected_transaction_type = self.get_selected_transaction_type()
        
        # Check for existing legal transaction - redirect to workflow instead of payment
        if selected_plot and request.user.is_authenticated:
            from transactions.models import Transaction
            legal_transaction = Transaction.objects.filter(
                plot=selected_plot,
                buyer=request.user,
                transaction_type=selected_transaction_type
            ).exclude(
                stage__in=[Transaction.Stage.COMPLETED, Transaction.Stage.CANCELLED]
            ).first()
            
            if legal_transaction:
                return redirect("transactions:detail", pk=legal_transaction.pk)
        
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        """Create legal transaction instead of direct payment"""
        selected_plot = self.get_selected_plot()
        selected_transaction_type = self.get_selected_transaction_type()
        
        if not selected_plot:
            messages.error(self.request, "Please select a property.")
            return redirect("payments:create_request")
        
        # Get seller
        seller = None
        if selected_plot.landowner_id and selected_plot.landowner.user_id:
            seller = selected_plot.landowner.user
        elif selected_plot.agent_id and selected_plot.agent.user_id:
            seller = selected_plot.agent.user
        
        # Validate we have a seller
        if not seller:
            messages.error(self.request, "This property does not have a valid seller assigned.")
            return redirect("payments:create_request")
        
        # Check if buyer is trying to buy their own property
        if seller.id == self.request.user.id:
            messages.error(self.request, "You cannot purchase your own property.")
            return redirect("payments:create_request")
        
        try:
            with transaction.atomic():
                # Create legal transaction
                legal_transaction = self.get_or_create_legal_transaction(
                    plot=selected_plot,
                    buyer=self.request.user,
                    seller=seller,
                    transaction_type=selected_transaction_type
                )
                
                if not legal_transaction:
                    messages.error(self.request, "Failed to create legal transaction.")
                    return redirect("payments:create_request")
                
                messages.success(
                    self.request,
                    f"✅ Legal workflow started for {selected_plot.title}. "
                    f"Current stage: {legal_transaction.get_stage_display()}"
                )
                
                return redirect("transactions:detail", pk=legal_transaction.pk)
                
        except Exception as e:
            logger.exception(f"Failed to create legal transaction: {e}")
            messages.error(self.request, f"Failed to start workflow: {str(e)}")
            return redirect("payments:create_request")

    def get_or_create_legal_transaction(self, plot, buyer, seller, transaction_type):
        """Create or get existing legal transaction for this plot/buyer"""
        from transactions.models import Transaction
        
        # Check for existing active transaction
        existing_transaction = Transaction.objects.filter(
            plot=plot,
            buyer=buyer,
            transaction_type=transaction_type
        ).exclude(
            stage__in=[Transaction.Stage.COMPLETED, Transaction.Stage.CANCELLED]
        ).first()
        
        if existing_transaction:
            return existing_transaction
        
        # Calculate the full contract value first.
        # Agreement Deposit is only the first 10% payment, not the total deal amount.
        from .forms import PaymentRequestForm
        if transaction_type == PaymentRequest.TransactionType.PURCHASE:
            agreed_price = getattr(plot, "sale_price", None) or getattr(plot, "price", None)
        else:
            agreed_price = PaymentRequestForm.lease_base_amount(plot)
            if agreed_price in {None, ""}:
                lease_monthly = getattr(plot, "lease_price_monthly", None)
                lease_yearly = getattr(plot, "lease_price_yearly", None)
                if lease_monthly:
                    agreed_price = lease_monthly * 12
                elif lease_yearly:
                    agreed_price = lease_yearly
        
        if not agreed_price or agreed_price <= 0:
            raise ValidationError("Unable to determine the full agreement value for this plot.")
        
        # Create transaction FIRST (without payment request)
        transaction_obj = Transaction.objects.create(
            plot=plot,
            buyer=buyer,
            seller=seller,
            agreed_price=agreed_price,
            transaction_type=transaction_type,
            stage=Transaction.Stage.DUE_DILIGENCE,
        )
        
        # Create payment request with proper values for escrow
        payment = PaymentRequest.objects.create(
            transaction_type=transaction_type,
            category=PaymentRequest.Category.AGREEMENT_DEPOSIT,
            plot=plot,
            buyer=buyer,
            seller=seller,
            amount=agreed_price,
            status=PaymentRequest.Status.PENDING,
            title=f"Purchase of {plot.title}",
            description=f"Legal transaction #{transaction_obj.id} for {plot.title}",
            escrow_enabled=True,
            method=PaymentRequest.Method.BANK_TRANSFER,
            internal_reference=PaymentRequest.generate_reference(),
        )
        
        transaction_obj.payment_request = payment
        transaction_obj.save(update_fields=['payment_request'])
        
        return transaction_obj

    def form_invalid(self, form):
        error_messages = []
        for field_name, errors in form.errors.items():
            for error in errors:
                error_messages.append(f"{field_name}: {error}")
        
        messages.error(
            self.request,
            "We could not start the workflow. " + " ".join(error_messages[:5])
        )
        return super().form_invalid(form)


class PaymentAccessMixin(UserPassesTestMixin):
    def test_func(self):
        payment = self.get_object()
        return user_can_view_payment(self.request.user, payment).allowed

    def handle_no_permission(self):
        if self.request.user.is_authenticated:
            messages.error(self.request, "You do not have access to this payment.")
            return redirect("payments:dashboard")
        return super().handle_no_permission()


class PaymentRequestDetailView(LoginRequiredMixin, PaymentAccessMixin, DetailView):
    model = PaymentRequest
    template_name = "payments/detail.html"
    context_object_name = "payment"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["milestone_form"] = PaymentMilestoneForm()
        context["dispute_form"] = PaymentDisputeForm()
        context["payment_dispute"] = getattr(self.object, "dispute", None)
        workspace_payment = self.object.workflow_anchor_payment
        _ensure_payment_workflow_seeded(workspace_payment)
        context["workspace_payment"] = workspace_payment
        closing_steps = list(workspace_payment.closing_steps.all())
        for step in closing_steps:
            decision = user_can_update_specific_closing_step(
                self.request.user,
                workspace_payment,
                step,
            )
            step.user_can_update = decision.allowed
            step.update_restriction_reason = decision.reason
            step.requires_admin_action = step_requires_admin_action(step)
        context["closing_steps"] = closing_steps
        from .presenters import PaymentPresenter
        presenter = PaymentPresenter(workspace_payment)
        context["transaction_stage_matrix"] = presenter.transaction_stage_matrix
        context["transaction_certificates"] = workspace_payment.certificates.all()
        context["disbursement_plan"] = workspace_payment.disbursements.all()
        context["bank_transfer_requests"] = _bank_transfer_requests_for_payment(
            workspace_payment
        )
        context["officer_payment_rules"] = presenter.officer_payment_rules
        context["platform_revenue_streams"] = presenter.platform_revenue_streams
        context["escrow_summary"] = presenter.escrow_summary
        context["stamp_duty_status"] = presenter.stamp_duty_status
        context["disbursement_schedule"] = presenter.disbursement_schedule
        
        action_labels = [
            ("submit", "Send request"),
            ("mark_paid", "Mark paid"),
            ("move_escrow", "Move to escrow"),
            ("partial_release", "Partial release"),
            ("release", "Release seller funds"),
            ("disburse_to_seller", "Disburse to Seller"),
            ("refund", "Refund buyer"),
            ("dispute", "Open dispute state"),
            ("cancel", "Cancel"),
        ]
        context["transition_actions"] = [
            (action, label)
            for action, label in action_labels
            if action in self.object.allowed_transitions
            and user_can_transition_payment(self.request.user, self.object, action).allowed
        ]
        context["can_add_milestone"] = user_can_add_milestone(
            self.request.user, self.object
        ).allowed
        context["can_open_dispute"] = user_can_open_dispute(
            self.request.user, self.object
        ).allowed
        context["can_update_closing_steps"] = user_can_update_closing_steps(
            self.request.user, self.object
        ).allowed
        context["is_finance_admin"] = user_is_finance_admin(self.request.user)
        context["is_escrow_admin"] = user_is_escrow_admin(self.request.user)
        context["is_payment_buyer"] = (
            self.request.user.is_authenticated
            and self.object.buyer_id == self.request.user.id
        )
        context["payment_provider"] = _active_payment_provider()
        context["bank_transfer_provider"] = _active_bank_transfer_provider()
        context["bank_transfer_ready"] = _bank_transfer_ready()
        context["gateway_ready"] = _gateway_ready()
        context["daraja_customer_message"] = (self.object.metadata or {}).get(
            "daraja_customer_message", ""
        )
        context["payment_status_poll_url"] = reverse(
            "payments:payment_status_poll",
            kwargs={
                "pk": workspace_payment.pk,
                "payment_id": self.object.pk,
            },
        )

        # ── Current payment stage (deposit vs completion) ──────────────────────
        meta = dict(workspace_payment.metadata or {})
        deposit_paid = bool(meta.get("deposit_paid"))
        completion_paid = bool(meta.get("completion_paid"))
        full_amount = workspace_payment.amount or Decimal("0")

        if not deposit_paid:
            current_stage_code = "deposit"
            current_stage_label = "Agreement Deposit (10%)"
            current_stage_amount = (full_amount * Decimal("0.1")).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
            current_stage_pct = 10
        elif not completion_paid:
            current_stage_code = "completion"
            current_stage_label = "Completion Balance (90%)"
            current_stage_amount = (full_amount * Decimal("0.9")).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
            current_stage_pct = 90
        else:
            current_stage_code = None
            current_stage_label = "All payments complete"
            current_stage_amount = Decimal("0")
            current_stage_pct = 0

        context["deposit_paid"] = deposit_paid
        context["completion_paid"] = completion_paid
        context["current_stage_code"] = current_stage_code
        context["current_stage_label"] = current_stage_label
        context["current_stage_amount"] = current_stage_amount
        context["current_stage_pct"] = current_stage_pct
        context["full_contract_amount"] = full_amount
        # ──────────────────────────────────────────────────────────────────────

        return context



@method_decorator(csrf_exempt, name="dispatch")
class DarajaCallbackView(View):
    http_method_names = ["post"]

    def post(self, request):
        if _active_payment_provider() != "daraja" or not daraja_ready():
            return HttpResponseBadRequest("Daraja not configured.")

        try:
            payload = json.loads(request.body.decode("utf-8"))
        except json.JSONDecodeError:
            return HttpResponseBadRequest("Invalid JSON payload.")

        stk_callback = (
            (payload.get("Body") or {}).get("stkCallback") or {}
        )
        checkout_request_id = stk_callback.get("CheckoutRequestID")
        merchant_request_id = stk_callback.get("MerchantRequestID")

        payment = PaymentRequest.objects.filter(
            Q(provider_reference=checkout_request_id)
            | Q(metadata__daraja_checkout_request_id=checkout_request_id)
            | Q(metadata__daraja_merchant_request_id=merchant_request_id)
        ).first()
        if not payment:
            return JsonResponse({"ResultCode": 0, "ResultDesc": "Accepted"})

        metadata = dict(payment.metadata or {})
        metadata["daraja_callback"] = stk_callback
        payment.metadata = metadata
        payment.save(update_fields=["metadata", "updated_at"])

        if stk_callback.get("ResultCode") == 0:
            callback_metadata = extract_callback_metadata(stk_callback)
            verification = {
                "status": "success",
                "result_desc": stk_callback.get("ResultDesc", ""),
                "checkout_request_id": checkout_request_id,
                "merchant_request_id": merchant_request_id,
                "receipt_number": callback_metadata.get("MpesaReceiptNumber", ""),
                "amount": callback_metadata.get("Amount"),
                "phone_number": callback_metadata.get("PhoneNumber", ""),
                "transaction_date": callback_metadata.get("TransactionDate", ""),
            }
            _handle_successful_gateway_payment(
                payment,
                provider="daraja",
                verification=verification,
            )
            payment.add_event(
                "daraja_callback_received",
                "Safaricom Daraja callback confirmed a successful STK payment.",
            )
        else:
            payment.add_event(
                "daraja_callback_failed",
                f"Daraja STK push returned: {stk_callback.get('ResultDesc', 'Unknown error')}",
            )

        return JsonResponse({"ResultCode": 0, "ResultDesc": "Accepted"})


@method_decorator(csrf_exempt, name="dispatch")
class PaymentStatusPollView(LoginRequiredMixin, View):
    def get(self, request, pk, payment_id):
        anchor_payment = _resolve_workspace_payment(pk)
        decision = user_can_view_payment(request.user, anchor_payment)
        if not decision.allowed:
            return JsonResponse({"ok": False, "message": decision.reason}, status=403)

        payment = get_object_or_404(PaymentRequest, pk=payment_id)
        if payment.workflow_anchor_payment.pk != anchor_payment.workflow_anchor_payment.pk:
            return JsonResponse({"ok": False, "message": "Payment does not belong to this workflow."}, status=404)

        settled_statuses = {
            PaymentRequest.Status.PAID,
            PaymentRequest.Status.IN_ESCROW,
            PaymentRequest.Status.PARTIALLY_RELEASED,
            PaymentRequest.Status.RELEASED,
        }
        failed_statuses = {
            PaymentRequest.Status.FAILED,
            PaymentRequest.Status.CANCELLED,
            PaymentRequest.Status.REFUNDED,
        }
        metadata = payment.metadata or {}
        customer_message = (
            metadata.get("daraja_customer_message")
            or ((metadata.get("daraja_callback") or {}).get("ResultDesc"))
            or ""
        )
        state = "pending"
        if payment.status in settled_statuses:
            state = "paid"
        elif payment.status in failed_statuses:
            state = "failed"

        # Prefer the legal transaction workspace if one exists
        if state == "paid" and anchor_payment.legal_transaction_id:
            from django.urls import reverse as _rev
            next_url = _rev("transactions:detail", kwargs={"pk": anchor_payment.legal_transaction_id})
        elif state == "paid":
            next_url = _payment_next_workspace_url(anchor_payment)
        else:
            next_url = ""

        return JsonResponse(
            {
                "ok": True,
                "state": state,
                "status": payment.status,
                "status_label": payment.get_status_display(),
                "message": customer_message,
                "redirect_url": next_url,
            }
        )


class PaymentTransitionView(LoginRequiredMixin, View):
    def post(self, request, pk, action):
        payment = get_object_or_404(PaymentRequest, pk=pk)
        view_decision = user_can_view_payment(request.user, payment)
        if not view_decision.allowed:
            messages.error(request, view_decision.reason)
            return redirect("payments:dashboard")
        action_decision = user_can_transition_payment(request.user, payment, action)
        if not action_decision.allowed:
            messages.error(request, action_decision.reason)
            return redirect("payments:detail", pk=payment.pk)

        # Special handling for disbursement - verify escrow admin
        if action == "disburse_to_seller" and not user_is_escrow_admin(request.user):
            messages.error(request, "Only escrow administrators can authorize fund disbursement.")
            return redirect("payments:detail", pk=payment.pk)

        try:
            payment.apply_transition(action, actor=request.user)
        except Exception as exc:
            messages.error(request, str(exc))
            return redirect("payments:detail", pk=payment.pk)
        if action == "mark_paid":
            _notify_payment_activity(payment, "paid")
            _notify_buyer_payment_success(payment)
        if action == "disburse_to_seller":
            messages.success(
                request,
                f"Funds disbursed for {payment.internal_reference}. "
                f"Platform fee: KES {payment.platform_fee_amount:,.2f}, "
                f"Seller receives: KES {payment.seller_net_amount:,.2f}"
            )
        else:
            messages.success(request, f"{payment.internal_reference} updated to {payment.get_status_display()}.")
        return redirect("payments:detail", pk=payment.pk)


class PaymentClosingStepWorkspaceView(LoginRequiredMixin, UserPassesTestMixin, View):
    """Workspace view for a specific closing step with actions and evidence upload."""
    template_name = "payments/step_workspace.html"

    def test_func(self):
        payment = get_object_or_404(PaymentRequest, pk=self.kwargs["pk"])
        step = get_object_or_404(PaymentClosingStep, pk=self.kwargs["step_id"], payment=payment)
        return user_can_view_payment(self.request.user, payment).allowed

    def handle_no_permission(self):
        if self.request.user.is_authenticated:
            messages.error(self.request, "You do not have access to this payment step.")
            return redirect("payments:dashboard")
        return redirect("login")

    def get_context(self, payment, step):
        """Build comprehensive context for the workspace template"""
        presenter = PaymentPresenter(payment)
        step_permission = user_can_update_specific_closing_step(self.request.user, payment, step)

        timeline_current_step = None
        completed_stages = []
        step_is_current = step.sequence == payment.current_assigned_step.sequence if payment.current_assigned_step else False
        all_steps = list(payment.closing_steps.order_by("sequence"))

        for s in all_steps:
            if s.sequence < (payment.current_assigned_step.sequence if payment.current_assigned_step else 999):
                completed_stages.append(s)
            elif s.sequence == (payment.current_assigned_step.sequence if payment.current_assigned_step else 999):
                timeline_current_step = s

        legal_transaction = getattr(payment, "legal_transaction", None)
        legal_status_summary = presenter.legal_status_summary if hasattr(presenter, "legal_status_summary") else None
        legal_workspace_url = presenter.legal_workspace_url if hasattr(presenter, "legal_workspace_url") else ""
        legal_progress_percentage = presenter.legal_transaction_progress if hasattr(presenter, "legal_transaction_progress") else 0

        context = {
            "payment": payment,
            "step": step,
            "workspace_title": "Payment Workspace",
            "section_kicker": "Payment Step",
            "timeline_current_step": timeline_current_step,
            "completed_stages": completed_stages,
            "legal_transaction": legal_transaction,
            "legal_status_summary": legal_status_summary,
            "legal_workspace_url": legal_workspace_url,
            "legal_progress_percentage": legal_progress_percentage,
            "step_is_current": step_is_current,
            "total_step_count": len(all_steps),
            "completed_step_count": len(completed_stages),
            "can_update_closing_steps": user_can_update_closing_steps(self.request.user, payment).allowed,
            "step_requires_admin_action": step_requires_admin_action(step),
            "step_update_reason": step.evidence_blocking_reason() if step_is_current else "",
            "primary_task_title": step.display_title if step_is_current else "",
            "primary_task_description": step.buyer_instruction if step_is_current else "",
            "primary_task_label": step.responsible_party_label,
            "step_checkout_reason": "",
            "step_payment_amount": None,
            "step_payment_url": None,
            "can_start_inline_step_checkout": user_can_start_inline_step_checkout(self.request.user, payment, step).allowed,
            "checkout_phone_initial": _user_phone_number(getattr(payment, "buyer", None)),
            "total_paid_by_buyer": payment.workflow_total_paid_amount,
            "current_escrow_balance": 0,
            "viewing_historical_step": not step_is_current,
            "current_workspace_step_url": reverse("payments:closing_step_workspace", kwargs={"pk": payment.pk, "step_id": payment.current_assigned_step.pk}) if payment.current_assigned_step else "",
            "is_payment_buyer": self.request.user.is_authenticated and payment.buyer_id == self.request.user.id,
            "is_payment_seller": self.request.user.is_authenticated and payment.seller_id == self.request.user.id,
            "is_finance_admin": user_is_finance_admin(self.request.user),
            "is_escrow_admin": user_is_escrow_admin(self.request.user),
            "can_update_current_closing_step": step_permission.allowed,
            "current_closing_step_update_reason": step_permission.reason,
            "closing_step_form": PaymentClosingStepForm(
                instance=step,
                user=self.request.user,
            ) if step_permission.allowed else None,
            "stamp_duty_status": presenter.stamp_duty_status if step.code == "stamp_duty" else None,
            "disbursement_schedule": presenter.disbursement_schedule if step.code == "disbursement" else None,
        }

        # Missing legal docs
        missing_legal_docs = []
        required_legal_docs = []
        pending_legal_docs = []
        legal_upload_form = None
        if legal_transaction:
            required_docs = legal_transaction.get_required_documents_for_stage()
            from transactions.models import TransactionDocument
            doc_labels = dict(TransactionDocument.DocType.choices)
            required_legal_docs = [doc_labels.get(doc_type, doc_type) for doc_type in required_docs]
            missing_legal_docs = required_legal_docs
            try:
                from transactions.forms import TransactionDocumentForm
                legal_upload_form = TransactionDocumentForm(transaction=legal_transaction, user=self.request.user)
            except Exception:
                pass

        context["required_legal_docs"] = required_legal_docs
        context["missing_legal_docs"] = missing_legal_docs
        context["pending_legal_docs"] = pending_legal_docs
        context["legal_upload_form"] = legal_upload_form
        context["actor_access_summary"] = []
        context["step_action_checklist"] = []

        return context

    def get(self, request, pk, step_id):
        payment = get_object_or_404(PaymentRequest, pk=pk)
        step = get_object_or_404(PaymentClosingStep, pk=step_id, payment=payment)
        context = self.get_context(payment, step)
        return render(request, self.template_name, context)

    def post(self, request, pk, step_id):
        payment = get_object_or_404(PaymentRequest, pk=pk)
        step = get_object_or_404(PaymentClosingStep, pk=step_id, payment=payment)

        decision = user_can_update_specific_closing_step(request.user, payment, step)
        if not decision.allowed:
            messages.error(request, decision.reason)
            return redirect("payments:closing_step_workspace", pk=pk, step_id=step_id)

        action = request.POST.get("action")
        notes = request.POST.get("notes", "")
        bypass_evidence = request.POST.get("bypass_evidence") == "on"

        try:
            if action == "mark_completed":
                step.set_status(PaymentClosingStep.Status.COMPLETED, actor=request.user, notes=notes, bypass_evidence=bypass_evidence)
                messages.success(request, f"Step '{step.display_title}' marked as completed.")
                
                # If this was the registration step, check if disbursement should be triggered
                if step.code == "registration" and payment.transaction_type == PaymentRequest.TransactionType.PURCHASE:
                    if (payment.metadata.get('deposit_paid') and payment.metadata.get('balance_paid') 
                            and payment.stamp_duty_receipt_verified_at):
                        messages.info(
                            request,
                            "Registration complete! Funds will be automatically disbursed to the seller after platform fee deduction."
                        )
                
                # If this was the stamp duty step, record verification
                if step.code == "stamp_duty":
                    messages.info(
                        request,
                        "Stamp duty payment verified. Thank you."
                    )
                    
            elif action == "mark_in_progress":
                step.set_status(PaymentClosingStep.Status.IN_PROGRESS, actor=request.user, notes=notes)
                messages.success(request, f"Step '{step.display_title}' marked as in progress.")
            elif action == "mark_blocked":
                step.set_status(PaymentClosingStep.Status.BLOCKED, actor=request.user, notes=notes)
                messages.success(request, f"Step '{step.display_title}' marked as blocked.")
            elif action == "disburse_funds":
                # Manual disbursement trigger for escrow admins
                if not user_is_escrow_admin(request.user):
                    messages.error(request, "Only escrow administrators can disburse funds.")
                elif payment.purchase_registration_complete:
                    payment.apply_transition("disburse_to_seller", actor=request.user)
                    messages.success(
                        request,
                        f"Funds disbursed for {payment.internal_reference}. "
                        f"Platform fee: KES {payment.platform_fee_amount:,.2f}, "
                        f"Seller receives: KES {payment.seller_net_amount:,.2f}"
                    )
                else:
                    messages.error(request, "Cannot disburse funds. Registration not complete.")
        except ValidationError as e:
            messages.error(request, str(e))

        if "document" in request.FILES:
            step.document = request.FILES["document"]
            step.save(update_fields=["document", "updated_at"])
            messages.success(request, "Document uploaded successfully.")

        return redirect("payments:closing_step_workspace", pk=pk, step_id=step_id)


class PaymentClosingStepUpdateView(LoginRequiredMixin, UserPassesTestMixin, View):
    """Update a closing step via form submission."""

    def test_func(self):
        payment = get_object_or_404(PaymentRequest, pk=self.kwargs["pk"])
        step = get_object_or_404(PaymentClosingStep, pk=self.kwargs["step_id"], payment=payment)
        return user_can_view_payment(self.request.user, payment).allowed

    def handle_no_permission(self):
        return redirect("payments:dashboard")

    def post(self, request, pk, step_id):
        payment = get_object_or_404(PaymentRequest, pk=pk)
        step = get_object_or_404(PaymentClosingStep, pk=step_id, payment=payment)

        decision = user_can_update_specific_closing_step(request.user, payment, step)
        if not decision.allowed:
            messages.error(request, decision.reason)
            return redirect("payments:closing_step_workspace", pk=pk, step_id=step_id)

        action = request.POST.get("action")
        notes = request.POST.get("notes", "")
        bypass_evidence = request.POST.get("bypass_evidence") == "on"

        try:
            if action == "mark_completed":
                step.set_status(PaymentClosingStep.Status.COMPLETED, actor=request.user, notes=notes, bypass_evidence=bypass_evidence)
                messages.success(request, f"Step '{step.display_title}' marked as completed.")
            elif action == "mark_in_progress":
                step.set_status(PaymentClosingStep.Status.IN_PROGRESS, actor=request.user, notes=notes)
                messages.success(request, f"Step '{step.display_title}' marked as in progress.")
            elif action == "mark_blocked":
                step.set_status(PaymentClosingStep.Status.BLOCKED, actor=request.user, notes=notes)
                messages.success(request, f"Step '{step.display_title}' marked as blocked.")
        except ValidationError as e:
            messages.error(request, str(e))

        if "document" in request.FILES:
            step.document = request.FILES["document"]
            step.save(update_fields=["document", "updated_at"])
            messages.success(request, "Document uploaded successfully.")

        return redirect("payments:closing_step_workspace", pk=pk, step_id=step_id)


class PaymentClosingStepStkPushView(LoginRequiredMixin, View):
    """Handle STK push for a payment step checkout."""

    def post(self, request, pk, step_id):
        payment = get_object_or_404(PaymentRequest, pk=pk)
        step = get_object_or_404(PaymentClosingStep, pk=step_id, payment=payment)

        if not user_can_start_inline_step_checkout(self.request.user, payment, step).allowed:
            return JsonResponse({"ok": False, "message": "Cannot start checkout for this step."}, status=403)

        phone_number = request.POST.get("phone_number", "")
        try:
            child_payment, stk_data = _create_workspace_stage_payment(payment, step, phone_number, request.user)
            return JsonResponse({
                "ok": True,
                "payment_id": child_payment.pk,
                "message": stk_data.get("CustomerMessage", "STK push sent"),
            })
        except ValidationError as e:
            return JsonResponse({"ok": False, "message": str(e)}, status=400)
        except Exception as e:
            return JsonResponse({"ok": False, "message": f"Failed: {str(e)}"}, status=500)


@login_required
def wallet_dashboard(request):
    """Wallet dashboard view — always routes to the wallet section."""
    return redirect(f"{reverse('listings:dashboard_router')}?section=wallet")


@login_required
def wallet_set_pin(request):
    """Set wallet PIN"""
    if request.method == 'POST':
        try:
            data = json.loads(request.body) if request.body else request.POST
            pin = data.get('pin')
            confirm_pin = data.get('confirm_pin')
        except (json.JSONDecodeError, AttributeError):
            pin = request.POST.get('pin')
            confirm_pin = request.POST.get('confirm_pin')

        if not pin or not confirm_pin:
            return JsonResponse({'success': False, 'message': 'Please enter PIN'})

        if pin != confirm_pin:
            return JsonResponse({'success': False, 'message': 'PINs do not match'})

        if len(pin) != 4 or not pin.isdigit():
            return JsonResponse({'success': False, 'message': 'PIN must be 4 digits'})

        try:
            WalletService.set_pin(request.user, pin)
            return JsonResponse({'success': True, 'message': 'PIN set successfully'})
        except Exception as e:
            return JsonResponse({'success': False, 'message': str(e)})

    return JsonResponse({'success': False, 'message': 'Invalid request'})


@login_required
def wallet_deposit(request):
    """Initiate wallet deposit"""
    if request.method == 'POST':
        try:
            data = json.loads(request.body) if request.body else request.POST
            amount = Decimal(str(data.get('amount', '0')))
            phone_number = data.get('phone_number', '')
        except (json.JSONDecodeError, AttributeError, Exception):
            amount = Decimal(request.POST.get('amount', '0'))
            phone_number = request.POST.get('phone_number', '')

        try:
            callback_url = (
                settings.WALLET_MPESA_CALLBACK_URL
                or f"{settings.SITE_URL.rstrip('/')}{reverse('payments:mpesa_wallet_callback')}"
            )
            result = WalletService.initiate_deposit(request.user, amount, phone_number, callback_url)
            return JsonResponse(result)
        except ValidationError as e:
            return JsonResponse({'success': False, 'message': e.message})
        except Exception as e:
            return JsonResponse({'success': False, 'message': str(e)})

    return JsonResponse({'success': False, 'message': 'Invalid request'})


@login_required
def wallet_withdraw(request):
    """Initiate wallet withdrawal"""
    if request.method == 'POST':
        try:
            data = json.loads(request.body) if request.body else request.POST
            amount = Decimal(str(data.get('amount', '0')))
            phone_number = data.get('phone_number', '')
            pin = data.get('pin', '')
        except (json.JSONDecodeError, AttributeError, Exception):
            amount = Decimal(request.POST.get('amount', '0'))
            phone_number = request.POST.get('phone_number', '')
            pin = request.POST.get('pin', '')

        try:
            result = WalletService.initiate_withdrawal(request.user, amount, phone_number, pin)
            return JsonResponse(result)
        except ValidationError as e:
            return JsonResponse({'success': False, 'message': e.message})
        except Exception as e:
            return JsonResponse({'success': False, 'message': str(e)})

    return JsonResponse({'success': False, 'message': 'Invalid request'})


@login_required
def wallet_pay(request):
    """Make payment from wallet"""
    if request.method == 'POST':
        try:
            data = json.loads(request.body) if request.body else request.POST
            amount = Decimal(str(data.get('amount', '0')))
            pin = data.get('pin', '')
            payment_request_id = data.get('payment_request_id')
        except (json.JSONDecodeError, AttributeError, Exception):
            amount = Decimal(request.POST.get('amount', '0'))
            pin = request.POST.get('pin', '')
            payment_request_id = request.POST.get('payment_request_id')

        payment_request = None
        if payment_request_id:
            payment_request = get_object_or_404(PaymentRequest, id=payment_request_id)

        try:
            result = WalletService.make_payment(
                user=request.user,
                amount=amount,
                pin=pin,
                payment_request=payment_request,
                description=request.POST.get('description', '')
            )
            return JsonResponse(result)
        except ValidationError as e:
            return JsonResponse({'success': False, 'message': e.message})
        except Exception as e:
            return JsonResponse({'success': False, 'message': str(e)})

    return JsonResponse({'success': False, 'message': 'Invalid request'})


@login_required
def wallet_transactions(request):
    """Get wallet transactions (AJAX)"""
    limit = request.GET.get('limit', 50)
    try:
        limit = int(limit)
    except (ValueError, TypeError):
        limit = 50

    transactions = WalletService.get_transaction_history(request.user, limit=limit)

    data = [{
        'id': t.id,
        'date': t.created_at.strftime('%Y-%m-%d %H:%M'),
        'type_display': t.get_transaction_type_display(),
        'type_code': t.type,
        'amount': float(t.amount),
        'status': t.get_status_display(),
        'status_code': t.status,
        'description': t.description or t.get_channel_display(),
        'reference': t.reference,
        'mpesa_receipt': (t.metadata or {}).get('mpesa_receipt') or t.provider_reference or '',
    } for t in transactions]

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'success': True, 'transactions': data})

    return render(request, 'payments/wallet_transactions.html', {'transactions': data})


@login_required
def wallet_balance_api(request):
    """API endpoint to get wallet balance"""
    balance_info = WalletService.get_balance_dict(request.user)
    return JsonResponse({'success': True, 'balance': float(balance_info['balance'])})


@login_required
def wallet_has_pin(request):
    """Check if user has set wallet PIN"""
    has_pin = WalletService.has_pin(request.user)
    return JsonResponse({'has_pin': has_pin})


@csrf_exempt
def mpesa_wallet_callback(request):
    """M-Pesa callback for wallet deposits"""
    try:
        data = json.loads(request.body)
        logger.info(f"Wallet callback received: {data}")
    except json.JSONDecodeError:
        return JsonResponse({'ResultCode': 1, 'ResultDesc': 'Invalid data'})

    body = data.get('Body', {})
    stk_callback = body.get('stkCallback', {})
    result_code = stk_callback.get('ResultCode')
    checkout_request_id = stk_callback.get('CheckoutRequestID')
    result_desc = stk_callback.get('ResultDesc')

    if result_code == 0:
        callback_metadata = extract_callback_metadata(stk_callback)
        receipt = callback_metadata.get('MpesaReceiptNumber')
        amount = callback_metadata.get('Amount')
        if receipt and amount and checkout_request_id:
            amount = Decimal(str(amount))
            result = WalletService.complete_deposit(checkout_request_id, receipt, amount)
            if result['success']:
                return JsonResponse({'ResultCode': 0, 'ResultDesc': 'Success'})

    logger.error(f"Wallet deposit failed: {result_desc}")
    return JsonResponse({'ResultCode': result_code or 1, 'ResultDesc': result_desc or 'Failed'})


@login_required
def test_stk_push(request):
    from .daraja import initiate_stk_push, daraja_ready

    if not request.user.is_superuser:
        return JsonResponse({'error': 'Only superusers can test'}, status=403)

    if request.method == 'POST':
        phone = request.POST.get('phone', '')
        amount = request.POST.get('amount', '')

        if not phone or not amount:
            return JsonResponse({'error': 'Phone and amount required'}, status=400)

        if not daraja_ready():
            return JsonResponse({'error': 'M-Pesa not configured'}, status=500)

        callback_url = settings.MPESA_CALLBACK_URL or (
            f"{settings.SITE_URL.rstrip('/')}{reverse('payments:daraja_callback')}"
        )

        class MockPayment:
            def __init__(self, phone, amount):
                self.phone_number = phone
                self.amount = float(amount)
                self.internal_reference = f"TEST-{int(timezone.now().timestamp())}"
                self.title = "Test Payment"

        mock_payment = MockPayment(phone, amount)

        try:
            result = initiate_stk_push(mock_payment, callback_url)
            return JsonResponse({
                'success': True,
                'message': 'STK push sent successfully!',
                'result': result
            })
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)}, status=500)

    return render(request, 'payments/test_stk.html')

# Add to your views.py

class LegalWorkflowView(LoginRequiredMixin, DetailView):
    """
    Main legal workflow view that shows the appropriate UI based on current stage.
    This replaces the old payment-centric flow.
    """
    model = PaymentRequest
    template_name = "payments/legal_workflow.html"
    context_object_name = "payment"

    def get_object(self, queryset=None):
        pk = self.kwargs.get("pk")
        payment = get_object_or_404(
            PaymentRequest.objects.select_related("plot", "buyer", "seller"),
            pk=pk
        )
        return payment.workflow_anchor_payment

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        payment = self.get_object()
        
        # Use the PaymentPresenter for all stage logic
        presenter = PaymentPresenter(payment)
        
        context["presenter"] = presenter
        current_stage = payment.metadata.get("current_step_code")
        if not current_stage:
            if payment.category == PaymentRequest.Category.AGREEMENT_DEPOSIT:
                current_stage = "deposit"
            elif payment.category == PaymentRequest.Category.COMPLETION_BALANCE:
                current_stage = "completion_balance"
            elif payment.category == PaymentRequest.Category.STAMP_DUTY:
                current_stage = "stamp_duty"
            else:
                current_stage = "due_diligence"

        context["current_stage"] = current_stage
        context["stage_progress"] = presenter.legal_transaction_progress
        
        # Get the workflow matrix
        context["workflow_stages"] = presenter.transaction_stage_matrix
        
        # For payment stages, include payment-specific context
        current_stage_code = context["current_stage"]
        
        if current_stage_code in ['deposit', 'agreement_deposit']:
            deposit_amount = payment.amount * Decimal('0.1')
            context["payment_amount"] = deposit_amount
            context["payment_label"] = "Agreement Deposit (10%)"
            context["payment_required"] = True
            context["is_deposit_stage"] = True
            
        elif current_stage_code in ['completion', 'completion_docs', 'completion_balance']:
            balance_amount = payment.amount * Decimal('0.9')
            context["payment_amount"] = balance_amount
            context["payment_label"] = "Completion Balance (90%)"
            context["payment_required"] = True
            context["is_completion_stage"] = True
            
        elif current_stage_code == 'stamp_duty':
            context["payment_required"] = False
            context["is_stamp_duty_stage"] = True
            context["stamp_duty_info"] = presenter.stamp_duty_status
            
        else:
            context["payment_required"] = False
            
        # Wallet balance for payment stages
        if context.get("payment_required"):
            context["wallet_balance"] = WalletService.get_balance(self.request.user)
            context["has_wallet_pin"] = WalletService.has_pin(self.request.user)
            
        # Check if user has permission to advance the stage
        if hasattr(payment, 'can_advance_to_next_stage'):
            can_advance, advance_message = payment.can_advance_to_next_stage()
            context["can_advance_stage"] = can_advance
            context["advance_message"] = advance_message
        else:
            context["can_advance_stage"] = True
            context["advance_message"] = ""
            
        # Get missing documents for current stage
        if hasattr(payment, 'get_missing_documents_for_current_stage'):
            context["missing_documents"] = payment.get_missing_documents_for_current_stage()
        else:
            context["missing_documents"] = []
            
        # Permission checks
        context["is_buyer"] = self.request.user.is_authenticated and payment.buyer_id == self.request.user.id
        context["is_seller"] = self.request.user.is_authenticated and payment.seller_id == self.request.user.id
        context["is_finance_admin"] = user_is_finance_admin(self.request.user)
        
        return context

    def post(self, request, *args, **kwargs):
        """Handle stage advancement and document uploads"""
        self.object = self.get_object()
        payment = self.object
        
        action = request.POST.get("action")
        
        # Handle document upload
        if action == "upload_document" and ("file" in request.FILES or "document" in request.FILES):
            try:
                from transactions.forms import TransactionDocumentForm
                from transactions.models import TransactionDocument

                form_data = request.POST.copy()
                form_files = request.FILES.copy()
                if "file" not in form_files and "document" in form_files:
                    form_files["file"] = form_files["document"]

                document_type = form_data.get("document_type")
                existing_doc = None
                if document_type:
                    existing_doc = TransactionDocument.objects.filter(
                        transaction=payment.legal_transaction,
                        document_type=document_type,
                    ).first()

                doc_form = TransactionDocumentForm(
                    form_data,
                    form_files,
                    instance=existing_doc,
                    transaction=payment.legal_transaction,
                    user=request.user,
                )
                if doc_form.is_valid():
                    doc = doc_form.save()
                    messages.success(request, f"Document '{doc.get_document_type_display()}' uploaded successfully.")

                    # After upload, check if stage can be advanced
                    if hasattr(payment.legal_transaction, 'can_advance_to_next_stage'):
                        can_advance, _ = payment.legal_transaction.can_advance_to_next_stage()
                        if can_advance:
                            messages.info(request, "All required documents for this stage are now uploaded. You can proceed to the next step.")
                else:
                    for field, errors in doc_form.errors.items():
                        for error in errors:
                            messages.error(request, f"{field}: {error}")
            except Exception as e:
                messages.error(request, f"Failed to upload document: {str(e)}")
                
        # Handle stage advancement
        elif action == "advance_stage":
            if hasattr(payment, 'advance_to_next_stage'):
                try:
                    payment.advance_to_next_stage(actor=request.user)
                    messages.success(request, f"Advanced to next stage: {payment.get_stage_display()}")
                    
                    # If new stage requires payment, show appropriate message
                    if payment.stage in ['deposit', 'completion']:
                        messages.info(request, "Payment is now required to proceed.")
                        
                except ValidationError as e:
                    messages.error(request, str(e))
            else:
                messages.error(request, "Cannot advance stage at this time.")
                
        # Handle deposit payment (10%)
        elif action == "pay_deposit":
            return self._handle_stage_payment(request, payment, "deposit", payment.amount * Decimal('0.1'))
            
        # Handle completion payment (90%)
        elif action == "pay_completion":
            return self._handle_stage_payment(request, payment, "completion", payment.amount * Decimal('0.9'))
            
        # Handle KRA stamp duty confirmation
        elif action == "confirm_stamp_duty":
            receipt_file = request.FILES.get("stamp_duty_receipt")
            if receipt_file:
                # Store receipt and mark stamp duty as paid
                from transactions.models import TransactionDocument
                
                TransactionDocument.objects.create(
                    transaction=payment.legal_transaction,
                    document_type='STAMP_DUTY_RECEIPT',
                    file=receipt_file,
                    uploaded_by=request.user,
                    status='pending'
                )
                
                # Mark stamp duty step as completed in closing steps
                stamp_step = payment.closing_steps.filter(code='stamp_duty').first()
                if stamp_step:
                    stamp_step.set_status(PaymentClosingStep.Status.COMPLETED, actor=request.user)
                    
                messages.success(request, "Stamp duty receipt uploaded. Verification in progress.")
            else:
                messages.error(request, "Please upload the stamp duty receipt from KRA.")
                
        # Handle registration confirmation
        elif action == "confirm_registration":
            title_file = request.FILES.get("new_title_deed")
            if title_file:
                from transactions.models import TransactionDocument
                
                TransactionDocument.objects.create(
                    transaction=payment.legal_transaction,
                    document_type='NEW_TITLE_DEED',
                    file=title_file,
                    uploaded_by=request.user,
                    status='verified'
                )
                
                # Mark registration as complete
                reg_step = payment.closing_steps.filter(code='registration').first()
                if reg_step:
                    reg_step.set_status(PaymentClosingStep.Status.COMPLETED, actor=request.user)
                    
                messages.success(request, "New title deed uploaded. Transaction complete!")
            else:
                messages.error(request, "Please upload the new title deed.")
                
        return redirect("payments:legal_workflow", pk=payment.pk)
    
    def _handle_stage_payment(self, request, payment, stage_code, amount):
        """Handle payment for a specific stage (deposit or completion)"""
        method = request.POST.get("method")
        phone_number = request.POST.get("phone_number")
        wallet_pin = request.POST.get("wallet_pin")
        
        if not method:
            messages.error(request, "Please select a payment method.")
            return redirect("payments:legal_workflow", pk=payment.pk)
            
        # Create child payment for this stage
        child_payment = PaymentRequest(
            buyer=payment.buyer,
            seller=payment.seller,
            plot=payment.plot,
            title=f"{stage_code.title()} payment for {payment.plot.title}",
            amount=amount,
            category=PaymentRequest.Category.AGREEMENT_DEPOSIT if stage_code == "deposit" else PaymentRequest.Category.COMPLETION_BALANCE,
            method=method,
            transaction_type=payment.transaction_type,
            status=PaymentRequest.Status.PENDING,
            phone_number=phone_number,
            metadata={
                "workflow_root_id": payment.pk,
                "stage_code": stage_code,
            }
        )
        
        try:
            with transaction.atomic():
                child_payment.full_clean()
                child_payment.save()
                
                if method == PaymentRequest.Method.WALLET:
                    if not wallet_pin:
                        raise ValidationError("Enter your wallet PIN.")
                        
                    result = WalletService.make_payment(
                        user=request.user,
                        amount=amount,
                        pin=wallet_pin,
                        payment_request=child_payment,
                        description=f"{stage_code.title()} payment for {payment.plot.title}"
                    )
                    
                    # Mark payment as successful
                    child_payment.apply_transition("mark_paid", actor=request.user)
                    
                    # Update the parent payment's stage
                    if stage_code == "deposit":
                        payment.metadata['deposit_paid'] = True
                        payment.metadata['deposit_paid_at'] = timezone.now().isoformat()
                        
                        # Advance to next stage (statutory_consents)
                        if hasattr(payment, 'advance_to_next_stage'):
                            payment.advance_to_next_stage(actor=request.user)
                            
                    elif stage_code == "completion":
                        payment.metadata['balance_paid'] = True
                        payment.metadata['balance_paid_at'] = timezone.now().isoformat()
                        
                        # Advance to registration stage
                        if hasattr(payment, 'advance_to_next_stage'):
                            payment.advance_to_next_stage(actor=request.user)
                            
                    payment.save(update_fields=["metadata"])
                    
                    messages.success(request, f"Payment of KES {amount:,.2f} successful via wallet.")
                    
                elif method == PaymentRequest.Method.MPESA_STK:
                    if not phone_number:
                        raise ValidationError("Phone number required for M-Pesa.")
                        
                    phone_number = validate_kenyan_phone(phone_number)
                    child_payment.phone_number = phone_number
                    child_payment.save()
                    
                    callback_url = settings.MPESA_CALLBACK_URL or (
                        f"{settings.SITE_URL.rstrip('/')}{reverse('payments:daraja_callback')}"
                    )
                    
                    stk_data = initiate_stk_push(child_payment, callback_url)
                    
                    child_payment.provider_reference = stk_data.get("CheckoutRequestID")
                    child_payment.save(update_fields=["provider_reference"])
                    
                    messages.success(
                        request,
                        stk_data.get("CustomerMessage", "STK push sent. Check your phone.")
                    )
                    
                elif method == PaymentRequest.Method.BANK_TRANSFER:
                    messages.info(
                        request,
                        f"Bank transfer requested. Transfer KES {amount:,.2f} to:\n"
                        f"Bank: Cooperative Bank of Kenya\n"
                        f"Account: AgriPlot Escrow Services\n"
                        f"Account: 0114123456789\n"
                        f"Reference: {child_payment.internal_reference}"
                    )
                    
                elif method == PaymentRequest.Method.CARD:
                    # Redirect to card payment gateway
                    return redirect("payments:card_payment", pk=child_payment.pk)
                    
                elif method == PaymentRequest.Method.AIRTEL_MONEY:
                    messages.info(request, "Airtel Money payment initiated. Check your phone.")
                    
        except ValidationError as e:
            messages.error(request, str(e))
        except Exception as e:
            logger.exception(f"Payment failed: {e}")
            messages.error(request, f"Payment failed: {str(e)}")
            
        return redirect("payments:legal_workflow", pk=payment.pk)


class AdvanceStageView(LoginRequiredMixin, View):
    """API endpoint to advance to next stage"""
    
    def post(self, request, pk):
        payment = get_object_or_404(PaymentRequest, pk=pk)
        payment = payment.workflow_anchor_payment
        
        # Check permission
        is_buyer = payment.buyer_id == request.user.id
        is_seller = payment.seller_id == request.user.id
        is_admin = user_is_finance_admin(request.user)
        
        if not (is_buyer or is_seller or is_admin):
            return JsonResponse({"success": False, "message": "Permission denied."}, status=403)
            
        if not hasattr(payment, 'advance_to_next_stage'):
            return JsonResponse({"success": False, "message": "Cannot advance stage."}, status=400)
            
        try:
            payment.advance_to_next_stage(actor=request.user)
            
            # Get the presenter for stage info
            presenter = PaymentPresenter(payment)
            
            return JsonResponse({
                "success": True,
                "new_stage": payment.stage,
                "new_stage_display": payment.get_stage_display(),
                "progress_percentage": presenter.legal_transaction_progress,
                "payment_required": payment.stage in ['deposit', 'completion'],
                "redirect_url": reverse("payments:legal_workflow", kwargs={"pk": payment.pk}),
            })
        except ValidationError as e:
            return JsonResponse({"success": False, "message": str(e)}, status=400)


class UploadDocumentView(LoginRequiredMixin, View):
    """API endpoint to upload a document for current stage"""
    
    def post(self, request, pk):
        payment = get_object_or_404(PaymentRequest, pk=pk)
        payment = payment.workflow_anchor_payment
        
        try:
            from transactions.forms import TransactionDocumentForm
            from transactions.models import TransactionDocument

            form_data = request.POST.copy()
            form_files = request.FILES.copy()
            if "file" not in form_files and "document" in form_files:
                form_files["file"] = form_files["document"]

            document_type = form_data.get("document_type")
            existing_doc = None
            if document_type:
                existing_doc = TransactionDocument.objects.filter(
                    transaction=payment.legal_transaction,
                    document_type=document_type,
                ).first()

            doc_form = TransactionDocumentForm(
                form_data,
                form_files,
                instance=existing_doc,
                transaction=payment.legal_transaction,
                user=request.user,
            )
            if not doc_form.is_valid():
                error_messages = []
                for field, errors in doc_form.errors.items():
                    for error in errors:
                        error_messages.append(f"{field}: {error}")
                return JsonResponse({"success": False, "message": " ".join(error_messages) or "Document upload failed."}, status=400)

            doc = doc_form.save()

            # After upload, check if stage can be advanced
            can_advance, message = payment.legal_transaction.can_advance_to_next_stage()

            return JsonResponse({
                "success": True,
                "document_id": doc.id,
                "can_advance": can_advance,
                "message": message,
            })
        except Exception as e:
            return JsonResponse({"success": False, "message": str(e)}, status=500)


class PaymentStagePaymentView(LoginRequiredMixin, View):
    """Handle payment for a specific stage (deposit or completion)"""
    
    def post(self, request, pk):
        payment = get_object_or_404(PaymentRequest, pk=pk)
        payment = payment.workflow_anchor_payment
        
        stage_code = request.POST.get("stage_code")
        method = request.POST.get("method")
        phone_number = request.POST.get("phone_number")
        wallet_pin = request.POST.get("wallet_pin")
        
        if stage_code not in ['deposit', 'completion']:
            return JsonResponse({"success": False, "message": "Invalid stage for payment."}, status=400)
            
        amount = (
            payment.amount * Decimal('0.1') if stage_code == 'deposit'
            else payment.amount * Decimal('0.9')
        ).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

        
        # Create child payment
        child_payment = PaymentRequest(
            buyer=payment.buyer,
            seller=payment.seller,
            plot=payment.plot,
            title=f"{stage_code.title()} payment",
            amount=amount,
            category=PaymentRequest.Category.AGREEMENT_DEPOSIT if stage_code == "deposit" else PaymentRequest.Category.COMPLETION_BALANCE,
            method=method,
            transaction_type=payment.transaction_type,
            status=PaymentRequest.Status.PENDING,
            phone_number=phone_number or "",
            metadata={
                "workflow_root_id": payment.pk,
                "stage_code": stage_code,
            }
        )
        
        try:
            with transaction.atomic():
                child_payment.full_clean()
                child_payment.save()
                
                if method == PaymentRequest.Method.WALLET:
                    if not wallet_pin:
                        raise ValidationError("Wallet PIN required.")
                        
                    result = WalletService.make_payment(
                        user=request.user,
                        amount=amount,
                        pin=wallet_pin,
                        payment_request=child_payment,
                        description=f"{stage_code.title()} payment"
                    )
                    
                    child_payment.apply_transition("mark_paid", actor=request.user)
                    
                    # Update parent payment metadata
                    metadata = dict(payment.metadata or {})
                    metadata[f"{stage_code}_paid"] = True
                    metadata[f"{stage_code}_paid_at"] = timezone.now().isoformat()
                    payment.metadata = metadata
                    payment.save(update_fields=["metadata"])
                    
                    # Advance stage if both payments are complete (for completion stage)
                    if stage_code == "completion" or (stage_code == "deposit" and payment.transaction_type == PaymentRequest.TransactionType.LEASE):
                        if hasattr(payment, 'advance_to_next_stage'):
                            payment.advance_to_next_stage(actor=request.user)
                    
                    return JsonResponse({
                        "success": True,
                        "message": f"Payment of KES {amount:,.2f} successful.",
                        "redirect_url": reverse("payments:legal_workflow", kwargs={"pk": payment.pk}),
                    })
                    
                elif method == PaymentRequest.Method.MPESA_STK:
                    if not phone_number:
                        raise ValidationError("Phone number required.")
                        
                    phone_number = validate_kenyan_phone(phone_number)
                    child_payment.phone_number = phone_number
                    child_payment.save()
                    
                    callback_url = settings.MPESA_CALLBACK_URL or (
                        f"{settings.SITE_URL.rstrip('/')}{reverse('payments:daraja_callback')}"
                    )
                    
                    stk_data = initiate_stk_push(child_payment, callback_url)
                    child_payment.provider_reference = stk_data.get("CheckoutRequestID")
                    child_payment.save(update_fields=["provider_reference"])
                    
                    return JsonResponse({
                        "success": True,
                        "message": stk_data.get("CustomerMessage", "STK push sent."),
                        "payment_id": child_payment.pk,
                        "requires_callback": True,
                    })
                    
                elif method == PaymentRequest.Method.BANK_TRANSFER:
                    return JsonResponse({
                        "success": True,
                        "message": "Bank transfer noted. AgriPlot will confirm receipt within 1\u20132 business days.",
                        "payment_id": child_payment.pk,
                        "poll_url": reverse(
                            "payments:payment_status_poll",
                            kwargs={"pk": payment.pk, "payment_id": child_payment.pk},
                        ),
                    })
                    
                else:
                    return JsonResponse({
                        "success": True,
                        "message": f"{dict(PaymentRequest.Method.choices).get(method)} payment submitted. Pending admin confirmation.",
                        "payment_id": child_payment.pk,
                        "poll_url": reverse(
                            "payments:payment_status_poll",
                            kwargs={"pk": payment.pk, "payment_id": child_payment.pk},
                        ),
                    })
                    
        except ValidationError as e:
            return JsonResponse({"success": False, "message": str(e)}, status=400)
        except Exception as e:
            logger.exception(f"Stage payment failed: {e}")
            return JsonResponse({"success": False, "message": str(e)}, status=500)
