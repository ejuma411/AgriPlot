import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.contenttypes.models import ContentType
from django.core.paginator import Paginator
from django.db.models import Avg, Count, Q
from django.db.models.functions import TruncMonth
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from listings.models import ContactRequest, Plot, UserInterest
from verification.models import VerificationLog, VerificationStatus, VerificationTask

logger = logging.getLogger(__name__)


@login_required
def staff_dashboard(request):
    """Dashboard for agents/landowners with optional staff features."""
    import time

    start_time = time.time()
    is_agent = hasattr(request.user, "agent")
    is_landowner = hasattr(request.user, "landownerprofile")
    is_staff = request.user.is_staff or request.user.is_superuser
    is_extension = hasattr(request.user, "extension_officer")
    is_surveyor = hasattr(request.user, "land_surveyor")

    if is_extension and not request.user.is_superuser:
        return redirect("verification:extension_dashboard")
    if is_surveyor and not request.user.is_superuser:
        return redirect("verification:surveyor_dashboard")
    if not (is_agent or is_landowner or is_staff or request.user.is_superuser):
        messages.error(request, "You don't have access to this dashboard.")
        return redirect("listings:home")

    context = {
        "is_agent": is_agent,
        "is_landowner": is_landowner,
        "profile_type": "Agent" if is_agent else "Landowner",
        "profile": (
            request.user.agent
            if is_agent
            else request.user.landownerprofile
            if is_landowner
            else None
        ),
    }

    if is_agent:
        plots = Plot.objects.filter(agent=request.user.agent)
    elif is_landowner:
        plots = Plot.objects.filter(landowner=request.user.landownerprofile)
    elif request.user.is_superuser:
        plots = Plot.objects.all()
    else:
        plots = Plot.objects.none()

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
        UserInterest.objects.filter(plot__in=plots).order_by("-created_at")[:5]
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

    if is_staff:
        context["stats"] = {
            "pending_review": VerificationStatus.objects.filter(
                content_type=plot_content_type, current_stage="document_uploaded"
            ).count(),
        }
        context["task_stats"] = {
            "pending": VerificationTask.objects.filter(status="pending").count(),
        }
        context["my_tasks_count"] = VerificationTask.objects.filter(
            assigned_to=request.user, status="in_progress"
        ).count()

    if is_extension:
        context["extension_tasks_count"] = VerificationTask.objects.filter(
            assigned_to=request.user,
            status="in_progress",
            verification_type="extension_review",
        ).count()

    logger.info("Dashboard loaded in %.2f seconds", time.time() - start_time)
    return render(request, "accounts/dashboard/staff_dashboard.html", context)


@login_required
def my_plots(request):
    is_agent = hasattr(request.user, "agent")
    is_landowner = hasattr(request.user, "landownerprofile")

    if not (is_agent or is_landowner or request.user.is_superuser):
        messages.error(request, "You need to be a landowner or agent to view plots.")
        return redirect("listings:home")

    if is_agent:
        plots = Plot.objects.filter(agent=request.user.agent)
    elif is_landowner:
        plots = Plot.objects.filter(landowner=request.user.landownerprofile)
    else:
        plots = Plot.objects.all()

    status_filter = request.GET.get("status", "all")
    if status_filter != "all":
        verification_stage = (
            "document_uploaded" if status_filter == "pending" else status_filter
        )
        plots = plots.filter(verification__current_stage=verification_stage)

    search_query = request.GET.get("search", "")
    if search_query:
        plots = plots.filter(
            Q(title__icontains=search_query) | Q(location__icontains=search_query)
        )

    paginator = Paginator(plots.order_by("-created_at"), 10)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    status_counts = {
        "all": plots.count(),
        "approved": plots.filter(verification__current_stage="approved").count(),
        "admin_review": plots.filter(verification__current_stage="admin_review").count(),
        "pending": plots.filter(verification__current_stage="document_uploaded").count(),
        "rejected": plots.filter(verification__current_stage="rejected").count(),
    }

    context = {
        "page_obj": page_obj,
        "status_filter": status_filter,
        "search_query": search_query,
        "status_counts": status_counts,
        "total_plots": plots.count(),
        "is_agent": is_agent,
        "is_landowner": is_landowner,
    }

    return render(request, "accounts/dashboard/my_plots.html", context)


@login_required
def plot_verification_detail(request, plot_id):
    plot = get_object_or_404(Plot, id=plot_id)

    is_agent = hasattr(request.user, "agent") and plot.agent == request.user.agent
    is_landowner = (
        hasattr(request.user, "landownerprofile")
        and plot.landowner == request.user.landownerprofile
    )

    if not (is_agent or is_landowner or request.user.is_staff or request.user.is_superuser):
        messages.error(request, "You don't have permission to view this plot.")
        return redirect("listings:home")

    verification, created = VerificationStatus.objects.get_or_create(
        content_type=ContentType.objects.get_for_model(Plot),
        object_id=plot.id,
        defaults={
            "current_stage": "document_uploaded",
            "document_uploaded_at": timezone.now(),
        },
    )
    if created:
        logger.info("Created missing verification status for plot %s", plot.id)

    has_title_deed = bool(plot.title_deed)
    has_official_search = bool(plot.official_search)
    has_landowner_id = bool(plot.landowner_id_doc)
    has_kra_pin = bool(plot.kra_pin)
    has_soil_report = bool(plot.soil_report)

    verification_docs = plot.verification_docs.all()
    verification_logs = (
        VerificationLog.objects.filter(plot=plot)
        .select_related("verified_by")
        .order_by("-created_at")[:50]
    )

    profile_type = "Buyer"
    if hasattr(request.user, "agent"):
        profile_type = "Agent"
    elif hasattr(request.user, "landownerprofile"):
        profile_type = "Landowner"
    elif hasattr(request.user, "extension_officer"):
        profile_type = "Extension Officer"
    elif hasattr(request.user, "land_surveyor"):
        profile_type = "Land Surveyor"

    context = {
        "plot": plot,
        "verification": verification,
        "verification_status": verification,
        "has_title_deed": has_title_deed,
        "has_official_search": has_official_search,
        "has_landowner_id": has_landowner_id,
        "has_kra_pin": has_kra_pin,
        "has_soil_report": has_soil_report,
        "verification_docs": verification_docs,
        "documents_complete": all(
            [has_title_deed, has_official_search, has_landowner_id, has_kra_pin]
        ),
        "verification_logs": verification_logs,
        "profile_type": profile_type,
    }

    return render(request, "accounts/dashboard/plot_verification_detail.html", context)


@login_required
def buyer_interests(request):
    is_agent = hasattr(request.user, "agent")
    is_landowner = hasattr(request.user, "landownerprofile")

    if not (is_agent or is_landowner):
        messages.error(request, "Only agents and landowners can view buyer interests.")
        return redirect("listings:home")

    if is_agent:
        interests = UserInterest.objects.filter(plot__agent=request.user.agent)
    else:
        interests = UserInterest.objects.filter(plot__landowner=request.user.landownerprofile)

    status_filter = request.GET.get("status", "all")
    if status_filter != "all":
        interests = interests.filter(status=status_filter)

    search_query = request.GET.get("search", "")
    if search_query:
        interests = interests.filter(
            Q(user__username__icontains=search_query)
            | Q(plot__title__icontains=search_query)
            | Q(message__icontains=search_query)
        )

    paginator = Paginator(interests.order_by("-created_at"), 10)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    status_counts = {
        "all": interests.count(),
        "pending": interests.filter(status="pending").count(),
        "contacted": interests.filter(status="contacted").count(),
        "scheduled": interests.filter(status="scheduled").count(),
        "rejected": interests.filter(status="rejected").count(),
        "accepted": interests.filter(status="accepted").count(),
    }

    context = {
        "page_obj": page_obj,
        "status_filter": status_filter,
        "search_query": search_query,
        "status_counts": status_counts,
    }

    return render(request, "accounts/dashboard/buyer_interests.html", context)


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
    is_agent = hasattr(request.user, "agent")
    is_landowner = hasattr(request.user, "landownerprofile")

    if not (is_agent or is_landowner):
        messages.error(request, "Only agents and landowners can view analytics.")
        return redirect("listings:home")

    if is_agent:
        plots = Plot.objects.filter(agent=request.user.agent)
        total_interests = UserInterest.objects.filter(plot__agent=request.user.agent).count()
    else:
        plots = Plot.objects.filter(landowner=request.user.landownerprofile)
        total_interests = UserInterest.objects.filter(
            plot__landowner=request.user.landownerprofile
        ).count()

    monthly_stats = (
        plots.annotate(month=TruncMonth("created_at"))
        .values("month")
        .annotate(count=Count("id"))
        .order_by("month")
    )

    price_ranges = {
        "Under 1M": plots.filter(price__lt=1000000).count(),
        "1M - 5M": plots.filter(price__gte=1000000, price__lt=5000000).count(),
        "5M - 10M": plots.filter(price__gte=5000000, price__lt=10000000).count(),
        "10M+": plots.filter(price__gte=10000000).count(),
    }

    listing_type_stats = {
        "For Sale": plots.filter(listing_type="sale").count(),
        "For Lease": plots.filter(listing_type="lease").count(),
        "Both": plots.filter(listing_type="both").count(),
    }

    land_type_stats = plots.values("land_type").annotate(count=Count("id")).order_by(
        "-count"
    )
    location_stats = plots.values("location").annotate(count=Count("id")).order_by(
        "-count"
    )[:10]

    context = {
        "monthly_stats": list(monthly_stats),
        "price_ranges": price_ranges,
        "listing_type_stats": listing_type_stats,
        "land_type_stats": list(land_type_stats),
        "location_stats": list(location_stats),
        "total_interests": total_interests,
        "total_plots": plots.count(),
        "avg_price": plots.aggregate(avg=Avg("price"))["avg"] or 0,
        "avg_area": 0,
    }

    try:
        area_values = [p.area_acres for p in plots if p.area_acres]
        if area_values:
            context["avg_area"] = sum(area_values) / len(area_values)
    except Exception:
        context["avg_area"] = 0

    return render(request, "accounts/dashboard/analytics.html", context)


@login_required
def dashboard_router(request):
    if not request.user.is_authenticated:
        return redirect("listings:home")

    if hasattr(request.user, "extension_officer") and not request.user.is_superuser:
        return redirect("verification:extension_dashboard")
    if hasattr(request.user, "land_surveyor") and not request.user.is_superuser:
        return redirect("verification:surveyor_dashboard")

    if (
        hasattr(request.user, "agent")
        or hasattr(request.user, "landownerprofile")
        or request.user.is_staff
        or request.user.is_superuser
    ):
        return redirect("listings:staff_dashboard")
    return redirect("listings:home")
