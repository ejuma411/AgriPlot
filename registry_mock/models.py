from django.db import models
from django.contrib.auth import get_user_model


class MockLandRegistry(models.Model):
    """Mocked Ministry of Lands registry record used for testing."""

    TITLE_TYPE_CHOICES = [
        ("FREEHOLD", "Freehold"),
        ("LEASEHOLD", "Leasehold"),
    ]

    parcel_number = models.CharField(max_length=100, unique=True, db_index=True)
    registered_owner_name = models.CharField(max_length=255)
    owner_id_number = models.CharField(max_length=20)
    owner_kra_pin = models.CharField(max_length=20, blank=True)
    county = models.CharField(max_length=100, blank=True)
    subcounty = models.CharField(max_length=100, blank=True)
    registration_section = models.CharField(max_length=150, blank=True)
    search_reference_number = models.CharField(max_length=100, blank=True)
    search_certificate_date = models.DateField(null=True, blank=True)

    acreage_ha = models.DecimalField(max_digits=10, decimal_places=4)
    land_type = models.CharField(max_length=20, choices=TITLE_TYPE_CHOICES)

    is_charged = models.BooleanField(default=False)
    has_caution = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["parcel_number"]),
            models.Index(fields=["registered_owner_name"]),
        ]

    def __str__(self):
        return self.parcel_number


class RegistryMismatchAttempt(models.Model):
    """Track failed registry verification attempts for audit and abuse prevention."""

    parcel_number = models.CharField(max_length=100, db_index=True)
    provided_owner_name = models.CharField(max_length=255, blank=True)
    provided_owner_id = models.CharField(max_length=50, blank=True)
    user = models.ForeignKey(
        get_user_model(),
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )
    reason = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["parcel_number", "created_at"]),
        ]

    def __str__(self):
        return f"Mismatch {self.parcel_number} ({self.created_at:%Y-%m-%d})"
