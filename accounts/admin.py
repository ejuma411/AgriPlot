from django.conf import settings
from django.contrib import admin
from django.utils import timezone
from django.utils.html import format_html

from accounts.models import Agent, LandownerProfile, Profile
from notifications.notification_service import NotificationService


admin.site.site_header = "AgriPlot Administration"
admin.site.site_title = "AgriPlot Admin"
admin.site.index_title = "System Management"


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


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "role", "phone")
    list_filter = ("role",)
    search_fields = ("user__username", "user__email", "phone")

    def has_add_permission(self, request):
        return False


@admin.register(LandownerProfile)
class LandownerProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "submitted_on", "has_id", "has_kra", "status")
    list_filter = (ApprovalStatusFilter, "verified")
    search_fields = ("user__username", "user__email")

    fieldsets = (
        (
            "User Information",
            {"fields": ("user", "verified", "verified_at", "reviewed_by", "rejection_reason")},
        ),
        ("Documents", {"fields": ("national_id", "kra_pin", "title_deed", "land_search", "lcb_consent")}),
    )

    def submitted_on(self, obj):
        return obj.user.date_joined.strftime("%Y-%m-%d")

    submitted_on.short_description = "Submitted"

    def has_id(self, obj):
        return bool(obj.national_id)

    has_id.boolean = True
    has_id.short_description = "ID"

    def has_kra(self, obj):
        return bool(obj.kra_pin)

    has_kra.boolean = True
    has_kra.short_description = "KRA"

    def status(self, obj):
        if obj.verified:
            return format_html(
                '<span style="color: green; font-weight: bold;">✓ Verified</span>'
            )
        return format_html(
            '<span style="color: orange; font-weight: bold;">⏳ Pending</span>'
        )

    status.short_description = "Status"

    actions = ["verify_selected"]

    def verify_selected(self, request, queryset):
        for obj in queryset:
            obj.verified = True
            obj.verified_at = timezone.now()
            obj.reviewed_by = request.user
            obj.rejection_reason = ""
            obj.save()

            NotificationService.notify_role_decision(
                user=obj.user,
                role="Landowner",
                approved=True,
                decided_by=request.user,
            )
        self.message_user(request, f"{queryset.count()} landowner(s) verified.")

    verify_selected.short_description = "Verify selected landowners"

    def reject_selected(self, request, queryset):
        for obj in queryset:
            obj.verified = False
            obj.verified_at = None
            obj.reviewed_by = request.user
            obj.rejection_reason = "Your landowner role request was not approved. Please review your documents and try again."
            obj.save()

            NotificationService.notify_role_decision(
                user=obj.user,
                role="Landowner",
                approved=False,
                decided_by=request.user,
                reason=obj.rejection_reason,
            )
        self.message_user(request, f"{queryset.count()} landowner(s) rejected.")

    reject_selected.short_description = "Reject selected landowners"


@admin.register(Agent)
class AgentAdmin(admin.ModelAdmin):
    list_display = ("user", "submitted_on", "license_number", "has_license", "status")
    list_filter = (ApprovalStatusFilter, "verified")
    search_fields = ("user__username", "user__email", "license_number")

    fieldsets = (
        ("Basic Information", {"fields": ("user", "phone", "id_number", "verified")}),
        ("Professional Details", {"fields": ("license_number", "license_doc", "kra_pin")}),
    )

    def submitted_on(self, obj):
        return obj.user.date_joined.strftime("%Y-%m-%d")

    submitted_on.short_description = "Submitted"

    def has_license(self, obj):
        return bool(obj.license_doc)

    has_license.boolean = True
    has_license.short_description = "License"

    def status(self, obj):
        if obj.verified:
            return format_html(
                '<span style="color: green; font-weight: bold;">✓ Verified</span>'
            )
        return format_html(
            '<span style="color: orange; font-weight: bold;">⏳ Pending</span>'
        )

    status.short_description = "Status"

    actions = ["verify_selected", "reject_selected"]

    def verify_selected(self, request, queryset):
        count = 0
        for obj in queryset:
            obj.verified = True
            obj.save()
            count += 1

            NotificationService.notify_role_decision(
                user=obj.user,
                role="Agent",
                approved=True,
                decided_by=request.user,
            )
        self.message_user(request, f"{count} agent(s) verified.")

    verify_selected.short_description = "Verify selected agents"

    def reject_selected(self, request, queryset):
        count = 0
        for obj in queryset:
            obj.verified = False
            obj.save()
            count += 1

            NotificationService.notify_role_decision(
                user=obj.user,
                role="Agent",
                approved=False,
                decided_by=request.user,
                reason="Your agent role request was not approved. Please review your documents and resubmit.",
            )
        self.message_user(request, f"{count} agent(s) rejected.")

    reject_selected.short_description = "Reject selected agents"
