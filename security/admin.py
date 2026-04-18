from django.contrib import admin
from .models import (
    TwoFactorSettings,
    TwoFactorBackupCode,
    AuditLog,
    ImpersonationDetection,
    PhoneEmailVerification,
    DocumentHash,
    PhoneOTP,
    EmailOTP,
)


@admin.register(TwoFactorSettings)
class TwoFactorSettingsAdmin(admin.ModelAdmin):
    list_display = ['user', 'is_enabled', 'created_at', 'updated_at']
    list_filter = ['is_enabled', 'created_at']
    search_fields = ['user__username', 'user__email']
    readonly_fields = ['created_at', 'updated_at']


@admin.register(TwoFactorBackupCode)
class TwoFactorBackupCodeAdmin(admin.ModelAdmin):
    list_display = ['user', 'created_at', 'used_at']
    list_filter = ['used_at', 'created_at']
    search_fields = ['user__username', 'user__email']
    readonly_fields = ['created_at', 'used_at']


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = [
        'created_at', 'user', 'action', 'severity', 
        'object_type', 'object_id', 'ip_address'
    ]
    list_filter = ['action', 'severity', 'created_at']
    search_fields = [
        'user__username', 'user__email', 'object_type', 
        'object_id', 'ip_address', 'hash_signature'
    ]
    readonly_fields = [
        'user', 'action', 'severity', 'object_type', 'object_id', 
        'object_repr', 'old_data', 'new_data', 'changes', 'extra',
        'ip_address', 'user_agent', 'request_path', 'request_method',
        'hash_signature', 'previous_hash', 'created_at'
    ]
    date_hierarchy = 'created_at'
    
    def has_add_permission(self, request):
        """Prevent manual creation of audit logs"""
        return False
    
    def has_change_permission(self, request, obj=None):
        """Prevent modification of audit logs"""
        return False
    
    def has_delete_permission(self, request, obj=None):
        """Prevent deletion of audit logs"""
        return False


@admin.register(ImpersonationDetection)
class ImpersonationDetectionAdmin(admin.ModelAdmin):
    list_display = [
        'user', 'alert_type', 'severity', 'status', 'created_at'
    ]
    list_filter = ['alert_type', 'severity', 'status', 'created_at']
    search_fields = ['user__username', 'user__email', 'description']
    readonly_fields = ['created_at', 'updated_at']
    list_editable = ['status']
    actions = ['mark_resolved', 'mark_investigating', 'mark_false_positive']
    
    def mark_resolved(self, request, queryset):
        queryset.update(status='resolved')
    mark_resolved.short_description = "Mark selected alerts as Resolved"
    
    def mark_investigating(self, request, queryset):
        queryset.update(status='investigating')
    mark_investigating.short_description = "Mark selected alerts as Under Investigation"
    
    def mark_false_positive(self, request, queryset):
        queryset.update(status='false_positive')
    mark_false_positive.short_description = "Mark selected alerts as False Positive"


@admin.register(PhoneEmailVerification)
class PhoneEmailVerificationAdmin(admin.ModelAdmin):
    list_display = [
        'user', 'phone_verified', 'email_verified', 
        'phone_verified_at', 'email_verified_at'
    ]
    list_filter = ['phone_verified', 'email_verified']
    search_fields = ['user__username', 'user__email', 'phone_number', 'email']
    readonly_fields = ['created_at', 'updated_at']


@admin.register(DocumentHash)
class DocumentHashAdmin(admin.ModelAdmin):
    list_display = ['file_name', 'file_hash', 'uploaded_by', 'uploaded_at', 'is_verified']
    list_filter = ['is_verified', 'uploaded_at']
    search_fields = ['file_name', 'file_hash', 'uploaded_by__username']
    readonly_fields = ['file_hash', 'uploaded_at', 'verified_at']


@admin.register(PhoneOTP)
class PhoneOTPAdmin(admin.ModelAdmin):
    list_display = ['phone', 'purpose', 'is_verified', 'attempts', 'created_at', 'expires_at']
    list_filter = ['purpose', 'is_verified', 'created_at']
    search_fields = ['phone', 'otp']
    readonly_fields = ['created_at', 'expires_at']


@admin.register(EmailOTP)
class EmailOTPAdmin(admin.ModelAdmin):
    list_display = ['email', 'purpose', 'is_verified', 'attempts', 'created_at', 'expires_at']
    list_filter = ['purpose', 'is_verified', 'created_at']
    search_fields = ['email', 'otp']
    readonly_fields = ['created_at', 'expires_at']
