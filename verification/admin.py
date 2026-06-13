from django.contrib import admin
from django.utils import timezone
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

@admin.register(VerificationStatus)
class VerificationStatusAdmin(admin.ModelAdmin):
    list_display = ("id", "content_type", "object_id", "current_stage", "created_at")
    list_filter = ("current_stage", "created_at", "is_complete")

@admin.register(VerificationTask)
class VerificationTaskAdmin(admin.ModelAdmin):
    list_display = ("plot", "verification_type", "assigned_to", "status", "assigned_at")
    list_filter = ("verification_type", "status")
    search_fields = ("plot__title", "assigned_to__username")

@admin.register(VerificationLog)
class VerificationLogAdmin(admin.ModelAdmin):
    list_display = ("plot", "verified_by", "verification_type", "created_at")
    list_filter = ("verification_type",)

@admin.register(DocumentVerification)
class DocumentVerificationAdmin(admin.ModelAdmin):
    list_display = ("user", "plot", "document_type", "approved", "verified_at")
    list_filter = ("document_type", "approved")

@admin.register(ExtensionOfficer)
class ExtensionOfficerAdmin(admin.ModelAdmin):
    list_display = ("user", "designation", "station", "verified", "is_active")
    list_filter = ("is_active", "verified", "designation")
    search_fields = ("user__username", "user__email")

@admin.register(ExtensionReport)
class ExtensionReportAdmin(admin.ModelAdmin):
    list_display = ("plot", "officer", "visit_date", "overall_suitability")
    list_filter = ("overall_suitability", "recommendation")
    search_fields = ("plot__title", "officer__user__username")

@admin.register(LandSurveyor)
class LandSurveyorAdmin(admin.ModelAdmin):
    list_display = ("user", "designation", "station", "verified", "is_active")
    list_filter = ("is_active", "verified")
    search_fields = ("user__username", "user__email")

@admin.register(SurveyorReport)
class SurveyorReportAdmin(admin.ModelAdmin):
    list_display = ("plot", "surveyor", "visit_date", "recommendation")
    list_filter = ("recommendation",)
    search_fields = ("plot__title", "surveyor__user__username")

@admin.register(PlotVerification)
class PlotVerificationAdmin(admin.ModelAdmin):
    list_display = ("plot", "current_stage", "submitted_at")
    list_filter = ("current_stage",)

@admin.register(SoilReport)
class SoilReportAdmin(admin.ModelAdmin):
    list_display = ("plot", "verification_status", "created_at")
    list_filter = ("verification_status",)
