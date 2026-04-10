import logging
import hashlib
import hmac
import json
from datetime import timedelta

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Count, Q, Sum
from django.http import Http404, HttpResponse, HttpResponseBadRequest, HttpResponseForbidden, HttpResponseRedirect, JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse, reverse_lazy
from django.utils.decorators import method_decorator
from django.views import View
from django.views.generic import CreateView, DetailView, ListView, TemplateView
from django.views.decorators.csrf import csrf_exempt

from django.utils import timezone
from listings.models import Plot, UserInterest
from notifications.notification_service import NotificationService

from .forms import (
    PaymentClosingStepForm,
    PaymentDisputeForm,
    PaymentMilestoneForm,
    PaymentRequestForm,
)
from .models import (
    PaymentCertificate,
    PaymentClosingStep,
    PaymentDisbursement,
    PaymentDispute,
    PaymentMilestone,
    PaymentRequest,
)
from .daraja import DarajaError, daraja_ready, extract_callback_metadata, initiate_stk_push
from .paystack import PaystackError, initialize_transaction, paystack_ready, verify_transaction
from .permissions import (
    step_requires_admin_action,
    user_can_add_milestone,
    user_can_create_payment,
    user_can_open_dispute,
    user_can_update_closing_steps,
    user_can_update_specific_closing_step,
    user_can_transition_payment,
    user_can_view_payment,
    user_is_finance_admin,
)

logger = logging.getLogger(__name__)


PAYMENT_METHOD_CARDS = [
    {
        "name": "M-Pesa STK Push",
        "slug": PaymentRequest.Method.MPESA_STK,
        "description": "The primary buyer checkout flow: enter a number, send an STK push, and confirm on the phone.",
        "tone": "green",
    },
]


def _active_payment_provider():
    return getattr(settings, "PAYMENT_PROVIDER", "daraja").lower()


def _gateway_ready():
    if _active_payment_provider() == "daraja":
        return daraja_ready()
    return paystack_ready()


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

    NotificationService.notify_user(
        user=recipient,
        notification_type="plot_stage_update",
        title=title,
        message=full_message,
        plot=payment.plot,
        email_subject=subject,
    )


def _handle_successful_paystack_payment(payment, verification, actor=None):
    _handle_successful_gateway_payment(
        payment,
        provider="paystack",
        verification=verification,
        actor=actor,
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

    if anchor.pk != payment.pk:
        category_to_step = {
            PaymentRequest.Category.AGREEMENT_DEPOSIT: "agreement",
            PaymentRequest.Category.ESCROW_DEPOSIT: "payment_security",
            PaymentRequest.Category.STAMP_DUTY: "stamp_duty",
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

    _maybe_auto_complete_test_deal(payment)
    payment.save(update_fields=["metadata", "updated_at"])


def _paystack_signature_is_valid(raw_body, received_signature):
    if not settings.PAYSTACK_SECRET_KEY or not received_signature:
        return False
    digest = hmac.new(
        settings.PAYSTACK_SECRET_KEY.encode("utf-8"),
        raw_body,
        hashlib.sha512,
    ).hexdigest()
    return hmac.compare_digest(digest, received_signature)


def _journey_context():
    return {
        "journey_steps": [
            {
                "eyebrow": "Buyer journey",
                "title": "Buyer commits with a real payment signal",
                "copy": "The buyer picks a payment method, pays a viewing fee, reservation deposit, or verification package, and receives a clear commitment receipt.",
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
        PaymentRequest.Category.COMMITMENT_FEE: [
            "Commitment fee confirmed",
            "Due diligence lock activated",
            "Search and survey pack delivered",
        ],
        PaymentRequest.Category.VIEWING_FEE: [
            "Buyer payment confirmed",
            "Seller viewing slot scheduled",
            "Viewing completed and recorded",
        ],
        PaymentRequest.Category.RESERVATION_DEPOSIT: [
            "Reservation acknowledged",
            "Seller uploads title and supporting documents",
            "Reservation released or refunded",
        ],
        PaymentRequest.Category.AGREEMENT_DEPOSIT: [
            "Agreement deposit confirmed",
            "Sale agreement signed",
            "Advocate escrow instructions recorded",
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
            "Government valuation captured",
            "Stamp duty payment confirmed",
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
    titles = milestone_templates.get(payment.category, milestone_templates[PaymentRequest.Category.VIEWING_FEE])
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
    if not settings.PAYSTACK_AUTO_RELEASE_TEST_DEALS:
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
        raise ValidationError("AgriPlot could not calculate the amount for this stage.")

    checkout_phone = str(phone_number or "").strip()
    if not checkout_phone:
        raise ValidationError("Enter the M-Pesa number that should receive the STK push.")

    child_payment = PaymentRequest(
        buyer=anchor.buyer,
        seller=anchor.seller,
        plot=anchor.plot,
        title=PaymentRequestForm.build_title(anchor.plot, anchor.transaction_type, payment_category),
        description=f"M-Pesa checkout for {dict(PaymentRequest.Category.choices).get(payment_category, 'payment').lower()}.",
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
    callback_url = settings.MPESA_CALLBACK_URL or (
        f"{settings.SITE_URL.rstrip('/')}{reverse('payments:daraja_callback')}"
    )
    stk_data = initiate_stk_push(child_payment, callback_url)
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
        "Safaricom Daraja STK push sent from the step workspace.",
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
            return PaymentRequest.Category.COMMITMENT_FEE, None
        next_step = active_deal.next_closing_step
        if not next_step:
            return None, active_deal
        step_to_category = {
            "agreement": PaymentRequest.Category.AGREEMENT_DEPOSIT,
            "stamp_duty": PaymentRequest.Category.STAMP_DUTY,
            "completion_docs": PaymentRequest.Category.COMPLETION_BALANCE,
        }
        return step_to_category.get(next_step.code), active_deal
    if transaction_type == PaymentRequest.TransactionType.LEASE:
        if not active_deal:
            return PaymentRequest.Category.COMMITMENT_FEE, None
        next_step = active_deal.next_closing_step
        if not next_step:
            return None, active_deal
        step_to_category = {
            "offer": PaymentRequest.Category.COMMITMENT_FEE,
            "payment_security": PaymentRequest.Category.ESCROW_DEPOSIT,
        }
        return step_to_category.get(next_step.code), active_deal
    return PaymentRequest.Category.COMMITMENT_FEE, None


STEP_PAYMENT_CATEGORY_MAP = {
    "due_diligence": PaymentRequest.Category.COMMITMENT_FEE,
    "agreement": PaymentRequest.Category.AGREEMENT_DEPOSIT,
    "payment_security": PaymentRequest.Category.ESCROW_DEPOSIT,
    "stamp_duty": PaymentRequest.Category.STAMP_DUTY,
    "completion_docs": PaymentRequest.Category.COMPLETION_BALANCE,
}


class PaymentFlowOverviewView(TemplateView):
    template_name = "payments/flow_overview.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(_journey_context())
        context["method_cards"] = PAYMENT_METHOD_CARDS
        context["dashboard_url"] = reverse("payments:dashboard")
        plot = None
        plot_id = self.request.GET.get("plot")
        if plot_id:
            try:
                plot = Plot.objects.select_related("landowner__user", "agent__user").get(pk=plot_id)
            except (Plot.DoesNotExist, ValueError, TypeError):
                plot = None
        context["selected_plot"] = plot
        context["workflow_start_url"] = (
            f"{reverse('payments:create_request')}?plot={plot.pk}" if plot else reverse("payments:create_request")
        )
        return context


class PaymentDashboardView(ListView):
    template_name = "payments/dashboard.html"
    model = PaymentRequest
    context_object_name = "payments"
    paginate_by = 12

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
        requested_type = self.request.GET.get("transaction_type") or self.request.POST.get("transaction_type")
        if selected_plot:
            if selected_plot.listing_type == "sale":
                return PaymentRequest.TransactionType.PURCHASE
            if selected_plot.listing_type == "lease":
                return PaymentRequest.TransactionType.LEASE
        if requested_type in {
            PaymentRequest.TransactionType.PURCHASE,
            PaymentRequest.TransactionType.LEASE,
        }:
            return requested_type
        return PaymentRequest.TransactionType.PURCHASE

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
        if (
            active_deal.transaction_type == PaymentRequest.TransactionType.LEASE
            and forced_category == PaymentRequest.Category.ESCROW_DEPOSIT
        ):
            return active_deal.lease_security_deposit or active_deal.amount
        return None

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
        if (
            requested_workflow_root
            and requested_workflow_root.plot_id == selected_plot.pk
            and requested_workflow_root.transaction_type == transaction_type
        ):
            active_deal = requested_workflow_root.workflow_anchor_payment
            next_step = active_deal.next_closing_step
            if transaction_type == PaymentRequest.TransactionType.PURCHASE:
                step_to_category = {
                    "agreement": PaymentRequest.Category.AGREEMENT_DEPOSIT,
                    "stamp_duty": PaymentRequest.Category.STAMP_DUTY,
                    "completion_docs": PaymentRequest.Category.COMPLETION_BALANCE,
                }
            else:
                step_to_category = {
                    "offer": PaymentRequest.Category.COMMITMENT_FEE,
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
        payment_required = bool(forced_category)
        forced_amount = self.get_forced_stage_amount(active_deal, forced_category)
        if forced_category:
            stage_title = dict(PaymentRequest.Category.choices).get(forced_category, "Current payment stage")
            stage_message = (
                f"AgriPlot has locked this checkout to {stage_title.lower()} based on the current legal step, "
                "so the buyer cannot accidentally pay for the wrong stage."
            )
            if forced_amount is not None:
                stage_message = (
                    f"{stage_message} The amount is fixed to the exact agreed deal amount of KES {forced_amount:,.2f}."
                )
        elif active_deal and active_deal.next_closing_step:
            stage_title = active_deal.next_closing_step.display_title
            stage_message = (
                f"The transaction is currently at '{stage_title}'. This stage needs legal work or evidence, "
                "not a new payment."
            )
        return {
            "forced_category": forced_category,
            "active_deal": active_deal,
            "forced_amount": forced_amount,
            "payment_required": payment_required,
            "stage_title": stage_title,
            "stage_message": stage_message,
        }

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user
        kwargs["selected_plot"] = self.get_selected_plot()
        stage_gate = self.get_stage_gate()
        kwargs["forced_category"] = stage_gate["forced_category"]
        kwargs["active_deal"] = stage_gate["active_deal"]
        kwargs["forced_amount"] = stage_gate["forced_amount"]
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["method_cards"] = PAYMENT_METHOD_CARDS
        context["selected_plot"] = self.get_selected_plot()
        stage_gate = self.get_stage_gate()
        context["stage_gate"] = stage_gate
        context["forced_category"] = stage_gate["forced_category"]
        context["forced_amount"] = stage_gate["forced_amount"]
        context["current_payment_stage_label"] = stage_gate["stage_title"]
        context["current_payment_stage_message"] = stage_gate["stage_message"]
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
        selected_plot = context["selected_plot"]
        context["checkout_amounts"] = {
            "purchase": {
                "commitment_fee": str(PaymentRequestForm.calculate_amount(
                    selected_plot,
                    PaymentRequest.TransactionType.PURCHASE,
                    PaymentRequest.Category.COMMITMENT_FEE,
                ) or ""),
                "reservation_deposit": str(PaymentRequestForm.calculate_amount(
                    selected_plot,
                    PaymentRequest.TransactionType.PURCHASE,
                    PaymentRequest.Category.RESERVATION_DEPOSIT,
                ) or ""),
                "agreement_deposit": str(PaymentRequestForm.calculate_amount(
                    selected_plot,
                    PaymentRequest.TransactionType.PURCHASE,
                    PaymentRequest.Category.AGREEMENT_DEPOSIT,
                ) or ""),
                "escrow_deposit": str(PaymentRequestForm.calculate_amount(
                    selected_plot,
                    PaymentRequest.TransactionType.PURCHASE,
                    PaymentRequest.Category.ESCROW_DEPOSIT,
                ) or ""),
                "stamp_duty": str(PaymentRequestForm.calculate_amount(
                    selected_plot,
                    PaymentRequest.TransactionType.PURCHASE,
                    PaymentRequest.Category.STAMP_DUTY,
                ) or ""),
                "completion_balance": str(PaymentRequestForm.calculate_amount(
                    selected_plot,
                    PaymentRequest.TransactionType.PURCHASE,
                    PaymentRequest.Category.COMPLETION_BALANCE,
                ) or ""),
            },
            "lease": {
                "commitment_fee": str(PaymentRequestForm.calculate_amount(
                    selected_plot,
                    PaymentRequest.TransactionType.LEASE,
                    PaymentRequest.Category.COMMITMENT_FEE,
                ) or ""),
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
        return context

    def dispatch(self, request, *args, **kwargs):
        decision = user_can_create_payment(request.user)
        if not decision.allowed:
            messages.error(request, decision.reason)
            return redirect("payments:dashboard")
        stage_gate = self.get_stage_gate()
        if (
            stage_gate["active_deal"]
            and not stage_gate["payment_required"]
            and stage_gate["active_deal"].next_closing_step
        ):
            next_step = stage_gate["active_deal"].next_closing_step
            messages.info(
                request,
                f"This deal is currently at '{next_step.display_title}'. AgriPlot has opened the legal workspace instead of another payment page.",
            )
            return redirect(_payment_next_workspace_url(stage_gate["active_deal"]))
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        stage_gate = self.get_stage_gate()
        payment = form.save(commit=False)
        if self.request.user.is_authenticated:
            payment.buyer = self.request.user

        if payment.plot:
            if payment.plot.landowner_id and payment.plot.landowner.user_id:
                payment.seller = payment.plot.landowner.user
            elif payment.plot.agent_id and payment.plot.agent.user_id:
                payment.seller = payment.plot.agent.user

        metadata = dict(payment.metadata or {})
        if (
            stage_gate["active_deal"]
            and stage_gate["active_deal"].pk != payment.pk
            and stage_gate["payment_required"]
        ):
            metadata["workflow_root_id"] = stage_gate["active_deal"].pk
        payment.metadata = metadata

        payment.status = PaymentRequest.Status.PENDING
        if not payment.internal_reference:
            payment.internal_reference = PaymentRequest.generate_reference()
        provider = _active_payment_provider()
        try:
            with transaction.atomic():
                payment.save()
                self.object = payment

                if payment.plot and payment.buyer:
                    activity_message = (
                        f"Buyer initiated a {payment.get_transaction_type_display().lower()} flow "
                        f"through checkout. Reference: {payment.internal_reference}."
                    )
                    if (
                        payment.transaction_type == PaymentRequest.TransactionType.LEASE
                        and payment.lease_start_date
                        and payment.lease_end_date
                    ):
                        activity_message = (
                            f"{activity_message} Requested lease period: "
                            f"{payment.lease_start_date:%b %d, %Y} to {payment.lease_end_date:%b %d, %Y}."
                        )
                    UserInterest.objects.update_or_create(
                        user=payment.buyer,
                        plot=payment.plot,
                        defaults={
                            "message": activity_message,
                            "notes": "Created automatically from AgriPlot checkout initiation.",
                            "status": "pending",
                        },
                    )

                _ensure_payment_workflow_seeded(payment)

                if provider == "daraja" and daraja_ready():
                    callback_url = settings.MPESA_CALLBACK_URL or (
                        f"{settings.SITE_URL.rstrip('/')}{reverse('payments:daraja_callback')}"
                    )
                    stk_data = initiate_stk_push(payment, callback_url)
                    payment.provider_reference = (
                        stk_data.get("CheckoutRequestID")
                        or stk_data.get("MerchantRequestID")
                        or payment.internal_reference
                    )
                    metadata = dict(payment.metadata or {})
                    metadata.update(
                        {
                            "daraja_checkout_request_id": stk_data.get("CheckoutRequestID", ""),
                            "daraja_merchant_request_id": stk_data.get("MerchantRequestID", ""),
                            "daraja_customer_message": stk_data.get("CustomerMessage", ""),
                            "daraja_response_description": stk_data.get("ResponseDescription", ""),
                        }
                    )
                    payment.metadata = metadata
                    payment.save(update_fields=["provider_reference", "metadata", "updated_at"])
                    payment.add_event(
                        "created",
                        "Payment request created in the AgriPlot payments workspace.",
                        actor=self.request.user if self.request.user.is_authenticated else None,
                    )
                    payment.add_event(
                        "daraja_stk_initialized",
                        "Safaricom Daraja STK push sent to the buyer's phone.",
                        actor=self.request.user if self.request.user.is_authenticated else None,
                    )
                    _notify_payment_activity(payment, "initiated")
                    messages.success(
                        self.request,
                        stk_data.get("CustomerMessage")
                        or "Safaricom Daraja STK push sent. Complete the prompt on your phone.",
                    )
                    self.success_url = reverse("payments:detail", kwargs={"pk": payment.pk})
                    return HttpResponseRedirect(self.get_success_url())

                if provider == "paystack" and paystack_ready():
                    callback_url = f"{settings.SITE_URL.rstrip('/')}{reverse('payments:paystack_callback')}"
                    checkout_data = initialize_transaction(payment, callback_url)
                    payment.provider_reference = checkout_data.get("reference", payment.internal_reference)
                    metadata = dict(payment.metadata or {})
                    metadata.update(
                        {
                            "paystack_access_code": checkout_data.get("access_code", ""),
                            "paystack_authorization_url": checkout_data.get("authorization_url", ""),
                        }
                    )
                    payment.metadata = metadata
                    payment.save(update_fields=["provider_reference", "metadata", "updated_at"])
                    payment.add_event(
                        "created",
                        "Payment request created in the AgriPlot payments workspace.",
                        actor=self.request.user if self.request.user.is_authenticated else None,
                    )
                    payment.add_event(
                        "paystack_initialized",
                        "Redirecting buyer to Paystack checkout.",
                        actor=self.request.user if self.request.user.is_authenticated else None,
                    )
                    _notify_payment_activity(payment, "initiated")
                    return redirect(checkout_data["authorization_url"])
        except DarajaError as exc:
            logger.exception("Daraja STK push failed for payment %s", payment.internal_reference)
            messages.error(
                self.request,
                f"Safaricom Daraja STK push could not start yet: {exc}",
            )
            target_url = reverse("payments:create_request")
            if payment.plot_id:
                target_url = f"{target_url}?plot={payment.plot_id}"
            return HttpResponseRedirect(target_url)
        except PaystackError as exc:
            logger.exception("Paystack initialization failed for payment %s", payment.internal_reference)
            messages.error(
                self.request,
                f"Paystack checkout could not start yet: {exc}",
            )
            target_url = reverse("payments:create_request")
            if payment.plot_id:
                target_url = f"{target_url}?plot={payment.plot_id}"
            return HttpResponseRedirect(target_url)

        provider_label = "Safaricom Daraja" if provider == "daraja" else "Paystack"
        messages.success(
            self.request,
            f"Payment request {payment.internal_reference} created. Configure {provider_label} to continue with live checkout.",
        )
        self.success_url = reverse("payments:detail", kwargs={"pk": payment.pk})
        return HttpResponseRedirect(self.get_success_url())


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
        context["closing_step_form"] = PaymentClosingStepForm()
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
        context["transaction_stage_matrix"] = workspace_payment.transaction_stage_matrix
        context["transaction_certificates"] = workspace_payment.certificates.all()
        context["disbursement_plan"] = workspace_payment.disbursements.all()
        context["officer_payment_rules"] = workspace_payment.officer_payment_rules
        context["platform_revenue_streams"] = workspace_payment.platform_revenue_streams
        action_labels = [
            ("submit", "Send request"),
            ("mark_paid", "Mark paid"),
            ("move_escrow", "Move to escrow"),
            ("partial_release", "Partial release"),
            ("release", "Release seller funds"),
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
        context["is_payment_buyer"] = (
            self.request.user.is_authenticated
            and self.object.buyer_id == self.request.user.id
        )
        context["payment_provider"] = _active_payment_provider()
        context["gateway_ready"] = _gateway_ready()
        context["daraja_customer_message"] = (self.object.metadata or {}).get(
            "daraja_customer_message", ""
        )
        context["paystack_authorization_url"] = (self.object.metadata or {}).get(
            "paystack_authorization_url", ""
        )
        return context


class PaystackCallbackView(View):
    def get(self, request):
        reference = request.GET.get("reference") or request.GET.get("trxref")
        if not reference:
            messages.error(request, "Missing Paystack reference.")
            return redirect("payments:dashboard")

        payment = get_object_or_404(PaymentRequest, internal_reference=reference)
        if not paystack_ready():
            messages.error(request, "Paystack is not configured yet.")
            return redirect("payments:detail", pk=payment.pk)

        try:
            verification = verify_transaction(reference)
        except PaystackError as exc:
            messages.error(request, f"Could not verify Paystack payment: {exc}")
            return redirect("payments:detail", pk=payment.pk)

        if verification.get("status") == "success":
            _handle_successful_paystack_payment(payment, verification)
            messages.success(
                request,
                f"Payment {payment.internal_reference} verified successfully through Paystack.",
            )
            return redirect(_payment_next_workspace_url(payment))
        else:
            metadata = dict(payment.metadata or {})
            metadata["paystack_verification"] = {
                "status": verification.get("status", ""),
                "gateway_response": verification.get("gateway_response", ""),
                "paid_at": verification.get("paid_at", ""),
                "channel": verification.get("channel", ""),
            }
            payment.metadata = metadata
            payment.save(update_fields=["metadata", "updated_at"])
            messages.warning(
                request,
                f"Paystack returned status '{verification.get('status', 'unknown')}' for this transaction.",
            )
        return redirect("payments:detail", pk=payment.pk)


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
class PaystackWebhookView(View):
    http_method_names = ["post"]

    def post(self, request):
        if not paystack_ready():
            return HttpResponseBadRequest("Paystack not configured.")

        signature = request.headers.get("x-paystack-signature", "")
        if not _paystack_signature_is_valid(request.body, signature):
            return HttpResponseForbidden("Invalid signature.")

        try:
            event = json.loads(request.body.decode("utf-8"))
        except json.JSONDecodeError:
            return HttpResponseBadRequest("Invalid JSON payload.")

        if event.get("event") != "charge.success":
            return JsonResponse({"received": True, "ignored": True})

        data = event.get("data") or {}
        reference = data.get("reference")
        if not reference:
            return HttpResponseBadRequest("Missing payment reference.")

        payment = PaymentRequest.objects.filter(internal_reference=reference).first()
        if not payment:
            return JsonResponse({"received": True, "ignored": True})

        _handle_successful_paystack_payment(payment, data)
        payment.add_event(
            "paystack_webhook_received",
            "Paystack webhook confirmed a successful charge.",
        )
        return JsonResponse({"received": True})


class PaymentClosingStepWorkspaceView(LoginRequiredMixin, TemplateView):
    template_name = "payments/step_workspace.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        payment = _resolve_workspace_payment(self.kwargs["pk"])
        decision = user_can_view_payment(self.request.user, payment)
        if not decision.allowed:
            messages.error(self.request, decision.reason)
            raise Http404(decision.reason)

        payment.ensure_closing_steps()
        payment.ensure_transaction_artifacts()
        step = get_object_or_404(PaymentClosingStep, pk=self.kwargs["step_id"], payment=payment)
        closing_steps = list(payment.closing_steps.all())
        timeline_current_step = payment.current_assigned_step or step
        current_index = next((idx for idx, item in enumerate(closing_steps) if item.pk == step.pk), 0)
        previous_step = closing_steps[current_index - 1] if current_index > 0 else None
        next_step = closing_steps[current_index + 1] if current_index + 1 < len(closing_steps) else None
        completed_stages = [
            item for item in closing_steps if item.status == PaymentClosingStep.Status.COMPLETED
        ]
        blocked_stages = [
            item for item in closing_steps if item.status == PaymentClosingStep.Status.BLOCKED
        ]
        in_progress_stages = [
            item
            for item in closing_steps
            if item.status == PaymentClosingStep.Status.IN_PROGRESS
            and (not timeline_current_step or item.pk != timeline_current_step.pk)
        ]
        upcoming_stages = [
            item
            for item in closing_steps
            if item.status == PaymentClosingStep.Status.PENDING
            and (not timeline_current_step or item.sequence > timeline_current_step.sequence)
        ]
        recorded_submitter = ((payment.metadata or {}).get("step_submitters") or {}).get(step.code, {})
        payment_category = STEP_PAYMENT_CATEGORY_MAP.get(step.code)
        payment_stage_label = (
            dict(PaymentRequest.Category.choices).get(payment_category, "")
            if payment_category
            else ""
        )
        payment_amount = (
            (
                payment.lease_security_deposit
                or payment.amount
            )
            if (
                payment_category == PaymentRequest.Category.ESCROW_DEPOSIT
                and payment.transaction_type == PaymentRequest.TransactionType.LEASE
                and step.code == "payment_security"
            )
            else PaymentRequestForm.calculate_amount(payment.plot, payment.transaction_type, payment_category)
            if payment_category
            else None
        )
        step_action_checklist = {
            "due_diligence": [
                "Open every delivered search, survey, and land-use document.",
                "Confirm the plot details match what you expect on the ground.",
                "Save any review notes before moving to the agreement stage.",
            ],
            "agreement": [
                "Enter the buyer and seller advocate details.",
                "Upload the executed sale agreement once both sides sign.",
                "Pay the agreement deposit through the legal workflow button below.",
            ],
            "lcb_consent": [
                "Capture the Land Control Board or transfer consent reference.",
                "Enter the meeting date.",
                "Upload the consent pack before the next stage can unlock.",
            ],
            "stamp_duty": [
                "Enter the official market value from the government valuer.",
                "Enter the assessed stamp duty amount.",
                "Upload the KRA/eCitizen receipt and clear the payment stage if required.",
            ],
            "completion_docs": [
                "Confirm the original title has been handed over.",
                "Confirm the seller ID/KRA copies are in the file.",
                "Confirm the signed transfer forms are in order, then clear the completion balance stage.",
            ],
            "registration": [
                "Upload the fresh search or title proof showing the buyer as proprietor.",
                "Use this final proof to complete the legal transfer on AgriPlot.",
            ],
        }.get(step.code, [])
        if step.code == "agreement" and payment.transaction_type == PaymentRequest.TransactionType.LEASE:
            step_action_checklist = [
                "Review the generated lease terms, including dates, intended use, notice window, and subject-to-sale wording.",
                "Confirm the good husbandry and soil exit obligations before any digital confirmation is recorded.",
                "Tenant and landowner must both digitally confirm before this step can complete.",
            ]
        released_total = sum(
            item.amount
            for item in payment.disbursements.filter(status=PaymentDisbursement.Status.RELEASED)
        )
        released_to_seller = sum(
            item.amount
            for item in payment.disbursements.filter(
                recipient_role=PaymentDisbursement.RecipientRole.SELLER,
                status=PaymentDisbursement.Status.RELEASED,
            )
        )
        total_paid_by_buyer = payment.workflow_total_paid_amount
        current_escrow_balance = max(total_paid_by_buyer - released_total, 0)
        today = timezone.localdate()
        lease_days_remaining = None
        if payment.transaction_type == PaymentRequest.TransactionType.LEASE and payment.lease_end_date:
            lease_days_remaining = max((payment.lease_end_date - today).days, 0)
        section_kicker = (
            "Your Lease Workspace"
            if payment.transaction_type == PaymentRequest.TransactionType.LEASE
            else "Your Purchase Workspace"
        )
        workspace_title = (
            payment.plot.title if payment.plot else payment.title
        )
        step_update_decision = user_can_update_specific_closing_step(
            self.request.user,
            payment,
            step,
        )
        checkout_phone_initial = ""
        buyer_profile = getattr(payment.buyer, "profile", None) if payment.buyer else None
        if buyer_profile and buyer_profile.phone:
            checkout_phone_initial = buyer_profile.phone
        elif payment.phone_number:
            checkout_phone_initial = payment.phone_number
        settled_payment_statuses = {
            PaymentRequest.Status.PAID,
            PaymentRequest.Status.IN_ESCROW,
            PaymentRequest.Status.PARTIALLY_RELEASED,
            PaymentRequest.Status.RELEASED,
        }
        step_payment_record = None
        if payment_category:
            step_payments = [
                related_payment
                for related_payment in payment.workflow_related_payments
                if related_payment.category == payment_category
                and related_payment.status in settled_payment_statuses
            ]
            if step_payments:
                step_payment_record = step_payments[-1]
        current_workspace_step_url = ""
        if timeline_current_step:
            current_workspace_step_url = reverse(
                "payments:closing_step_workspace",
                kwargs={"pk": payment.pk, "step_id": timeline_current_step.pk},
            )

        context.update(
            {
                "payment": payment,
                "step": step,
                "previous_step": previous_step,
                "next_step": next_step,
                "closing_steps": closing_steps,
                "completed_stages": completed_stages,
                "blocked_stages": blocked_stages,
                "in_progress_stages": in_progress_stages,
                "upcoming_stages": upcoming_stages,
                "timeline_current_step": timeline_current_step,
                "viewing_historical_step": bool(timeline_current_step and timeline_current_step.pk != step.pk),
                "current_workspace_step_url": current_workspace_step_url,
                "is_payment_buyer": payment.buyer_id == self.request.user.id,
                "is_finance_admin": user_is_finance_admin(self.request.user),
                "can_update_closing_steps": step_update_decision.allowed,
                "step_requires_admin_action": step_requires_admin_action(step),
                "step_update_reason": step_update_decision.reason,
                "closing_step_form": PaymentClosingStepForm(instance=step, user=self.request.user),
                "step_payment_category": payment_category,
                "step_payment_label": payment_stage_label,
                "step_payment_amount": payment_amount,
                "step_payment_url": (
                    f"{reverse('payments:create_request')}?plot={payment.plot_id}&transaction_type={payment.transaction_type}&workflow_root_id={payment.workflow_anchor_payment.pk}"
                    if payment.plot_id and payment_category
                    else ""
                ),
                "checkout_phone_initial": checkout_phone_initial,
                "step_payment_record": step_payment_record,
                "step_action_checklist": step_action_checklist,
                "recorded_submitter": recorded_submitter,
                "lease_days_remaining": lease_days_remaining,
                "section_kicker": section_kicker,
                "workspace_title": workspace_title,
                "total_paid_by_buyer": total_paid_by_buyer,
                "current_escrow_balance": current_escrow_balance,
                "released_to_seller": released_to_seller,
                "agriplot_fee": payment.platform_fee_amount,
                "agent_commission": payment.agent_commission_amount,
                "total_price": (
                    payment.lease_contract_value
                    if payment.transaction_type == PaymentRequest.TransactionType.LEASE
                    else payment.sale_price_value
                ),
                "agreement_certificate": payment.certificates.filter(code="lease_compliance").first()
                if payment.transaction_type == PaymentRequest.TransactionType.LEASE
                else payment.certificates.filter(code="completion_notice").first(),
                "buyer_payment_certificate": payment.certificates.filter(
                    code="tenant_payment_ack"
                    if payment.transaction_type == PaymentRequest.TransactionType.LEASE
                    else "buyer_payment_ack"
                ).first(),
            }
        )
        return context


class PaymentClosingStepStkPushView(LoginRequiredMixin, View):
    def post(self, request, pk, step_id):
        payment = _resolve_workspace_payment(pk)
        decision = user_can_view_payment(request.user, payment)
        if not decision.allowed:
            return JsonResponse({"ok": False, "message": decision.reason}, status=403)

        step = get_object_or_404(PaymentClosingStep, pk=step_id, payment=payment)
        if step.code != "payment_security":
            return JsonResponse({"ok": False, "message": "This step does not support inline STK checkout."}, status=400)

        phone_number = request.POST.get("phone_number", "")
        try:
            child_payment, stk_data = _create_workspace_stage_payment(
                payment,
                step,
                phone_number,
                actor=request.user,
            )
        except ValidationError as exc:
            message = exc.messages[0] if getattr(exc, "messages", None) else str(exc)
            return JsonResponse({"ok": False, "message": message}, status=400)
        except DarajaError as exc:
            logger.exception("Workspace Daraja STK push failed for payment %s", payment.pk)
            return JsonResponse(
                {
                    "ok": False,
                    "message": f"Safaricom Daraja STK push could not start yet: {exc}",
                },
                status=502,
            )

        return JsonResponse(
            {
                "ok": True,
                "payment_id": child_payment.pk,
                "reference": child_payment.internal_reference,
                "message": stk_data.get("CustomerMessage")
                or "Safaricom Daraja STK push sent. Complete the prompt on the phone.",
            }
        )


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

        return JsonResponse(
            {
                "ok": True,
                "state": state,
                "status": payment.status,
                "status_label": payment.get_status_display(),
                "message": customer_message,
                "redirect_url": _payment_next_workspace_url(anchor_payment) if state == "paid" else "",
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

        try:
            payment.apply_transition(action, actor=request.user)
        except Exception as exc:
            messages.error(request, str(exc))
            return redirect("payments:detail", pk=payment.pk)
        if action == "mark_paid":
            _notify_payment_activity(payment, "paid")
        messages.success(request, f"{payment.internal_reference} updated to {payment.get_status_display()}.")
        return redirect("payments:detail", pk=payment.pk)


class PaymentClosingStepUpdateView(LoginRequiredMixin, View):
    def post(self, request, pk, step_id):
        payment = _resolve_workspace_payment(pk)
        step = get_object_or_404(PaymentClosingStep, pk=step_id, payment=payment)
        decision = user_can_update_specific_closing_step(request.user, payment, step)
        if not decision.allowed:
            messages.error(request, decision.reason)
            return redirect("payments:closing_step_workspace", pk=payment.pk, step_id=step.pk)

        form = PaymentClosingStepForm(request.POST, request.FILES, instance=step, user=request.user)
        if not form.is_valid():
            messages.error(request, "Please correct the closing tracker update and try again.")
            return redirect("payments:closing_step_workspace", pk=payment.pk, step_id=step.pk)

        updated_step = form.save(commit=False)
        if request.FILES.get("document"):
            updated_step.document = request.FILES["document"]
        updated_step.save()
        target_status = updated_step.status
        if not user_is_finance_admin(request.user):
            target_status = (
                PaymentClosingStep.Status.COMPLETED
                if updated_step.can_mark_complete_with_current_evidence()
                else PaymentClosingStep.Status.IN_PROGRESS
            )
        try:
            updated_step.set_status(
                target_status,
                actor=request.user,
                notes=updated_step.notes,
            )
        except ValidationError as exc:
            messages.error(request, exc.messages[0] if getattr(exc, "messages", None) else str(exc))
            return redirect("payments:closing_step_workspace", pk=payment.pk, step_id=step.pk)
        payment.add_event(
            "closing_step_updated",
            f"Closing tracker updated: {step.title} → {updated_step.get_status_display()}",
            actor=request.user,
        )
        if (
            payment.transaction_type == PaymentRequest.TransactionType.PURCHASE
            and step.code == "registration"
            and updated_step.status == PaymentClosingStep.Status.COMPLETED
        ):
            payment.add_event(
                "sale_registered",
                "Purchase marked legally complete after registry transfer confirmation.",
                actor=request.user,
            )
        messages.success(request, f"Updated closing tracker step: {step.title}.")
        return redirect("payments:closing_step_workspace", pk=payment.pk, step_id=step.pk)


class PaymentMilestoneCreateView(LoginRequiredMixin, View):
    def post(self, request, pk):
        payment = get_object_or_404(PaymentRequest, pk=pk)
        decision = user_can_add_milestone(request.user, payment)
        if not decision.allowed:
            messages.error(request, decision.reason)
            return redirect("payments:detail", pk=payment.pk)

        form = PaymentMilestoneForm(request.POST)
        if form.is_valid():
            milestone = form.save(commit=False)
            milestone.payment = payment
            milestone.sequence = payment.milestones.count() + 1
            milestone.save()
            payment.add_event("milestone_added", f"Milestone added: {milestone.title}", actor=request.user)
            messages.success(request, "Milestone added.")
        else:
            messages.error(request, "Please correct the milestone form and try again.")
        return redirect("payments:detail", pk=payment.pk)


class PaymentDisputeCreateView(LoginRequiredMixin, View):
    def post(self, request, pk):
        payment = get_object_or_404(PaymentRequest, pk=pk)
        decision = user_can_open_dispute(request.user, payment)
        if not decision.allowed:
            messages.error(request, decision.reason)
            return redirect("payments:detail", pk=payment.pk)

        form = PaymentDisputeForm(request.POST)
        if form.is_valid():
            dispute, created = PaymentDispute.objects.get_or_create(
                payment=payment,
                defaults={
                    "opened_by": request.user,
                    "reason": form.cleaned_data["reason"],
                    "details": form.cleaned_data["details"],
                },
            )
            if not created:
                dispute.reason = form.cleaned_data["reason"]
                dispute.details = form.cleaned_data["details"]
                dispute.status = PaymentDispute.Status.UNDER_REVIEW
                dispute.save()
            payment.apply_transition("dispute", actor=request.user)
            payment.add_event("dispute_opened", f"Dispute opened for reason: {dispute.get_reason_display()}", actor=request.user)
            messages.success(request, "Dispute recorded.")
        else:
            messages.error(request, "Please correct the dispute details and try again.")
        return redirect("payments:detail", pk=payment.pk)
