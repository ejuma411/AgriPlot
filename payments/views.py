import logging

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.db.models import Count, Q, Sum
from django.core.mail import send_mail
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse, reverse_lazy
from django.views import View
from django.views.generic import CreateView, DetailView, ListView, TemplateView

from listings.models import Plot, UserInterest
from notifications.notification_service import NotificationService

from .forms import PaymentDisputeForm, PaymentMilestoneForm, PaymentRequestForm
from .models import PaymentDispute, PaymentMilestone, PaymentRequest
from .permissions import (
    user_can_add_milestone,
    user_can_create_payment,
    user_can_open_dispute,
    user_can_transition_payment,
    user_can_view_payment,
    user_is_finance_admin,
)

logger = logging.getLogger(__name__)


PAYMENT_METHOD_CARDS = [
    {
        "name": "M-Pesa STK Push",
        "slug": PaymentRequest.Method.MPESA_STK,
        "description": "Best for buyer commitment fees and reservation deposits straight from the phone.",
        "tone": "green",
    },
    {
        "name": "M-Pesa Paybill / Till",
        "slug": PaymentRequest.Method.MPESA_PAYBILL,
        "description": "Useful when the buyer prefers to pay manually but you still want clean reconciliation.",
        "tone": "gold",
    },
    {
        "name": "Card",
        "slug": PaymentRequest.Method.CARD,
        "description": "Supports remote buyers and investors who need faster digital checkout.",
        "tone": "charcoal",
    },
    {
        "name": "Bank Transfer",
        "slug": PaymentRequest.Method.BANK_TRANSFER,
        "description": "Ideal for larger escrow deposits and enterprise-style settlement paths.",
        "tone": "olive",
    },
    {
        "name": "Airtel Money",
        "slug": PaymentRequest.Method.AIRTEL_MONEY,
        "description": "Expands mobile money reach for buyers who are not strictly in the M-Pesa flow.",
        "tone": "sand",
    },
    {
        "name": "AgriPlot Wallet / Manual Escrow",
        "slug": PaymentRequest.Method.WALLET,
        "description": "Keeps room for internal balances, manual approvals, or partner-led escrow later on.",
        "tone": "green",
    },
]


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

    NotificationService.create_notification(
        user=recipient,
        notification_type="plot_stage_update",
        title=title,
        message=message,
        plot=payment.plot,
    )

    if recipient.email:
        try:
            site_url = getattr(settings, "SITE_URL", "").rstrip("/")
            send_mail(
                subject=subject,
                message=(
                    f"{message}\n\n"
                    f"Open payment workspace: {site_url}{payment_url}"
                ),
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[recipient.email],
                fail_silently=False,
            )
        except Exception:
            logger.exception(
                "Failed to send payment notification email for payment %s",
                payment.pk,
            )


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


class PaymentFlowOverviewView(TemplateView):
    template_name = "payments/flow_overview.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(_journey_context())
        context["method_cards"] = PAYMENT_METHOD_CARDS
        context["dashboard_url"] = reverse("payments:dashboard")
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
            .prefetch_related("milestones")
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
        aggregates = payments.aggregate(
            total_amount=Sum("amount"),
            paid_count=Count("id", filter=Q(status=PaymentRequest.Status.PAID)),
            escrow_count=Count("id", filter=Q(status=PaymentRequest.Status.IN_ESCROW)),
            disputed_count=Count("id", filter=Q(status=PaymentRequest.Status.DISPUTED)),
        )
        context["stats"] = {
            "total_payments": payments.count(),
            "total_amount": aggregates["total_amount"] or 0,
            "paid_count": aggregates["paid_count"] or 0,
            "escrow_count": aggregates["escrow_count"] or 0,
            "disputed_count": aggregates["disputed_count"] or 0,
        }
        context["method_cards"] = PAYMENT_METHOD_CARDS
        context["show_scope_notice"] = not self.request.user.is_authenticated
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

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user
        kwargs["selected_plot"] = self.get_selected_plot()
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["method_cards"] = PAYMENT_METHOD_CARDS
        context["selected_plot"] = self.get_selected_plot()
        context["plot_listing_types"] = {
            str(plot.pk): plot.listing_type
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
                "viewing_fee": str(PaymentRequestForm.calculate_amount(
                    selected_plot,
                    PaymentRequest.TransactionType.PURCHASE,
                    PaymentRequest.Category.VIEWING_FEE,
                ) or ""),
                "reservation_deposit": str(PaymentRequestForm.calculate_amount(
                    selected_plot,
                    PaymentRequest.TransactionType.PURCHASE,
                    PaymentRequest.Category.RESERVATION_DEPOSIT,
                ) or ""),
                "verification_package": str(PaymentRequestForm.calculate_amount(
                    selected_plot,
                    PaymentRequest.TransactionType.PURCHASE,
                    PaymentRequest.Category.VERIFICATION_PACKAGE,
                ) or ""),
                "escrow_deposit": str(PaymentRequestForm.calculate_amount(
                    selected_plot,
                    PaymentRequest.TransactionType.PURCHASE,
                    PaymentRequest.Category.ESCROW_DEPOSIT,
                ) or ""),
                "service_fee": str(PaymentRequestForm.calculate_amount(
                    selected_plot,
                    PaymentRequest.TransactionType.PURCHASE,
                    PaymentRequest.Category.SERVICE_FEE,
                ) or ""),
            },
            "lease": {
                "viewing_fee": str(PaymentRequestForm.calculate_amount(
                    selected_plot,
                    PaymentRequest.TransactionType.LEASE,
                    PaymentRequest.Category.VIEWING_FEE,
                ) or ""),
                "reservation_deposit": str(PaymentRequestForm.calculate_amount(
                    selected_plot,
                    PaymentRequest.TransactionType.LEASE,
                    PaymentRequest.Category.RESERVATION_DEPOSIT,
                ) or ""),
                "verification_package": str(PaymentRequestForm.calculate_amount(
                    selected_plot,
                    PaymentRequest.TransactionType.LEASE,
                    PaymentRequest.Category.VERIFICATION_PACKAGE,
                ) or ""),
                "escrow_deposit": str(PaymentRequestForm.calculate_amount(
                    selected_plot,
                    PaymentRequest.TransactionType.LEASE,
                    PaymentRequest.Category.ESCROW_DEPOSIT,
                ) or ""),
                "service_fee": str(PaymentRequestForm.calculate_amount(
                    selected_plot,
                    PaymentRequest.TransactionType.LEASE,
                    PaymentRequest.Category.SERVICE_FEE,
                ) or ""),
            },
            "service": {
                "viewing_fee": str(PaymentRequestForm.calculate_amount(
                    selected_plot,
                    PaymentRequest.TransactionType.SERVICE,
                    PaymentRequest.Category.VIEWING_FEE,
                ) or ""),
                "reservation_deposit": str(PaymentRequestForm.calculate_amount(
                    selected_plot,
                    PaymentRequest.TransactionType.SERVICE,
                    PaymentRequest.Category.RESERVATION_DEPOSIT,
                ) or ""),
                "verification_package": str(PaymentRequestForm.calculate_amount(
                    selected_plot,
                    PaymentRequest.TransactionType.SERVICE,
                    PaymentRequest.Category.VERIFICATION_PACKAGE,
                ) or ""),
                "escrow_deposit": str(PaymentRequestForm.calculate_amount(
                    selected_plot,
                    PaymentRequest.TransactionType.SERVICE,
                    PaymentRequest.Category.ESCROW_DEPOSIT,
                ) or ""),
                "service_fee": str(PaymentRequestForm.calculate_amount(
                    selected_plot,
                    PaymentRequest.TransactionType.SERVICE,
                    PaymentRequest.Category.SERVICE_FEE,
                ) or ""),
            },
        }
        return context

    def dispatch(self, request, *args, **kwargs):
        decision = user_can_create_payment(request.user)
        if not decision.allowed:
            messages.error(request, decision.reason)
            return redirect("payments:dashboard")
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        payment = form.save(commit=False)
        if self.request.user.is_authenticated:
            payment.buyer = self.request.user

        if payment.plot:
            if payment.plot.landowner_id and payment.plot.landowner.user_id:
                payment.seller = payment.plot.landowner.user
            elif payment.plot.agent_id and payment.plot.agent.user_id:
                payment.seller = payment.plot.agent.user

        payment.status = PaymentRequest.Status.PENDING
        super().form_valid(form)
        payment.add_event("created", "Payment request created in the AgriPlot payments workspace.", actor=self.request.user if self.request.user.is_authenticated else None)
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
        _build_default_milestones(payment)
        _notify_payment_activity(payment, "initiated")
        messages.success(self.request, f"Payment request {payment.internal_reference} created.")
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
        context["payment_dispute"] = getattr(self.object, "dispute", None)
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
        context["is_finance_admin"] = user_is_finance_admin(self.request.user)
        return context


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
