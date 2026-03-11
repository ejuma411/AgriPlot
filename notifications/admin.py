from django.contrib import admin

from notifications.models import EmailLog, Notification, SMSLog, SupportTicket


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ("user", "notification_type", "title", "is_read", "created_at")
    list_filter = ("notification_type", "is_read")
    search_fields = ("user__username", "title", "message")


@admin.register(EmailLog)
class EmailLogAdmin(admin.ModelAdmin):
    list_display = ("recipient", "subject", "status", "sent_at")
    list_filter = ("status",)
    search_fields = ("recipient", "subject")


@admin.register(SupportTicket)
class SupportTicketAdmin(admin.ModelAdmin):
    list_display = ("subject", "name", "email", "status", "created_at")
    list_filter = ("status",)
    search_fields = ("subject", "name", "email")


@admin.register(SMSLog)
class SMSLogAdmin(admin.ModelAdmin):
    list_display = ("phone", "provider", "status_code", "success", "created_at")
    list_filter = ("provider", "success")
    search_fields = ("phone", "message_id")

