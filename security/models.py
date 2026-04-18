"""
Security Models for AgriPlot
Handles 2FA, Audit Logging, Verification, and Security Monitoring
"""

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.core.validators import MinLengthValidator, MaxLengthValidator
import hashlib
import json
from decimal import Decimal


# ============================================================
# Custom JSON Encoder for Decimal handling
# ============================================================

class DecimalEncoder(json.JSONEncoder):
    """Custom JSON encoder to handle Decimal objects"""
    def default(self, obj):
        if isinstance(obj, Decimal):
            return float(obj)
        if isinstance(obj, timezone.datetime):
            return obj.isoformat()
        return super().default(obj)


# ============================================================
# Two-Factor Authentication Models
# ============================================================

class TwoFactorSettings(models.Model):
    """Two-Factor Authentication settings for users"""
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, 
        on_delete=models.CASCADE, 
        related_name="two_factor_settings"
    )
    is_enabled = models.BooleanField(default=False)
    totp_secret = models.CharField(max_length=64, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "security_twofactorsettings"
        verbose_name = "2FA Setting"
        verbose_name_plural = "2FA Settings"

    def __str__(self):
        return f"2FA for {self.user.username} ({'enabled' if self.is_enabled else 'disabled'})"


class TwoFactorBackupCode(models.Model):
    """Backup codes for 2FA recovery"""
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="two_factor_backup_codes",
    )
    code_hash = models.CharField(max_length=64)  # Hashed backup code
    created_at = models.DateTimeField(auto_now_add=True)
    used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "security_twofactorbackupcode"
        ordering = ["-created_at"]
        verbose_name = "2FA Backup Code"
        verbose_name_plural = "2FA Backup Codes"

    def __str__(self):
        return f"Backup code for {self.user.username} ({'used' if self.used_at else 'unused'})"


# ============================================================
# Audit Log for Non-Repudiation
# ============================================================

class AuditLog(models.Model):
    """
    Immutable audit log with blockchain-style chaining for non-repudiation.
    Each log entry contains a cryptographic hash of its content and the previous log's hash.
    """
    
    # Action Types
    ACTION_CREATE_PLOT = "create_plot"
    ACTION_EDIT_PLOT = "edit_plot"
    ACTION_DELETE_PLOT = "delete_plot"
    ACTION_VERIFY_LANDOWNER = "verify_landowner"
    ACTION_REJECT_LANDOWNER = "reject_landowner"
    ACTION_VERIFY_AGENT = "verify_agent"
    ACTION_VERIFY_PLOT = "verify_plot"
    ACTION_REJECT_PLOT = "reject_plot"
    ACTION_CHANGE_PRICE = "change_price"
    ACTION_LOGIN = "login"
    ACTION_LOGOUT = "logout"
    ACTION_FAILED_LOGIN = "failed_login"
    ACTION_PAYMENT_INITIATED = "payment_initiated"
    ACTION_PAYMENT_COMPLETED = "payment_completed"
    ACTION_PAYMENT_REFUNDED = "payment_refunded"
    ACTION_DOCUMENT_UPLOAD = "document_upload"
    ACTION_DOCUMENT_VIEW = "document_view"
    ACTION_EXPORT_DATA = "export_data"
    ACTION_SETTINGS_CHANGE = "settings_change"
    ACTION_ROLE_ASSIGNED = "role_assigned"
    ACTION_APPROVAL_GRANTED = "approval_granted"
    ACTION_DISPUTE_RAISED = "dispute_raised"
    ACTION_DISPUTE_RESOLVED = "dispute_resolved"
    ACTION_TWO_FACTOR_ENABLE = "two_factor_enable"
    ACTION_TWO_FACTOR_DISABLE = "two_factor_disable"
    ACTION_VERIFICATION_CODE_SENT = "verification_code_sent"
    ACTION_VERIFICATION_CODE_VERIFIED = "verification_code_verified"
    
    ACTION_CHOICES = [
        (ACTION_CREATE_PLOT, "Create Listing"),
        (ACTION_EDIT_PLOT, "Edit Listing"),
        (ACTION_DELETE_PLOT, "Delete Listing"),
        (ACTION_VERIFY_LANDOWNER, "Verify Landowner"),
        (ACTION_REJECT_LANDOWNER, "Reject Landowner"),
        (ACTION_VERIFY_AGENT, "Verify Agent"),
        (ACTION_VERIFY_PLOT, "Verify Plot"),
        (ACTION_REJECT_PLOT, "Reject Plot"),
        (ACTION_CHANGE_PRICE, "Change Price"),
        (ACTION_LOGIN, "Login"),
        (ACTION_LOGOUT, "Logout"),
        (ACTION_FAILED_LOGIN, "Failed Login"),
        (ACTION_PAYMENT_INITIATED, "Payment Initiated"),
        (ACTION_PAYMENT_COMPLETED, "Payment Completed"),
        (ACTION_PAYMENT_REFUNDED, "Payment Refunded"),
        (ACTION_DOCUMENT_UPLOAD, "Document Uploaded"),
        (ACTION_DOCUMENT_VIEW, "Document Viewed"),
        (ACTION_EXPORT_DATA, "Data Exported"),
        (ACTION_SETTINGS_CHANGE, "Settings Changed"),
        (ACTION_ROLE_ASSIGNED, "Role Assigned"),
        (ACTION_APPROVAL_GRANTED, "Approval Granted"),
        (ACTION_DISPUTE_RAISED, "Dispute Raised"),
        (ACTION_DISPUTE_RESOLVED, "Dispute Resolved"),
        (ACTION_TWO_FACTOR_ENABLE, "2FA Enabled"),
        (ACTION_TWO_FACTOR_DISABLE, "2FA Disabled"),
        (ACTION_VERIFICATION_CODE_SENT, "Verification Code Sent"),
        (ACTION_VERIFICATION_CODE_VERIFIED, "Verification Code Verified"),
    ]
    
    # Severity Levels
    SEVERITY_INFO = "info"
    SEVERITY_WARNING = "warning"
    SEVERITY_CRITICAL = "critical"
    
    SEVERITY_CHOICES = [
        (SEVERITY_INFO, "Information"),
        (SEVERITY_WARNING, "Warning"),
        (SEVERITY_CRITICAL, "Critical"),
    ]
    
    # Core fields
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_logs",
        db_index=True,
    )
    action = models.CharField(max_length=50, choices=ACTION_CHOICES, db_index=True)
    severity = models.CharField(max_length=20, choices=SEVERITY_CHOICES, default=SEVERITY_INFO, db_index=True)
    
    # Object information
    object_type = models.CharField(max_length=50, blank=True, db_index=True)
    object_id = models.PositiveIntegerField(null=True, blank=True)
    object_repr = models.CharField(max_length=200, blank=True, default="")
    
    # Data before/after for tracking changes
    old_data = models.JSONField(default=dict, blank=True)
    new_data = models.JSONField(default=dict, blank=True)
    changes = models.JSONField(default=dict, blank=True)
    extra = models.JSONField(default=dict, blank=True)
    
    # Request context
    ip_address = models.GenericIPAddressField(null=True, blank=True, db_index=True)
    user_agent = models.CharField(max_length=500, blank=True)
    request_path = models.CharField(max_length=500, blank=True)
    request_method = models.CharField(max_length=10, blank=True)
    
    # Cryptographic fields for non-repudiation (blockchain-style chaining)
    hash_signature = models.CharField(max_length=128, unique=True, db_index=True, blank=True)
    previous_hash = models.CharField(max_length=128, blank=True, null=True)
    is_verified = models.BooleanField(default=True)
    
    # Timestamp
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "security_auditlog"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["-created_at"]),
            models.Index(fields=["user", "action"]),
            models.Index(fields=["hash_signature"]),
            models.Index(fields=["severity", "created_at"]),
            models.Index(fields=["object_type", "object_id"]),
            models.Index(fields=["created_at"]),
        ]
        verbose_name = "Audit Log"
        verbose_name_plural = "Audit Logs"

    def __str__(self):
        return f"[{self.created_at}] {self.get_action_display()} - {self.user}"

    def save(self, *args, **kwargs):
        """Override save to generate cryptographic hash for non-repudiation"""
        is_new = self.pk is None
        
        # Get the last log's hash for chaining (for new entries only)
        if is_new and not self.previous_hash:
            last_log = AuditLog.objects.order_by('-created_at').first()
            if last_log:
                self.previous_hash = last_log.hash_signature
            else:
                self.previous_hash = "0" * 64  # Genesis block for first log
        
        # Generate hash for this log entry
        hash_content = json.dumps({
            'id': self.pk,
            'user_id': self.user_id,
            'action': self.action,
            'severity': self.severity,
            'object_type': self.object_type,
            'object_id': self.object_id,
            'ip_address': self.ip_address,
            'created_at': self.created_at.isoformat() if self.created_at else timezone.now().isoformat(),
            'old_data': self.old_data,
            'new_data': self.new_data,
            'changes': self.changes,
            'previous_hash': self.previous_hash,
        }, sort_keys=True, cls=DecimalEncoder)
        
        self.hash_signature = hashlib.sha256(hash_content.encode()).hexdigest()
        
        super().save(*args, **kwargs)
    
    @classmethod
    def log_action(cls, request, action, object_type=None, object_id=None, 
                   object_repr=None, old_data=None, new_data=None, 
                   changes=None, extra=None, severity=SEVERITY_INFO):
        """
        Convenience method to create audit log entries
        """
        # Get client IP from request
        ip_address = None
        if request:
            x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
            if x_forwarded_for:
                ip_address = x_forwarded_for.split(',')[0]
            else:
                ip_address = request.META.get('REMOTE_ADDR')
        
        log = cls(
            user=request.user if request and request.user.is_authenticated else None,
            action=action,
            severity=severity,
            object_type=object_type,
            object_id=object_id,
            object_repr=object_repr,
            old_data=old_data or {},
            new_data=new_data or {},
            changes=changes or {},
            extra=extra or {},
            ip_address=ip_address,
            user_agent=request.META.get('HTTP_USER_AGENT', '')[:500] if request else '',
            request_path=request.path if request else '',
            request_method=request.method if request else '',
        )
        log.save()
        return log
    
    def verify_integrity(self):
        """Verify that this log entry hasn't been tampered with"""
        hash_content = json.dumps({
            'id': self.id,
            'user_id': self.user_id,
            'action': self.action,
            'severity': self.severity,
            'object_type': self.object_type,
            'object_id': self.object_id,
            'ip_address': self.ip_address,
            'created_at': self.created_at.isoformat(),
            'old_data': self.old_data,
            'new_data': self.new_data,
            'changes': self.changes,
            'previous_hash': self.previous_hash,
        }, sort_keys=True, cls=DecimalEncoder)
        
        expected_hash = hashlib.sha256(hash_content.encode()).hexdigest()
        return self.hash_signature == expected_hash
    
    @classmethod
    def verify_chain(cls):
        """Verify the entire audit log chain for tampering"""
        logs = cls.objects.all().order_by('created_at')
        previous_hash = "0" * 64
        
        for log in logs:
            # Check chain linkage
            if log.previous_hash != previous_hash:
                return False, f"Chain broken at log {log.id}"
            
            # Check integrity
            if not log.verify_integrity():
                return False, f"Integrity failed at log {log.id}"
            
            previous_hash = log.hash_signature
        
        return True, "Chain verified"


# ============================================================
# Impersonation Detection
# ============================================================

class ImpersonationDetection(models.Model):
    """Detect potential impersonation attempts"""
    
    ALERT_DUPLICATE_ID = "duplicate_id"
    ALERT_NAME_MISMATCH = "name_mismatch"
    ALERT_RAPID_LISTINGS = "rapid_listings"
    ALERT_GEOGRAPHIC_MISMATCH = "geographic_mismatch"
    ALERT_CONTENT_SIMILARITY = "content_similarity"
    ALERT_SUSPICIOUS_LOGIN = "suspicious_login"
    ALERT_MULTIPLE_ACCOUNTS = "multiple_accounts"
    
    ALERT_TYPES = [
        (ALERT_DUPLICATE_ID, "Same ID multiple accounts"),
        (ALERT_NAME_MISMATCH, "Name mismatch across documents"),
        (ALERT_RAPID_LISTINGS, "Too many listings too quickly"),
        (ALERT_GEOGRAPHIC_MISMATCH, "Listings far apart"),
        (ALERT_CONTENT_SIMILARITY, "Listing description copied"),
        (ALERT_SUSPICIOUS_LOGIN, "Suspicious login pattern"),
        (ALERT_MULTIPLE_ACCOUNTS, "Multiple accounts with same ID"),
    ]
    
    SEVERITY_LOW = "low"
    SEVERITY_MEDIUM = "medium"
    SEVERITY_HIGH = "high"
    
    SEVERITY_CHOICES = [
        (SEVERITY_LOW, "Low Risk"),
        (SEVERITY_MEDIUM, "Medium Risk"),
        (SEVERITY_HIGH, "High Risk - Block"),
    ]
    
    STATUS_PENDING = "pending"
    STATUS_INVESTIGATING = "investigating"
    STATUS_RESOLVED = "resolved"
    STATUS_FALSE_POSITIVE = "false_positive"
    
    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending Review"),
        (STATUS_INVESTIGATING, "Under Investigation"),
        (STATUS_RESOLVED, "Resolved"),
        (STATUS_FALSE_POSITIVE, "False Positive"),
    ]
    
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="impersonation_alerts",
    )
    alert_type = models.CharField(max_length=50, choices=ALERT_TYPES)
    severity = models.CharField(max_length=20, choices=SEVERITY_CHOICES, default=SEVERITY_LOW)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    description = models.TextField()
    evidence = models.JSONField(default=dict, blank=True)
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="resolved_alerts",
    )
    resolved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "security_impersonationdetection"
        ordering = ["-severity", "-created_at"]
        indexes = [
            models.Index(fields=["severity", "-created_at"]),
            models.Index(fields=["status", "severity"]),
        ]

    def __str__(self):
        return f"{self.user.username} — {self.get_alert_type_display()} ({self.get_severity_display()})"


# ============================================================
# Contact Verification
# ============================================================

class PhoneEmailVerification(models.Model):
    """Track phone and email verification status"""
    
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
        db_table = "security_phoneemailverification"
        verbose_name = "Contact Verification"
        verbose_name_plural = "Contact Verifications"

    def __str__(self):
        return f"{self.user.username} — phone:{self.phone_verified} email:{self.email_verified}"


# ============================================================
# Document Integrity
# ============================================================

class DocumentHash(models.Model):
    """Store cryptographic hashes of uploaded documents for integrity verification"""
    
    file_hash = models.CharField(max_length=64, unique=True, db_index=True)
    file_name = models.CharField(max_length=255, blank=True, default="")
    file_size = models.BigIntegerField(null=True, blank=True)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)
    verified_at = models.DateTimeField(null=True, blank=True)
    is_verified = models.BooleanField(default=False)

    class Meta:
        db_table = "security_documenthash"
        ordering = ["-uploaded_at"]
        indexes = [
            models.Index(fields=["file_hash"]),
            models.Index(fields=["-uploaded_at"]),
        ]

    def __str__(self):
        return f"{self.file_name} — {self.file_hash[:10]}..."


# ============================================================
# One-Time Password Models
# ============================================================

class PhoneOTP(models.Model):
    """Phone-based OTP for verification"""
    
    PURPOSE_REGISTRATION = "registration"
    PURPOSE_LOGIN = "login"
    PURPOSE_VERIFICATION = "verification"
    PURPOSE_PASSWORD_RESET = "password_reset"
    PURPOSE_TRANSACTION = "transaction"
    
    PURPOSE_CHOICES = [
        (PURPOSE_REGISTRATION, "Registration"),
        (PURPOSE_LOGIN, "Login"),
        (PURPOSE_VERIFICATION, "Verification"),
        (PURPOSE_PASSWORD_RESET, "Password Reset"),
        (PURPOSE_TRANSACTION, "Transaction"),
    ]
    
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        on_delete=models.CASCADE, 
        null=True, 
        blank=True,
        related_name="phone_otps",
    )
    phone = models.CharField(max_length=20, db_index=True)
    otp = models.CharField(max_length=6)
    purpose = models.CharField(max_length=20, choices=PURPOSE_CHOICES)
    is_verified = models.BooleanField(default=False)
    attempts = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()

    class Meta:
        db_table = "security_phoneotp"
        indexes = [
            models.Index(fields=["phone", "otp", "expires_at"]),
            models.Index(fields=["expires_at"]),
        ]

    def __str__(self):
        return f"OTP for {self.phone} - {self.purpose} ({'verified' if self.is_verified else 'pending'})"

    def is_valid(self):
        """Check if OTP is still valid"""
        return not self.is_verified and timezone.now() < self.expires_at
    
    def increment_attempts(self):
        """Increment attempt counter and return if max exceeded"""
        self.attempts += 1
        if self.attempts >= 5:  # Max 5 attempts
            self.is_verified = True  # Lock the OTP
        self.save(update_fields=['attempts', 'is_verified'])
        return self.attempts >= 5


class EmailOTP(models.Model):
    """Email-based OTP for verification"""
    
    PURPOSE_REGISTRATION = "registration"
    PURPOSE_LOGIN = "login"
    PURPOSE_VERIFICATION = "verification"
    PURPOSE_PASSWORD_RESET = "password_reset"
    PURPOSE_TRANSACTION = "transaction"
    
    PURPOSE_CHOICES = [
        (PURPOSE_REGISTRATION, "Registration"),
        (PURPOSE_LOGIN, "Login"),
        (PURPOSE_VERIFICATION, "Verification"),
        (PURPOSE_PASSWORD_RESET, "Password Reset"),
        (PURPOSE_TRANSACTION, "Transaction"),
    ]
    
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        on_delete=models.CASCADE, 
        null=True, 
        blank=True,
        related_name="email_otps",
    )
    email = models.EmailField(db_index=True)
    otp = models.CharField(max_length=6)
    purpose = models.CharField(max_length=20, choices=PURPOSE_CHOICES)
    is_verified = models.BooleanField(default=False)
    attempts = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()

    class Meta:
        db_table = "security_emailotp"
        indexes = [
            models.Index(fields=["email", "otp", "expires_at"]),
            models.Index(fields=["expires_at"]),
        ]

    def __str__(self):
        return f"OTP for {self.email} - {self.purpose} ({'verified' if self.is_verified else 'pending'})"

    def is_valid(self):
        """Check if OTP is still valid"""
        return not self.is_verified and timezone.now() < self.expires_at
    
    def increment_attempts(self):
        """Increment attempt counter and return if max exceeded"""
        self.attempts += 1
        if self.attempts >= 5:  # Max 5 attempts
            self.is_verified = True  # Lock the OTP
        self.save(update_fields=['attempts', 'is_verified'])
        return self.attempts >= 5