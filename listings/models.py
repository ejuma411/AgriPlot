from django.conf import settings
from django.contrib.contenttypes.fields import GenericRelation
from django.core.exceptions import ValidationError
from django.db import models


class Plot(models.Model):
    MARKET_STATUS_CHOICES = [
        ("available", "Available"),
        ("reserved", "Reserved"),
        ("leased", "Leased"),
        ("sold", "Sold"),
    ]

    LISTING_TYPE_CHOICES = [
        ("sale", "For Sale"),
        ("lease", "For Lease"),
        ("both", "For Sale & Lease"),
    ]

    LEASE_DURATION_CHOICES = [
        ("monthly", "Month-to-Month"),
        ("seasonal", "Seasonal (3-6 months)"),
        ("1year", "1 Year"),
        ("3years", "3 Years"),
        ("5years", "5 Years"),
        ("10years", "10 Years"),
    ]

    LAND_TYPE_CHOICES = [
        ("agricultural", "Agricultural Land"),
        ("residential", "Residential Plot"),
        ("commercial", "Commercial Land"),
        ("mixed_use", "Mixed Use"),
        ("industrial", "Industrial Land"),
    ]

    WATER_SOURCE_CHOICES = [
        ("borehole", "Borehole"),
        ("river", "River/Stream"),
        ("rain", "Rain-fed"),
        ("irrigation", "Irrigation System"),
        ("none", "No Water Source"),
    ]

    ROAD_TYPE_CHOICES = [
        ("tarmac", "Tarmac"),
        ("murram", "Murram/Gravel"),
        ("earth", "Earth Road"),
        ("footpath", "Footpath Only"),
        ("none", "No Access"),
    ]

    FENCING_CHOICES = [
        ("full", "Full Perimeter"),
        ("partial", "Partial"),
        ("none", "No Fencing"),
        ("live", "Live Fence"),
    ]

    county = models.CharField(max_length=100, blank=True, null=True)
    subcounty = models.CharField(max_length=100, blank=True, null=True)
    nearest_town = models.CharField(max_length=150, blank=True)
    ownership_type = models.CharField(
        max_length=20,
        choices=[
            ("freehold", "Freehold"),
            ("leasehold", "Leasehold"),
            ("government", "Government"),
            ("community", "Community"),
        ],
        default="freehold",
    )
    tenure_details = models.CharField(
        max_length=200, blank=True, help_text="Lease duration/expiry or tenure notes"
    )
    encumbrances = models.BooleanField(default=False)
    encumbrance_details = models.TextField(blank=True)

    landowner = models.ForeignKey(
        "accounts.LandownerProfile", on_delete=models.CASCADE, null=True, blank=True
    )
    agent = models.ForeignKey(
        "accounts.Agent", on_delete=models.CASCADE, null=True, blank=True
    )

    title = models.CharField(max_length=200)
    location = models.CharField(max_length=300)

    AREA_UNIT_CHOICES = [
        ("acres", "Acres"),
        ("hectares", "Hectares"),
    ]
    area = models.FloatField(help_text="Land area value")
    area_unit = models.CharField(
        max_length=10,
        choices=AREA_UNIT_CHOICES,
        default="acres",
        help_text="Unit for the land area",
    )
    parcel_number = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        unique=True,
        db_index=True,
        help_text="Parcel/Title/LR number (e.g., REGISTRY/BLOCK/PARCEL or LR 1234/567)",
    )
    is_subdivision = models.BooleanField(
        default=False, help_text="True when listing is for a portion of a larger parcel"
    )
    original_parcel_number = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        help_text="Original parcel number when listing a subdivision",
    )
    registration_section = models.CharField(
        max_length=150,
        blank=True,
        null=True,
        help_text="Registration section / registry block (e.g., Nairobi/Block 10)",
    )
    search_certificate_date = models.DateField(
        null=True, blank=True, help_text="Official search certificate date"
    )
    search_reference_number = models.CharField(
        max_length=100, blank=True, help_text="Official search reference number"
    )
    owner_full_name = models.CharField(
        max_length=200, blank=True, help_text="Name of registered owner as per title/search"
    )
    owner_id_number = models.CharField(
        max_length=50, blank=True, help_text="National ID number of the registered owner"
    )
    owner_kra_pin_number = models.CharField(
        max_length=20, blank=True, help_text="KRA PIN number of the registered owner"
    )
    registry_owner_name = models.CharField(
        max_length=255, blank=True, help_text="Owner name fetched from registry"
    )
    registry_owner_id_number = models.CharField(
        max_length=50, blank=True, help_text="Owner ID fetched from registry"
    )
    registry_owner_kra_pin = models.CharField(
        max_length=50, blank=True, help_text="Owner KRA PIN fetched from registry"
    )
    registry_area_ha = models.DecimalField(
        max_digits=12,
        decimal_places=4,
        null=True,
        blank=True,
        help_text="Area (hectares) fetched from registry",
    )
    registry_land_type = models.CharField(
        max_length=20, blank=True, help_text="Title type fetched from registry (FREEHOLD/LEASEHOLD)"
    )
    registry_has_encumbrances = models.BooleanField(
        default=False, help_text="Encumbrance status fetched from registry"
    )
    spousal_consent = models.BooleanField(
        default=False, help_text="Spousal consent provided (if matrimonial property)"
    )

    listing_type = models.CharField(
        max_length=10, choices=LISTING_TYPE_CHOICES, default="sale"
    )
    market_status = models.CharField(
        max_length=20, choices=MARKET_STATUS_CHOICES, default="available"
    )
    lease_start_date = models.DateField(null=True, blank=True)
    lease_end_date = models.DateField(null=True, blank=True)
    availability_notes = models.TextField(blank=True)
    land_type = models.CharField(
        max_length=20, choices=LAND_TYPE_CHOICES, default="agricultural"
    )
    land_use_description = models.TextField(blank=True)

    sale_price = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True
    )
    price_per_acre = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True
    )
    PRICE_BASIS_CHOICES = [
        ("owner_set", "Owner-set price"),
        ("agent_market", "Agent market analysis"),
        ("valuation_report", "Professional valuation report"),
        ("government_set", "Government-set price"),
        ("negotiated", "Negotiated (market demand)"),
    ]
    price_basis = models.CharField(
        max_length=30, choices=PRICE_BASIS_CHOICES, default="owner_set"
    )
    valuation_report = models.FileField(
        upload_to="documents/valuation_reports/",
        null=True,
        blank=True,
        help_text="Optional valuation report (PDF/Image)",
    )
    price_notes = models.TextField(blank=True)
    is_price_negotiable = models.BooleanField(default=True)

    lease_price_monthly = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True
    )
    lease_price_yearly = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True
    )
    lease_duration = models.CharField(
        max_length=20, choices=LEASE_DURATION_CHOICES, null=True, blank=True
    )
    lease_terms = models.TextField(blank=True)
    lease_basis = models.CharField(
        max_length=30, choices=PRICE_BASIS_CHOICES, default="owner_set"
    )
    government_price_proof = models.FileField(
        upload_to="documents/government_price_proofs/",
        null=True,
        blank=True,
        help_text="Official notice/gazette for government-set price",
    )

    price = models.DecimalField(max_digits=12, decimal_places=2)

    soil_type = models.CharField(max_length=100, blank=True, default="")
    ph_level = models.FloatField(null=True, blank=True)
    crop_suitability = models.CharField(max_length=200, blank=True, default="")

    has_water = models.BooleanField(default=False)
    water_source = models.CharField(
        max_length=20, choices=WATER_SOURCE_CHOICES, null=True, blank=True
    )
    has_electricity = models.BooleanField(default=False)
    electricity_meter = models.BooleanField(default=False, help_text="Has meter installed")

    has_road_access = models.BooleanField(default=False)
    road_type = models.CharField(
        max_length=20, choices=ROAD_TYPE_CHOICES, null=True, blank=True
    )
    road_distance_km = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True
    )

    has_buildings = models.BooleanField(default=False)
    building_description = models.TextField(blank=True)
    other_amenities = models.TextField(blank=True)

    fencing = models.CharField(
        max_length=50, choices=FENCING_CHOICES, null=True, blank=True
    )

    verification = GenericRelation(
        "verification.VerificationStatus",
        content_type_field="content_type",
        object_id_field="object_id",
        related_query_name="plot",
    )

    title_deed = models.FileField(
        upload_to="documents/title_deeds/",
        null=True,
        blank=True,
        help_text="Official title deed document",
    )
    survey_map = models.FileField(
        upload_to="documents/survey_maps/",
        null=True,
        blank=True,
        help_text="Survey map or mutation form",
    )
    spousal_consent_doc = models.FileField(
        upload_to="documents/spousal_consents/",
        null=True,
        blank=True,
        help_text="Spousal consent document (if applicable)",
    )
    soil_report = models.FileField(
        upload_to="documents/soil_reports/",
        null=True,
        blank=True,
        help_text="Soil test report (optional)",
    )

    official_search = models.FileField(
        upload_to="documents/official_searches/",
        null=True,
        blank=True,
        help_text="Official land search certificate",
    )
    rates_clearance = models.FileField(
        upload_to="documents/rates_clearance/",
        null=True,
        blank=True,
        help_text="Land rates clearance certificate",
    )
    rent_clearance = models.FileField(
        upload_to="documents/rent_clearance/",
        null=True,
        blank=True,
        help_text="Land rent clearance certificate",
    )
    lcb_consent_doc = models.FileField(
        upload_to="documents/lcb_consents/",
        null=True,
        blank=True,
        help_text="Land Control Board consent (agricultural land)",
    )
    plupa1_form = models.FileField(
        upload_to="documents/plupa1_forms/",
        null=True,
        blank=True,
        help_text="PLUPA 1 / PPA 1 approval form (subdivision or change of use)",
    )
    consent_to_transfer = models.FileField(
        upload_to="documents/consent_to_transfer/",
        null=True,
        blank=True,
        help_text="Consent to transfer for leasehold land",
    )

    landowner_id_doc = models.FileField(
        upload_to="documents/landowner_ids/",
        null=True,
        blank=True,
        help_text="Landowner's national ID",
    )
    kra_pin = models.FileField(
        upload_to="documents/kra_pins/",
        null=True,
        blank=True,
        help_text="KRA PIN certificate",
    )

    latitude = models.DecimalField(
        max_digits=9,
        decimal_places=6,
        null=True,
        blank=True,
        help_text="Latitude (e.g. -1.292066 for Nairobi)",
    )
    longitude = models.DecimalField(
        max_digits=9,
        decimal_places=6,
        null=True,
        blank=True,
        help_text="Longitude (e.g. 36.821946 for Nairobi)",
    )

    elevation_meters = models.IntegerField(null=True, blank=True)
    climate_zone = models.CharField(max_length=100, blank=True)
    is_protected_area = models.BooleanField(default=False)
    special_features = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_published = models.BooleanField(default=False)
    is_registry_record = models.BooleanField(default=False)

    class Meta:
        indexes = [
            models.Index(fields=["-created_at"]),
            models.Index(fields=["listing_type"]),
            models.Index(fields=["land_type"]),
            models.Index(fields=["soil_type"]),
            models.Index(fields=["latitude", "longitude"]),
        ]

    def __str__(self):
        return self.title

    def primary_image_url(self):
        first_image = self.images.first()
        if first_image and first_image.image:
            return first_image.image.url
        return ""

    @property
    def area_acres(self):
        if self.area is None:
            return None
        if self.area_unit == "hectares":
            return self.area * 2.47105
        return self.area

    @property
    def area_display(self):
        if self.area is None:
            return "Not provided"
        unit = self.get_area_unit_display() if self.area_unit else "Acres"
        return f"{self.area} {unit}"

    def clean(self):
        if not self.landowner and not self.agent:
            raise ValidationError("Either landowner or agent must be associated with this plot")

        if self.listing_type in ["sale", "both"] and not self.sale_price:
            raise ValidationError("Sale price is required for listings marked 'For Sale'")

        if self.listing_type in ["lease", "both"] and not (
            self.lease_price_monthly or self.lease_price_yearly
        ):
            raise ValidationError("Lease price is required for listings marked 'For Lease'")

        if self.encumbrances and not self.encumbrance_details:
            raise ValidationError(
                "Provide encumbrance details when encumbrances are marked as present."
            )

        if self.market_status == "leased":
            if not self.lease_start_date or not self.lease_end_date:
                raise ValidationError(
                    "Lease start and end dates are required when the plot is marked as leased."
                )
            if self.lease_end_date <= self.lease_start_date:
                raise ValidationError("Lease end date must be after the lease start date.")

        if self.market_status == "sold":
            if self.lease_start_date or self.lease_end_date:
                raise ValidationError("Sold plots cannot keep lease date windows.")

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    @property
    def has_coordinates(self):
        return self.latitude is not None and self.longitude is not None

    @property
    def has_all_documents(self):
        required_docs = [
            "title_deed",
            "official_search",
            "landowner_id_doc",
            "kra_pin",
            "rates_clearance",
        ]
        if self.spousal_consent:
            required_docs.append("spousal_consent_doc")
        if self.land_type == "agricultural":
            required_docs.append("lcb_consent_doc")
        if self.is_subdivision:
            required_docs.extend(["survey_map", "plupa1_form"])
        if self.ownership_type == "leasehold":
            required_docs.extend(["rent_clearance", "consent_to_transfer"])
        return all(bool(getattr(self, doc, None)) for doc in required_docs)

    @property
    def has_active_lease(self):
        return (
            self.market_status == "leased"
            and self.lease_start_date is not None
            and self.lease_end_date is not None
        )

    @property
    def availability_summary(self):
        if self.market_status == "sold":
            return "This land has already been sold."
        if self.has_active_lease:
            return (
                f"This land is already leased from "
                f"{self.lease_start_date:%b %d, %Y} to {self.lease_end_date:%b %d, %Y}."
            )
        if self.market_status == "reserved":
            return "This land is currently reserved."
        return "This land is currently available."


class PlotImage(models.Model):
    plot = models.ForeignKey(Plot, on_delete=models.CASCADE, related_name="images")
    image = models.ImageField(upload_to="plot_images/")
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-uploaded_at"]

    def __str__(self):
        return f"PlotImage {self.id} for Plot {self.plot_id}"


class UserInterest(models.Model):
    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("contacted", "Contacted"),
        ("scheduled", "Viewing Scheduled"),
        ("rejected", "Not Interested"),
        ("accepted", "Accepted Offer"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="plot_interests"
    )
    plot = models.ForeignKey(Plot, on_delete=models.CASCADE, related_name="buyer_interests")
    message = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        unique_together = ["user", "plot"]

    def __str__(self):
        return f"{self.user.username} → {self.plot.title}"


class ContactRequest(models.Model):
    REQUEST_TYPES = [
        ("email", "Email Inquiry"),
        ("phone_request", "Phone Number Request"),
        ("phone_view", "Phone Number Viewed"),
        ("visit_request", "Site Visit Request"),
        ("message", "Direct Message"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="contact_requests"
    )
    plot = models.ForeignKey(Plot, on_delete=models.CASCADE, related_name="contact_requests")
    agent = models.ForeignKey(
        "accounts.Agent",
        on_delete=models.CASCADE,
        related_name="contact_requests",
        null=True,
        blank=True,
    )
    request_type = models.CharField(max_length=20, choices=REQUEST_TYPES)
    message = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    responded = models.BooleanField(default=False)
    responded_at = models.DateTimeField(null=True, blank=True)
    admin_notes = models.TextField(blank=True, null=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["-created_at"]),
            models.Index(fields=["responded"]),
        ]

    def __str__(self):
        if self.agent:
            recipient = self.agent.user.username
        elif self.plot.landowner:
            recipient = self.plot.landowner.user.username
        else:
            recipient = "plot-owner"
        return f"{self.user.username} → {recipient} ({self.request_type})"


class SitePage(models.Model):
    SLUG_CHOICES = [
        ("about", "About Us"),
        ("terms", "Terms of Service"),
        ("privacy", "Privacy Policy"),
    ]

    slug = models.CharField(max_length=50, choices=SLUG_CHOICES, unique=True)
    title = models.CharField(max_length=200)
    body = models.TextField(blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["slug"]

    def __str__(self):
        return self.get_slug_display()


class PriceComparable(models.Model):
    location = models.CharField(max_length=300)
    area_acres = models.DecimalField(max_digits=10, decimal_places=2)
    sale_price = models.DecimalField(max_digits=12, decimal_places=2)
    price_per_acre = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True
    )
    soil_type = models.CharField(max_length=100, blank=True)
    crop_type = models.CharField(max_length=200, blank=True)
    sale_date = models.DateField(null=True, blank=True)
    data_source = models.CharField(max_length=100, blank=True)
    verified = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-sale_date", "-created_at"]

    def save(self, *args, **kwargs):
        if self.area_acres and self.area_acres > 0 and not self.price_per_acre:
            self.price_per_acre = self.sale_price / self.area_acres
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.location} — {self.area_acres} ac @ {self.sale_price}"


class PricingSuggestion(models.Model):
    plot = models.ForeignKey(Plot, on_delete=models.CASCADE, related_name="pricing_suggestions")
    suggested_price = models.DecimalField(max_digits=12, decimal_places=2)
    price_range_min = models.DecimalField(max_digits=12, decimal_places=2)
    price_range_max = models.DecimalField(max_digits=12, decimal_places=2)
    methodology = models.CharField(max_length=200, blank=True)
    comparable_plots_used = models.IntegerField(default=0)
    explanation = models.TextField(blank=True)
    generated_at = models.DateTimeField(auto_now_add=True)
    landowner_accepted = models.BooleanField(null=True, blank=True)
    final_price = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)

    class Meta:
        ordering = ["-generated_at"]

    def __str__(self):
        return f"Suggestion for Plot {self.plot_id}: {self.suggested_price}"


class MarketPriceBand(models.Model):
    county = models.CharField(max_length=100)
    land_type = models.CharField(max_length=20, choices=Plot.LAND_TYPE_CHOICES)
    listing_type = models.CharField(max_length=10, choices=Plot.LISTING_TYPE_CHOICES)
    min_price_per_acre = models.DecimalField(max_digits=12, decimal_places=2)
    max_price_per_acre = models.DecimalField(max_digits=12, decimal_places=2)
    effective_from = models.DateField()
    effective_to = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["county", "land_type", "listing_type"]),
        ]

    def __str__(self):
        return f"{self.county} {self.land_type} {self.listing_type} band"


class ComparableSale(models.Model):
    plot = models.ForeignKey(Plot, on_delete=models.CASCADE, related_name="comparables")
    title = models.CharField(max_length=200, blank=True)
    county = models.CharField(max_length=100, blank=True)
    price_per_acre = models.DecimalField(max_digits=12, decimal_places=2)
    source = models.CharField(max_length=200, blank=True)
    notes = models.TextField(blank=True)

    def __str__(self):
        return f"Comparable {self.price_per_acre} for {self.plot_id}"


# Backward-compatible exports for code that still imports from `listings.models`.
from accounts.models import Agent, Broker, LandownerProfile, Profile  # noqa: E402
from notifications.models import EmailLog, Notification, SMSLog, SupportTicket  # noqa: E402
from security.models import (  # noqa: E402
    AuditLog,
    DocumentHash,
    EmailOTP,
    ImpersonationDetection,
    PhoneEmailVerification,
    PhoneOTP,
    TwoFactorBackupCode,
    TwoFactorSettings,
)
from verification.models import (  # noqa: E402
    DocumentVerification,
    ExtensionOfficer,
    ExtensionReport,
    LandSurveyor,
    PlotVerification,
    SoilReport,
    SurveyorReport,
    TitleSearchResult,
    VerificationDocument,
    VerificationLog,
    VerificationStatus,
    VerificationTask,
)

__all__ = [
    "Plot",
    "PlotImage",
    "UserInterest",
    "ContactRequest",
    "SitePage",
    "PriceComparable",
    "PricingSuggestion",
    "MarketPriceBand",
    "ComparableSale",
    "Profile",
    "Agent",
    "Broker",
    "LandownerProfile",
    "TwoFactorSettings",
    "TwoFactorBackupCode",
    "AuditLog",
    "ImpersonationDetection",
    "PhoneEmailVerification",
    "DocumentHash",
    "PhoneOTP",
    "EmailOTP",
    "Notification",
    "SupportTicket",
    "SMSLog",
    "EmailLog",
    "VerificationDocument",
    "TitleSearchResult",
    "VerificationStatus",
    "PlotVerification",
    "SoilReport",
    "VerificationTask",
    "VerificationLog",
    "DocumentVerification",
    "ExtensionOfficer",
    "ExtensionReport",
    "LandSurveyor",
    "SurveyorReport",
]
