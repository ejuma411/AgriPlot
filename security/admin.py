from django.contrib import admin

from security.models import (
    AuditLog,
    DocumentHash,
    EmailOTP,
    ImpersonationDetection,
    PhoneEmailVerification,
    PhoneOTP,
    TwoFactorBackupCode,
    TwoFactorSettings,
)


@admin.register(TwoFactorSettings)
class TwoFactorSettingsAdmin(admin.ModelAdmin):
    list_display = ("user", "is_enabled", "created_at", "updated_at")
    list_filter = ("is_enabled",)
    search_fields = ("user__username", "user__email")


@admin.register(TwoFactorBackupCode)
class TwoFactorBackupCodeAdmin(admin.ModelAdmin):
    list_display = ("user", "created_at", "used_at")
    list_filter = ("used_at", "created_at")
    search_fields = ("user__username", "user__email")


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "action", "object_type", "object_id", "ip_address", "created_at")
    list_filter = ("action", "created_at")
    search_fields = ("user__username", "action", "object_type")
    readonly_fields = (
        "user",
        "action",
        "object_type",
        "object_id",
        "extra",
        "ip_address",
        "user_agent",
        "created_at",
    )
    date_hierarchy = "created_at"


@admin.register(ImpersonationDetection)
class ImpersonationDetectionAdmin(admin.ModelAdmin):
    list_display = ("user", "alert_type", "severity", "resolved", "created_at")
    list_filter = ("severity", "resolved", "alert_type")
    search_fields = ("user__username", "description")


@admin.register(PhoneEmailVerification)
class PhoneEmailVerificationAdmin(admin.ModelAdmin):
    list_display = ("user", "phone_verified", "email_verified", "phone_number", "email", "updated_at")
    list_filter = ("phone_verified", "email_verified")
    search_fields = ("user__username", "phone_number", "email")


@admin.register(DocumentHash)
class DocumentHashAdmin(admin.ModelAdmin):
    list_display = ("file_name", "file_hash", "uploaded_by", "uploaded_at")
    search_fields = ("file_name", "file_hash")


@admin.register(PhoneOTP)
class PhoneOTPAdmin(admin.ModelAdmin):
    list_display = ("phone", "otp", "purpose", "is_verified", "expires_at", "created_at")
    list_filter = ("purpose", "is_verified")
    search_fields = ("phone",)


@admin.register(EmailOTP)
class EmailOTPAdmin(admin.ModelAdmin):
    list_display = ("email", "otp", "purpose", "is_verified", "expires_at", "created_at")
    list_filter = ("purpose", "is_verified")
    search_fields = ("email",)
