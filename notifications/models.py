from django.conf import settings
from django.db import models
from django.utils import timezone


class Notification(models.Model):
    NOTIFICATION_TYPES = [
        ("task_assigned", "Task Assigned"),
        ("task_completed", "Task Completed"),
        ("task_reminder", "Task Reminder"),
        ("task_unconfirmed", "Task Unconfirmed"),
        ("plot_submitted", "Plot Submitted"),
        ("plot_approved", "Plot Approved"),
        ("plot_rejected", "Plot Rejected"),
        ("plot_stage_update", "Plot Stage Update"),
        ("changes_requested", "Changes Requested"),
        ("document_uploaded", "Document Uploaded"),
        ("verification_started", "Verification Started"),
        ("verification_completed", "Verification Completed"),
        ("verification_step_update", "Verification Step Update"),
        ("no_officer_available", "No Officer Available"),
        ("role_request", "Role Request"),
        ("role_approved", "Role Approved"),
        ("account_verified", "Account Verified"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notifications",
    )
    notification_type = models.CharField(max_length=50, choices=NOTIFICATION_TYPES)
    title = models.CharField(max_length=200)
    message = models.TextField()
    plot = models.ForeignKey(
        "listings.Plot",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="notifications",
    )
    task = models.ForeignKey(
        "verification.VerificationTask",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="notifications",
    )

    is_read = models.BooleanField(default=False)
    is_email_sent = models.BooleanField(default=False)
    email_sent_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "listings_notification"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "-created_at"]),
            models.Index(fields=["user", "is_read"]),
        ]

    def __str__(self):
        return f"{self.user.username} - {self.notification_type} - {self.created_at}"

    def mark_as_read(self):
        self.is_read = True
        self.read_at = timezone.now()
        self.save()


class SupportTicket(models.Model):
    STATUS_CHOICES = [
        ("open", "Open"),
        ("in_progress", "In Progress"),
        ("resolved", "Resolved"),
        ("closed", "Closed"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True
    )
    name = models.CharField(max_length=120)
    email = models.EmailField()
    subject = models.CharField(max_length=200)
    message = models.TextField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="open")
    created_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "listings_supportticket"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.subject} ({self.status})"


class SMSLog(models.Model):
    PROVIDER_CHOICES = [
        ("textsms", "TextSMS"),
        ("opensms", "OpenSMS"),
    ]
    provider = models.CharField(max_length=20, choices=PROVIDER_CHOICES, default="textsms")
    phone = models.CharField(max_length=30)
    message = models.TextField()
    status_code = models.IntegerField(null=True, blank=True)
    success = models.BooleanField(default=False)
    message_id = models.CharField(max_length=100, blank=True)
    response_body = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "listings_smslog"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.phone} — {self.provider} — {self.status_code}"


class EmailLog(models.Model):
    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("sent", "Sent"),
        ("failed", "Failed"),
    ]

    recipient = models.EmailField()
    subject = models.CharField(max_length=500)
    template = models.CharField(max_length=100)
    context = models.JSONField(default=dict)

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")
    error_message = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "listings_emaillog"
        ordering = ["-created_at"]
