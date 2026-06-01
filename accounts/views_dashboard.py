import logging
from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.contenttypes.models import ContentType
from django.db.models import Avg, Count, Q, Sum
from django.db.models.functions import TruncMonth
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from accounts.access_control import (
    build_dashboard_modules,
    get_default_dashboard_section,
    get_dashboard_landing_url_name,
    humanize_role,
    resolve_access_profile,
)
from listings.models import Plot, UserInterest
from payments.models import (
    PaymentClosingStep,
    PaymentRequest,
    Wallet,
    WalletDepositRequest,
    WalletTransaction,
    WalletWithdrawalRequest,
)
from payments.wallet_service import WalletService
from payments.permissions import step_requires_admin_action, user_is_finance_admin
from security.models import AuditLog
from verification.models import VerificationStatus, VerificationTask
from transactions.models import Transaction
from accounts.views_profile import _build_profile_context
from accounts.forms import AccountDetailsForm, AgentDetailsForm

logger = logging.getLogger(__name__)


def _section_redirect(section, query_dict=None):
    params = {"section": section}
    if query_dict:
        params.update(query_dict)
    return redirect(f"{reverse('listings:dashboard_router')}?{urlencode(params, doseq=True)}")


def _role_profile_type(user):
    if hasattr(user, "agent"):
        return "Agent"
    if hasattr(user, "landownerprofile"):
        return "Landowner"
    if hasattr(user, "extension_officer"):
        return "Extension Officer"
    if hasattr(user, "land_surveyor"):
        return "Land Surveyor"
    return "User"


def _workspace_plots_for_user(user, is_agent, is_landowner, is_finance_admin):
    if is_agent:
        return Plot.objects.filter(agent=user.agent)
    if is_landowner:
        return Plot.objects.filter(landowner=user.landownerprofile)
    if user.is_superuser or is_finance_admin or user.is_staff:
        return Plot.objects.all()
    return Plot.objects.none()


@login_required
def staff_dashboard(request):
    """Single staff workspace entry point with permission-filtered sections."""
    import time

    start_time = time.time()
    access_profile = resolve_access_profile(request.user)
    is_agent = hasattr(request.user, "agent")
    is_landowner = hasattr(request.user, "landownerprofile")
    is_buyer = getattr(getattr(request.user, "profile", None), "role", "") == "buyer"
    is_staff = access_profile.is_staff_workspace
    is_finance_admin = user_is_finance_admin(request.user)
    is_extension = "extension_officer" in access_profile.roles
    is_surveyor = "land_surveyor" in access_profile.roles

    if not (
        is_agent
        or is_landowner
        or is_buyer
        or access_profile.is_staff_workspace
        or request.user.is_superuser
    ):
        messages.error(request, "You don't have access to this dashboard.")
        return redirect("listings:home")

    allowed_sections = {"overview", "profile", "settings"}
    if is_agent or is_landowner:
        allowed_sections.update({"portfolio", "inbox", "analytics"})
    if access_profile.can("wallet.view_own"):
        allowed_sections.add("wallet")
    if access_profile.can("tasks.view_assigned"):
        allowed_sections.add("tasks")
    if access_profile.can("verification.review"):
        allowed_sections.add("verification")
    if access_profile.can("finance.view_escrow"):
        allowed_sections.add("finance")
    if access_profile.can("transactions.view_own"):
        allowed_sections.add("transactions")
    if access_profile.can("audit.view_all"):
        allowed_sections.add("audit")
    if access_profile.can("users.manage"):
        allowed_sections.add("governance")

    default_section = get_default_dashboard_section(access_profile)
    active_section = request.GET.get("section") or default_section
    if active_section not in allowed_sections:
        active_section = default_section

    context = {
        "is_agent": is_agent,
        "is_landowner": is_landowner,
        "is_staff_dashboard_admin": is_staff or is_finance_admin,
        "is_buyer": is_buyer,
        "profile_type": _role_profile_type(request.user),
        "profile": (
            request.user.agent
            if is_agent
            else request.user.landownerprofile
            if is_landowner
            else None
        ),
        "access_profile": access_profile,
        "workspace_label": "Operations Workspace" if access_profile.is_staff_workspace else "Client Workspace",
        "primary_role_label": humanize_role(access_profile.primary_role),
        "role_labels": [humanize_role(role) for role in access_profile.roles],
        "active_section": active_section,
        "allowed_sections": sorted(allowed_sections),
    }

    plots = _workspace_plots_for_user(
        request.user,
        is_agent=is_agent,
        is_landowner=is_landowner,
        is_finance_admin=is_finance_admin,
    )

    plot_content_type = ContentType.objects.get_for_model(Plot)
    total_plots = plots.count()
    plot_ids = list(plots.values_list("id", flat=True))

    verification_map = {}
    if plot_ids:
        statuses = VerificationStatus.objects.filter(
            content_type=plot_content_type, object_id__in=plot_ids
        )
        for status in statuses:
            verification_map[status.object_id] = status

    for plot in plots:
        plot.verification_status = verification_map.get(plot.id)

    verification_statuses = VerificationStatus.objects.filter(
        content_type=plot_content_type, object_id__in=plot_ids
    )
    verified_plots = verification_statuses.filter(current_stage="approved").count()
    in_review_plots = verification_statuses.filter(current_stage="admin_review").count()
    pending_plots = verification_statuses.filter(
        current_stage="document_uploaded"
    ).count()
    rejected_plots = verification_statuses.filter(current_stage="rejected").count()

    verification = None
    if is_agent:
        from accounts.models import Agent

        verification = VerificationStatus.objects.filter(
            content_type=ContentType.objects.get_for_model(Agent),
            object_id=request.user.agent.id,
        ).first()
    elif is_landowner:
        from accounts.models import LandownerProfile

        verification = VerificationStatus.objects.filter(
            content_type=ContentType.objects.get_for_model(LandownerProfile),
            object_id=request.user.landownerprofile.id,
        ).first()

    recent_interests = list(
        UserInterest.objects.filter(plot__in=plots).select_related("plot", "user").order_by("-created_at")[:5]
    )
    for interest in recent_interests:
        interest.buyer_name = interest.user.get_full_name() or interest.user.username
        interest.activity_label = (
            "Checkout Started"
            if "checkout" in (interest.message or "").lower()
            else "Buyer Inquiry"
            if interest.message
            else "Saved Interest"
        )

    context.update(
        {
            "total_plots": total_plots,
            "verified_plots": verified_plots,
            "in_review_plots": in_review_plots,
            "pending_plots": pending_plots,
            "rejected_plots": rejected_plots,
            "verified_percentage": (verified_plots / total_plots * 100)
            if total_plots > 0
            else 0,
            "in_review_percentage": (in_review_plots / total_plots * 100)
            if total_plots > 0
            else 0,
            "pending_percentage": (pending_plots / total_plots * 100)
            if total_plots > 0
            else 0,
            "rejected_percentage": (rejected_plots / total_plots * 100)
            if total_plots > 0
            else 0,
            "plots": plots.order_by("-created_at")[:6],
            "recent_interests": recent_interests,
            "verification": verification,
            "recent_interests_count": len(recent_interests),
        }
    )

    badge_counts = {}
    primary_queue = []
    queue_title = "Assigned Work"
    queue_description = "Only the work relevant to your current permissions is shown here."

    if is_staff or is_finance_admin:
        context["stats"] = {
            "pending_review": VerificationStatus.objects.filter(
                content_type=plot_content_type, current_stage="document_uploaded"
            ).count(),
            "pending_registry_search": VerificationTask.objects.filter(
                verification_type="registry_search",
                status="pending",
            ).count(),
            "in_progress": VerificationStatus.objects.filter(
                content_type=plot_content_type,
                current_stage__in=[
                    "api_verification_started",
                    "title_search_completed",
                    "admin_review",
                ],
            ).count(),
            "approved_today": VerificationStatus.objects.filter(
                content_type=plot_content_type,
                approved_at__date=timezone.now().date(),
            ).count(),
        }
        context["task_stats"] = {
            "pending": VerificationTask.objects.filter(status="pending").count(),
        }
        context["my_tasks_count"] = VerificationTask.objects.filter(
            assigned_to=request.user, status="in_progress"
        ).count()

        payment_admin_tasks = []
        payment_queryset = (
            PaymentRequest.objects.select_related("plot", "buyer", "seller")
            .prefetch_related("closing_steps")
            .filter(
                transaction_type__in=[
                    PaymentRequest.TransactionType.PURCHASE,
                    PaymentRequest.TransactionType.LEASE,
                ]
            )
            .exclude(
                status__in=[
                    PaymentRequest.Status.REFUNDED,
                    PaymentRequest.Status.CANCELLED,
                    PaymentRequest.Status.FAILED,
                ]
            )
            .order_by("-created_at")
        )
        for payment in payment_queryset:
            payment.ensure_closing_steps()
            for step in payment.closing_steps.exclude(status=PaymentClosingStep.Status.COMPLETED).order_by("sequence"):
                if step_requires_admin_action(step):
                    payment_admin_tasks.append(
                        {
                            "payment": payment,
                            "step": step,
                            "owner_label": step.responsible_party_label,
                            "is_current": payment.current_assigned_step and payment.current_assigned_step.pk == step.pk,
                        }
                    )

        context["payment_admin_tasks"] = payment_admin_tasks
        context["payment_admin_task_count"] = len(payment_admin_tasks)
        context["show_payment_admin_tasks"] = True
        badge_counts["payment_admin_task_count"] = len(payment_admin_tasks)
        badge_counts["wallet_pending_count"] = (
            WalletDepositRequest.objects.filter(status__in=["pending", "processing"]).count()
            + WalletWithdrawalRequest.objects.filter(status__in=["pending", "processing"]).count()
        )

        recent_audit_logs = AuditLog.objects.select_related("user").order_by("-created_at")[:6]
        context["recent_audit_logs"] = recent_audit_logs

        pending_verifications = VerificationStatus.objects.filter(
            content_type=plot_content_type,
            current_stage="document_uploaded",
        ).order_by("-created_at")[:8]
        pending_plot_ids = [status.object_id for status in pending_verifications]
        context["verification_pending_plots"] = Plot.objects.filter(id__in=pending_plot_ids).select_related(
            "landowner__user",
            "agent__user",
        )

    if is_extension:
        context["extension_tasks_count"] = VerificationTask.objects.filter(
            assigned_to=request.user,
            status="in_progress",
            verification_type="extension_review",
        ).count()
        badge_counts["extension_tasks_count"] = context["extension_tasks_count"]

    if is_surveyor:
        context["surveyor_tasks_count"] = VerificationTask.objects.filter(
            assigned_to=request.user,
            status="in_progress",
            verification_type="surveyor_inspection",
        ).count()
        badge_counts["surveyor_tasks_count"] = context["surveyor_tasks_count"]

    can_manage_task_queue = (
        request.user.is_superuser
        or access_profile.can("tasks.view_all")
        or access_profile.can("tasks.assign")
        or access_profile.can("verification.review")
    )

    badge_counts["pending_review_count"] = context.get("stats", {}).get("pending_review", 0)
    badge_counts["unassigned_tasks_count"] = context.get("task_stats", {}).get("pending", 0)
    badge_counts["my_tasks_count"] = context.get("my_tasks_count", 0)
    context["dashboard_modules"] = build_dashboard_modules(access_profile, badge_counts)
    context["can_manage_task_queue"] = can_manage_task_queue

    if access_profile.can("finance.view_escrow") and context.get("payment_admin_tasks"):
        queue_title = "Finance Control Queue"
        queue_description = "Escrow and payout items waiting for controlled action."
        primary_queue = [
            {
                "title": item["step"].display_title,
                "subtitle": item["payment"].internal_reference,
                "meta": item["owner_label"],
                "status": item["step"].get_status_display(),
                "url": reverse(
                    "payments:closing_step_workspace",
                    args=[item["payment"].pk, item["step"].pk],
                ),
            }
            for item in context["payment_admin_tasks"][:5]
        ]
    elif access_profile.can("tasks.view_assigned"):
        queue_title = "Task Inbox"
        queue_description = "Assigned work items move through this queue instead of exposing unrelated records."
        task_filter = Q(assigned_to=request.user, status__in=["pending", "in_progress"])
        if can_manage_task_queue:
            task_filter |= Q(
                assigned_to__isnull=True,
                verification_type="document_review",
                status="pending",
            )
        task_queryset = (
            VerificationTask.objects.filter(task_filter)
            .select_related("plot", "assigned_to")
            .distinct()
            .order_by("status", "deadline_at", "-assigned_at")[:6]
        )
        primary_queue = [
            {
                "title": task.plot.title if task.plot else task.get_verification_type_display(),
                "subtitle": task.get_verification_type_display(),
                "meta": task.plot.county if task.plot and task.plot.county else "Assigned case",
                "status": task.get_status_display(),
                "url": (
                    reverse("verification:conduct_extension_review", args=[task.pk])
                    if task.verification_type == "extension_review"
                    else reverse("verification:conduct_surveyor_inspection", args=[task.pk])
                    if task.verification_type == "surveyor_inspection"
                    else reverse("verification:complete_task", args=[task.pk])
                ),
            }
            for task in task_queryset
        ]

    if not primary_queue and (is_agent or is_landowner):
        queue_title = "Client Pipeline"
        queue_description = "Your listing and buyer activity stays inside your own workspace."
        primary_queue = [
            {
                "title": interest.plot.title,
                "subtitle": interest.activity_label,
                "meta": interest.buyer_name,
                "status": interest.get_status_display(),
                "url": None,
            }
            for interest in recent_interests[:5]
        ]

    context["primary_queue"] = primary_queue
    context["primary_queue_title"] = queue_title
    context["primary_queue_description"] = queue_description

    task_filter = Q(assigned_to=request.user, status__in=["pending", "in_progress"])
    if can_manage_task_queue:
        task_filter |= Q(
            assigned_to__isnull=True,
            verification_type="document_review",
            status="pending",
        )
    task_queryset = (
        VerificationTask.objects.filter(task_filter)
        .select_related("plot", "assigned_to")
        .distinct()
        .order_by("status", "deadline_at", "-assigned_at")[:10]
    )
    context["workspace_tasks"] = task_queryset

    portfolio_plots = plots.prefetch_related(
        "surveyor_reports", "pricing_suggestions", "soil_reports"
    ).order_by("-created_at")[:8]
    for plot in portfolio_plots:
        plot.sale_pricing_recommendation = plot.pricing_recommendation("sale")
    context["portfolio_plots"] = portfolio_plots

    inbox_items = (
        UserInterest.objects.filter(plot__in=plots)
        .select_related("user", "plot", "user__profile")
        .order_by("-created_at")[:8]
    )
    for interest in inbox_items:
        interest.buyer_name = interest.user.get_full_name() or interest.user.username
        interest.buyer_email = interest.user.email or "No email provided"
        interest.buyer_phone = getattr(getattr(interest.user, "profile", None), "phone", "")
        interest.activity_label = (
            "Checkout Started"
            if "checkout" in (interest.message or "").lower()
            else "Buyer Inquiry"
            if interest.message
            else "Saved Interest"
        )
    context["workspace_inbox"] = inbox_items

    monthly_stats = (
        plots.annotate(month=TruncMonth("created_at"))
        .values("month")
        .annotate(count=Count("id"))
        .order_by("month")
    ) if (is_agent or is_landowner) else []
    context["analytics_cards"] = {
        "total_interests": UserInterest.objects.filter(plot__in=plots).count() if (is_agent or is_landowner) else 0,
        "avg_price": plots.aggregate(avg=Avg("price"))["avg"] or 0 if (is_agent or is_landowner) else 0,
        "for_sale": plots.filter(listing_type="sale").count() if (is_agent or is_landowner) else 0,
        "for_lease": plots.filter(listing_type="lease").count() if (is_agent or is_landowner) else 0,
        "monthly_stats": list(monthly_stats),
    }

    finance_payments = (
        PaymentRequest.objects.select_related("buyer", "seller", "plot")
        .order_by("-created_at")[:8]
        if access_profile.can("finance.view_escrow")
        else []
    )
    context["finance_payments"] = finance_payments

    if access_profile.can("wallet.view_own"):
        wallet = WalletService.get_or_create_wallet(request.user)
        wallet_transactions = list(
            wallet.transactions.select_related("payment_request", "related_payment").order_by("-created_at")[:8]
        )
        purchase_wallet_count = wallet.transactions.filter(
            Q(payment_request__transaction_type=PaymentRequest.TransactionType.PURCHASE)
            | Q(related_payment__transaction_type=PaymentRequest.TransactionType.PURCHASE)
        ).count()
        lease_wallet_count = wallet.transactions.filter(
            Q(payment_request__transaction_type=PaymentRequest.TransactionType.LEASE)
            | Q(related_payment__transaction_type=PaymentRequest.TransactionType.LEASE)
        ).count()
        total_deposit_amount = wallet.transactions.filter(
            type=WalletTransaction.TYPE_CREDIT,
            status=WalletTransaction.STATUS_SUCCESS,
        ).aggregate(total=Sum("amount"))["total"] or 0
        total_debit_amount = wallet.transactions.filter(
            type=WalletTransaction.TYPE_DEBIT,
            status=WalletTransaction.STATUS_SUCCESS,
        ).aggregate(total=Sum("amount"))["total"] or 0
        context["wallet"] = wallet
        context["wallet_transactions"] = wallet_transactions
        context["wallet_cards"] = {
            "available_balance": wallet.balance,
            "has_pin": bool(wallet.pin_hash),
            "deposit_total": total_deposit_amount,
            "debit_total": total_debit_amount,
            "purchase_payments": purchase_wallet_count,
            "lease_payments": lease_wallet_count,
        }

    if access_profile.can("wallet.manage"):
        total_wallet_balance = Wallet.objects.aggregate(total=Sum("balance"))["total"] or 0
        total_wallets = Wallet.objects.count()
        pending_deposits = WalletDepositRequest.objects.filter(status__in=["pending", "processing"]).order_by("-created_at")[:6]
        pending_withdrawals = WalletWithdrawalRequest.objects.filter(status__in=["pending", "processing"]).order_by("-created_at")[:6]
        recent_wallet_transactions = WalletTransaction.objects.select_related(
            "wallet__user", "payment_request", "related_payment"
        ).order_by("-created_at")[:8]
        deposit_volume = WalletTransaction.objects.filter(
            type=WalletTransaction.TYPE_CREDIT,
            status=WalletTransaction.STATUS_SUCCESS,
        ).aggregate(total=Sum("amount"))["total"] or 0
        payout_volume = WalletTransaction.objects.filter(
            type=WalletTransaction.TYPE_DEBIT,
            status=WalletTransaction.STATUS_SUCCESS,
        ).aggregate(total=Sum("amount"))["total"] or 0
        context["finance_wallet_cards"] = {
            "wallets": total_wallets,
            "balances": total_wallet_balance,
            "pending_deposits": WalletDepositRequest.objects.filter(status__in=["pending", "processing"]).count(),
            "pending_withdrawals": WalletWithdrawalRequest.objects.filter(status__in=["pending", "processing"]).count(),
            "deposit_volume": deposit_volume,
            "payout_volume": payout_volume,
        }
        context["finance_wallet_requests"] = {
            "deposits": pending_deposits,
            "withdrawals": pending_withdrawals,
            "transactions": recent_wallet_transactions,
        }

    if active_section == "transactions":
        user_transactions = Transaction.objects.filter(
            Q(buyer=request.user) | Q(seller=request.user)
        ).select_related("plot", "buyer", "seller").prefetch_related("milestones")
        context["transactions"] = user_transactions

    if access_profile.can("users.manage"):
        from django.contrib.auth import get_user_model

        User = get_user_model()
        total_users = User.objects.count()
        total_transactions = PaymentRequest.objects.count()
        completed_transactions = PaymentRequest.objects.filter(status="released").count()
        context["governance_cards"] = {
            "total_users": total_users,
            "total_transactions": total_transactions,
            "completed_transactions": completed_transactions,
            "pending_transactions": total_transactions - completed_transactions,
        }

    if active_section == "profile":
        profile_context = _build_profile_context(request.user)
        context.update(profile_context)
        context.update({
            "account_form": AccountDetailsForm(user=request.user),
            "agent_form": AgentDetailsForm(instance=request.user.agent) if is_agent else None,
        })

    if active_section == "settings":
        context.update(_build_profile_context(request.user))

    logger.info("Dashboard loaded in %.2f seconds", time.time() - start_time)
    return render(request, "accounts/dashboard/dashboard.html", context)


@login_required
def my_plots(request):
    return _section_redirect("portfolio")


@login_required
def plot_verification_detail(request, plot_id):
    return redirect(f"{reverse('listings:dashboard_router')}?section=verification")


@login_required
def saved_plots(request):
    return redirect(f"{reverse('listings:dashboard_router')}?section=overview")


@login_required
def buyer_interests(request):
    return redirect(f"{reverse('listings:notifications_inbox')}?filter=messages")


@login_required
def update_interest_status(request, interest_id):
    interest = get_object_or_404(UserInterest, id=interest_id)

    is_agent = hasattr(request.user, "agent") and interest.plot.agent == request.user.agent
    is_landowner = (
        hasattr(request.user, "landownerprofile")
        and interest.plot.landowner == request.user.landownerprofile
    )

    if not (is_agent or is_landowner or request.user.is_superuser):
        messages.error(request, "You don't have permission to update this interest.")
        return redirect("listings:home")

    if request.method == "POST":
        new_status = request.POST.get("status")
        notes = request.POST.get("notes", "")

        if new_status in dict(UserInterest.STATUS_CHOICES).keys():
            interest.status = new_status
            if notes:
                interest.notes = notes
            interest.save()
            messages.success(
                request, f"Interest status updated to {interest.get_status_display()}."
            )
        else:
            messages.error(request, "Invalid status.")

    return redirect("listings:buyer_interests")


@login_required
def dashboard_analytics(request):
    return _section_redirect("analytics")


@login_required
def dashboard_router(request):
    if not request.user.is_authenticated:
        return redirect("listings:home")
    access_profile = resolve_access_profile(request.user)
    landing_url_name = get_dashboard_landing_url_name(access_profile)
    if landing_url_name != "listings:dashboard_router":
        return redirect(landing_url_name)
    return staff_dashboard(request)
