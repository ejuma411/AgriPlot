from django.conf import settings
from django.contrib import admin
from django.core.management import call_command
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html

from notifications.notification_service import NotificationService
from verification.models import (
    DocumentVerification,
    ExtensionOfficer,
    ExtensionReport,
    LandSurveyor,
    PlotVerification,
    SoilReport,
    SurveyorReport,
    VerificationLog,
    VerificationStatus,
    VerificationTask,
)


class ApprovalStatusFilter(admin.SimpleListFilter):
    title = "Approval Status"
    parameter_name = "approval_status"

    def lookups(self, request, model_admin):
        return [
            ("pending", "Pending approvals"),
            ("approved", "Approved"),
        ]

    def queryset(self, request, queryset):
        value = self.value()
        if value == "pending":
            return queryset.filter(verified=False)
        if value == "approved":
            return queryset.filter(verified=True)
        return queryset


@admin.register(VerificationStatus)
class VerificationStatusAdmin(admin.ModelAdmin):
    list_display = ("id", "content_object_display", "current_stage", "progress_bar", "created_at")
    list_filter = ("current_stage", "created_at", "is_complete")
    list_select_related = ("content_type",)
    search_fields = ("search_reference",)
    readonly_fields = (
        "created_at",
        "updated_at",
        "api_responses",
        "stage_details",
        "progress_percentage",
        "content_type",
        "object_id",
        "content_object_display",
        "progress_bar_display",
    )

    fieldsets = (
        ("Target", {"fields": ("content_type", "object_id", "content_object_display")}),
        ("Current Status", {"fields": ("current_stage", "is_complete", "progress_percentage", "progress_bar_display")}),
        ("API Data", {"fields": ("search_reference", "search_fee_paid", "api_responses"), "classes": ("collapse",)}),
        (
            "Timestamps",
            {
                "fields": (
                    "document_uploaded_at",
                    "api_started_at",
                    "title_search_at",
                    "owner_verified_at",
                    "admin_review_at",
                    "approved_at",
                    "rejected_at",
                ),
                "classes": ("collapse",),
            },
        ),
        ("Details", {"fields": ("stage_details",), "classes": ("collapse",)}),
    )

    def content_object_display(self, obj):
        model_class = obj.content_type.model_class() if obj.content_type_id else None
        if not model_class:
            return format_html(
                "<span class='text-muted'>Missing model: {}.{}</span>",
                obj.content_type.app_label if obj.content_type_id else "unknown",
                obj.content_type.model if obj.content_type_id else "unknown",
            )

        try:
            content_object = model_class._base_manager.filter(pk=obj.object_id).first()
        except Exception:
            content_object = None

        if not content_object:
            return format_html(
                "<span class='text-muted'>Missing object #{} ({})</span>",
                obj.object_id,
                obj.content_type,
            )

        if hasattr(content_object, "user"):
            user = content_object.user
            return format_html(
                "<strong>{}</strong><br><small>{} - {}</small>",
                user.get_full_name() or user.username,
                content_object.__class__.__name__,
                obj.content_type,
            )
        if hasattr(content_object, "title"):
            return format_html(
                "<strong>{}</strong><br><small>Plot #{} - {}</small>",
                content_object.title,
                content_object.id,
                content_object.location,
            )
        return str(content_object)

    content_object_display.short_description = "Content Object"

    def progress_bar(self, obj):
        progress = obj.progress_percentage
        if progress >= 100:
            color = "#28a745"
        elif progress >= 75:
            color = "#17a2b8"
        elif progress >= 50:
            color = "#ffc107"
        elif progress >= 25:
            color = "#fd7e14"
        else:
            color = "#dc3545"
        return format_html(
            '<div style="width: 100px; background-color: #e9ecef; border-radius: 10px; overflow: hidden;">'
            '<div style="width: {}%; background-color: {}; height: 20px; text-align: center; color: white; font-size: 11px; line-height: 20px;">{}%</div>'
            "</div>",
            progress,
            color,
            progress,
        )

    progress_bar.short_description = "Progress"
    progress_bar.admin_order_field = "progress_percentage"

    def progress_bar_display(self, obj):
        return self.progress_bar(obj)

    progress_bar_display.short_description = "Progress Bar"

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        return queryset.select_related("content_type")

    actions = ["mark_as_approved", "mark_as_rejected", "reset_to_pending"]

    def mark_as_approved(self, request, queryset):
        count = 0
        for obj in queryset:
            obj.update_stage(
                "approved",
                {"approved_by": request.user.username, "approved_at": timezone.now().isoformat()},
            )
            count += 1
        self.message_user(request, f"{count} verification(s) marked as approved. Progress: 100%")

    mark_as_approved.short_description = "Mark selected as approved (100 percent)"

    def mark_as_rejected(self, request, queryset):
        count = 0
        for obj in queryset:
            obj.update_stage(
                "rejected",
                {"rejected_by": request.user.username, "rejected_at": timezone.now().isoformat()},
            )
            count += 1
        self.message_user(request, f"{count} verification(s) marked as rejected.")

    mark_as_rejected.short_description = "Mark selected as rejected"

    def reset_to_pending(self, request, queryset):
        count = 0
        for obj in queryset:
            obj.update_stage("document_uploaded")
            count += 1
        self.message_user(request, f"{count} verification(s) reset to pending.")

    reset_to_pending.short_description = "Reset selected to pending (0 percent)"


@admin.register(VerificationTask)
class VerificationTaskAdmin(admin.ModelAdmin):
    list_display = ("plot", "verification_type", "assigned_to", "status", "approved", "assigned_at")
    list_filter = ("verification_type", "status")
    search_fields = ("plot__title", "assigned_to__username")


@admin.register(VerificationLog)
class VerificationLogAdmin(admin.ModelAdmin):
    list_display = ("plot", "verified_by", "verification_type", "created_at")
    list_filter = ("verification_type",)
    search_fields = ("plot__title",)


@admin.register(DocumentVerification)
class DocumentVerificationAdmin(admin.ModelAdmin):
    list_display = ("user", "plot", "task", "document_type", "approved", "name_matches_user", "verified_by", "verified_at")
    list_filter = ("document_type", "approved")
    search_fields = ("user__username", "plot__title")


@admin.register(ExtensionOfficer)
class ExtensionOfficerAdmin(admin.ModelAdmin):
    list_display = ("user_info", "designation", "station", "assigned_counties_display", "workload_display", "status_display", "verified")
    list_filter = (ApprovalStatusFilter, "is_active", "verified", "designation", "station", "department")
    search_fields = ("user__username", "user__email", "user__first_name", "user__last_name", "employee_id", "phone")
    readonly_fields = ("total_tasks_completed", "average_rating", "response_time_avg", "created_at", "updated_at")

    fieldsets = (
        ("User Account", {"fields": ("user", "employee_id")}),
        ("Professional Details", {"fields": ("designation", "department", "station", "qualifications", "specializations", "years_of_experience")}),
        ("Contact Information", {"fields": ("phone", "office_address")}),
        ("Assignment & Workload", {"fields": ("assigned_counties", "max_daily_tasks", "is_active")}),
        ("Verification Status", {"fields": ("verified", "verified_by", "verified_at")}),
        ("Performance Metrics", {"fields": ("total_tasks_completed", "average_rating", "response_time_avg"), "classes": ("collapse",)}),
        ("Metadata", {"fields": ("created_at", "updated_at"), "classes": ("collapse",)}),
    )

    def user_info(self, obj):
        return format_html(
            "<strong>{}</strong><br><small>{}</small>",
            obj.user.get_full_name() or obj.user.username,
            obj.user.email,
        )

    user_info.short_description = "Officer"

    def assigned_counties_display(self, obj):
        if not obj.assigned_counties:
            return "None"
        return ", ".join(obj.assigned_counties[:3]) + ("..." if len(obj.assigned_counties) > 3 else "")

    assigned_counties_display.short_description = "Counties"

    def workload_display(self, obj):
        current = obj.current_workload
        max_tasks = obj.max_daily_tasks
        percentage = (current / max_tasks * 100) if max_tasks > 0 else 0
        color = "green" if percentage < 50 else "orange" if percentage < 80 else "red"
        return format_html('<span style="color: {};">{}/{} tasks</span>', color, current, max_tasks)

    workload_display.short_description = "Workload"

    def status_display(self, obj):
        if not obj.is_active:
            return format_html('<span style="color: red;">Inactive</span>')
        if not obj.verified:
            return format_html('<span style="color: orange;">Unverified</span>')
        return format_html('<span style="color: green;">Active</span>')

    status_display.short_description = "Status"

    actions = ["verify_officers", "activate_officers", "deactivate_officers"]

    def verify_officers(self, request, queryset):
        count = 0
        for obj in queryset:
            obj.verified = True
            obj.verified_by = request.user
            obj.verified_at = timezone.now()
            obj.is_active = True
            obj.save()
            count += 1

            if obj.user.email:
                NotificationService.send_email(
                    recipient=obj.user.email,
                    subject="Role Approved: Extension Officer",
                    template="role_approved",
                    context={
                        "user": obj.user,
                        "role": "Extension Officer",
                        "login_url": settings.SITE_URL + "/login/",
                    },
                )
            NotificationService.create_notification(
                user=obj.user,
                notification_type="role_approved",
                title="Role Approved: Extension Officer",
                message="Your extension officer role has been approved.",
            )
        self.message_user(request, f"{count} officer(s) verified.")

    verify_officers.short_description = "Verify selected officers"

    def activate_officers(self, request, queryset):
        queryset.update(is_active=True)
        self.message_user(request, f"{queryset.count()} officer(s) activated.")

    activate_officers.short_description = "Activate selected officers"

    def deactivate_officers(self, request, queryset):
        queryset.update(is_active=False)
        self.message_user(request, f"{queryset.count()} officer(s) deactivated.")

    deactivate_officers.short_description = "Deactivate selected officers"


@admin.register(ExtensionReport)
class ExtensionReportAdmin(admin.ModelAdmin):
    list_display = ("id", "plot_link", "officer", "visit_date", "overall_suitability", "recommendation", "submitted_at")
    list_filter = ("overall_suitability", "recommendation", "visit_date", "submitted_at")
    search_fields = ("plot__title", "officer__user__username", "comments")
    readonly_fields = ("submitted_at",)

    def plot_link(self, obj):
        url = reverse("admin:listings_plot_change", args=[obj.plot.id])
        return format_html('<a href="{}">{}</a>', url, obj.plot.title)

    plot_link.short_description = "Plot"


@admin.register(LandSurveyor)
class LandSurveyorAdmin(admin.ModelAdmin):
    list_display = ("user_info", "designation", "station", "assigned_counties_display", "workload_display", "status_display", "verified")
    list_filter = (ApprovalStatusFilter, "is_active", "verified", "station")
    search_fields = ("user__username", "user__email", "user__first_name", "user__last_name", "license_number", "phone")
    readonly_fields = ("total_tasks_completed", "average_rating", "response_time_avg", "created_at", "updated_at")

    fieldsets = (
        ("User Account", {"fields": ("user", "license_number")}),
        ("Professional Details", {"fields": ("designation", "station", "qualifications", "years_of_experience")}),
        ("Contact Information", {"fields": ("phone", "office_address")}),
        ("Assignment & Workload", {"fields": ("assigned_counties", "max_daily_tasks", "is_active")}),
        ("Verification Status", {"fields": ("verified", "verified_by", "verified_at")}),
        ("Performance Metrics", {"fields": ("total_tasks_completed", "average_rating", "response_time_avg"), "classes": ("collapse",)}),
        ("Metadata", {"fields": ("created_at", "updated_at"), "classes": ("collapse",)}),
    )

    def user_info(self, obj):
        return format_html(
            "<strong>{}</strong><br><small>{}</small>",
            obj.user.get_full_name() or obj.user.username,
            obj.user.email,
        )

    user_info.short_description = "Surveyor"

    def assigned_counties_display(self, obj):
        if not obj.assigned_counties:
            return "None"
        return ", ".join(obj.assigned_counties[:3]) + ("..." if len(obj.assigned_counties) > 3 else "")

    assigned_counties_display.short_description = "Counties"

    def workload_display(self, obj):
        current = obj.current_workload
        max_tasks = obj.max_daily_tasks
        percentage = (current / max_tasks * 100) if max_tasks > 0 else 0
        color = "green" if percentage < 50 else "orange" if percentage < 80 else "red"
        return format_html('<span style="color: {};">{}/{} tasks</span>', color, current, max_tasks)

    workload_display.short_description = "Workload"

    def status_display(self, obj):
        if not obj.is_active:
            return format_html('<span style="color: red;">Inactive</span>')
        if not obj.verified:
            return format_html('<span style="color: orange;">Unverified</span>')
        return format_html('<span style="color: green;">Active</span>')

    status_display.short_description = "Status"

    actions = ["verify_surveyors", "activate_surveyors", "deactivate_surveyors"]

    def verify_surveyors(self, request, queryset):
        count = 0
        for obj in queryset:
            obj.verified = True
            obj.verified_by = request.user
            obj.verified_at = timezone.now()
            obj.is_active = True
            obj.save()
            count += 1

            if obj.user.email:
                NotificationService.send_email(
                    recipient=obj.user.email,
                    subject="Role Approved: Land Surveyor",
                    template="role_approved",
                    context={
                        "user": obj.user,
                        "role": "Land Surveyor",
                        "login_url": settings.SITE_URL + "/login/",
                    },
                )
            NotificationService.create_notification(
                user=obj.user,
                notification_type="role_approved",
                title="Role Approved: Land Surveyor",
                message="Your land surveyor role has been approved.",
            )
        self.message_user(request, f"{count} surveyor(s) verified.")

    verify_surveyors.short_description = "Verify selected surveyors"

    def activate_surveyors(self, request, queryset):
        queryset.update(is_active=True)
        self.message_user(request, f"{queryset.count()} surveyor(s) activated.")

    activate_surveyors.short_description = "Activate selected surveyors"

    def deactivate_surveyors(self, request, queryset):
        queryset.update(is_active=False)
        self.message_user(request, f"{queryset.count()} surveyor(s) deactivated.")

    deactivate_surveyors.short_description = "Deactivate selected surveyors"


@admin.register(SurveyorReport)
class SurveyorReportAdmin(admin.ModelAdmin):
    list_display = ("id", "plot_link", "surveyor", "visit_date", "recommendation", "submitted_at")
    list_filter = ("recommendation", "visit_date", "submitted_at")
    search_fields = ("plot__title", "surveyor__user__username", "notes")
    readonly_fields = ("submitted_at",)

    def plot_link(self, obj):
        url = reverse("admin:listings_plot_change", args=[obj.plot.id])
        return format_html('<a href="{}">{}</a>', url, obj.plot.title)

    plot_link.short_description = "Plot"


@admin.register(PlotVerification)
class PlotVerificationAdmin(admin.ModelAdmin):
    list_display = ("plot", "current_stage", "submitted_at")
    list_filter = ("current_stage",)
    search_fields = ("plot__title",)


@admin.register(SoilReport)
class SoilReportAdmin(admin.ModelAdmin):
    list_display = ("plot", "verification_status", "created_at")
    list_filter = ("verification_status", "created_at")
    search_fields = ("plot__title", "lab_id")
