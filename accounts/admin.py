from django.conf import settings
from django.contrib import admin
from django.utils import timezone
from django.utils.html import format_html

from accounts.models import Agent, LandownerProfile, Profile
from notifications.notification_service import NotificationService

admin.site.site_header = "AgriPlot Administration"
admin.site.site_title = "AgriPlot Admin"
admin.site.index_title = "System Management"

@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "role", "phone")
    list_filter = ("role",)
    search_fields = ("user__username", "user__email", "phone")

    def has_add_permission(self, request):
        return False

@admin.register(LandownerProfile)
class LandownerProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "verified", "verified_at")
    list_filter = ("verified",)
    search_fields = ("user__username", "user__email")

    actions = ["verify_selected", "reject_selected"]

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
    list_display = ("user", "license_number", "verified")
    list_filter = ("verified",)
    search_fields = ("user__username", "user__email", "license_number")

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
