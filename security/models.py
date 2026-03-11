from django.conf import settings
from django.db import models
from django.utils import timezone


class TwoFactorSettings(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="two_factor_settings"
    )
    is_enabled = models.BooleanField(default=False)
    totp_secret = models.CharField(max_length=64, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "listings_twofactorsettings"

    def __str__(self):
        return f"2FA for {self.user.username} ({'enabled' if self.is_enabled else 'disabled'})"


class TwoFactorBackupCode(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="two_factor_backup_codes",
    )
    code_hash = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)
    used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "listings_twofactorbackupcode"
        ordering = ["-created_at"]

    def __str__(self):
        return f"Backup code for {self.user.username} ({'used' if self.used_at else 'unused'})"


class AuditLog(models.Model):
    ACTION_CHOICES = [
        ("create_plot", "Create Listing"),
        ("edit_plot", "Edit Listing"),
        ("delete_plot", "Delete Listing"),
        ("verify_landowner", "Verify Landowner"),
        ("reject_landowner", "Reject Landowner"),
        ("verify_agent", "Verify Agent"),
        ("verify_plot", "Verify Plot"),
        ("reject_plot", "Reject Plot"),
        ("change_price", "Change Price"),
        ("login", "Login"),
        ("failed_login", "Failed Login"),
    ]
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_logs",
    )
    action = models.CharField(max_length=50, choices=ACTION_CHOICES)
    object_type = models.CharField(max_length=50, blank=True)
    object_id = models.PositiveIntegerField(null=True, blank=True)
    extra = models.JSONField(default=dict, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "listings_auditlog"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["-created_at"]),
            models.Index(fields=["user", "action"]),
        ]

    def __str__(self):
        return f"{self.get_action_display()} by {self.user_id} at {self.created_at}"


class ImpersonationDetection(models.Model):
    ALERT_TYPES = [
        ("duplicate_id", "Same ID multiple accounts"),
        ("name_mismatch", "Name mismatch across documents"),
        ("rapid_listings", "Too many listings too quickly"),
        ("geographic_mismatch", "Listings far apart"),
        ("content_similarity", "Listing description copied"),
    ]
    SEVERITY_CHOICES = [
        ("low", "Low Risk"),
        ("medium", "Medium Risk"),
        ("high", "High Risk - Block"),
    ]
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="impersonation_alerts",
    )
    alert_type = models.CharField(max_length=50, choices=ALERT_TYPES)
    severity = models.CharField(max_length=20, choices=SEVERITY_CHOICES, default="low")
    description = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    resolved = models.BooleanField(default=False)

    class Meta:
        db_table = "listings_impersonationdetection"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["severity", "-created_at"])]

    def __str__(self):
        return f"{self.user_id} — {self.alert_type} ({self.severity})"


class PhoneEmailVerification(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="contact_verification",
    )
    phone_number = models.CharField(max_length=20, blank=True, default="")
    email = models.EmailField(blank=True, default="")
    phone_verified = models.BooleanField(default=False)
    email_verified = models.BooleanField(default=False)
    phone_verification_code = models.CharField(max_length=10, blank=True, default="")
    email_verification_code = models.CharField(max_length=10, blank=True, default="")
    phone_verified_at = models.DateTimeField(null=True, blank=True)
    email_verified_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "listings_phoneemailverification"

    def __str__(self):
        return f"{self.user_id} — phone:{self.phone_verified} email:{self.email_verified}"


class DocumentHash(models.Model):
    file_hash = models.CharField(max_length=64, unique=True)
    file_name = models.CharField(max_length=255, blank=True, default="")
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "listings_documenthash"
        ordering = ["-uploaded_at"]

    def __str__(self):
        return f"{self.file_name} — {self.file_hash[:10]}"


class PhoneOTP(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, null=True, blank=True
    )
    phone = models.CharField(max_length=20)
    otp = models.CharField(max_length=6)
    purpose = models.CharField(
        max_length=20,
        choices=[
            ("registration", "Registration"),
            ("login", "Login"),
            ("verification", "Verification"),
        ],
    )
    is_verified = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()

    class Meta:
        db_table = "listings_phoneotp"
        indexes = [
            models.Index(fields=["phone", "otp", "expires_at"]),
        ]

    def is_valid(self):
        return not self.is_verified and timezone.now() < self.expires_at


class EmailOTP(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, null=True, blank=True
    )
    email = models.EmailField()
    otp = models.CharField(max_length=6)
    purpose = models.CharField(
        max_length=20,
        choices=[
            ("registration", "Registration"),
            ("login", "Login"),
            ("verification", "Verification"),
        ],
    )
    is_verified = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()

    class Meta:
        db_table = "listings_emailotp"
        indexes = [
            models.Index(fields=["email", "otp", "expires_at"]),
        ]

    def is_valid(self):
        return not self.is_verified and timezone.now() < self.expires_at
