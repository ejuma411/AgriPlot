from decimal import Decimal

from django.conf import settings
from django.contrib.contenttypes.fields import GenericRelation
from django.contrib.gis.db.models.functions import Distance as DistanceFunction
from django.contrib.gis.geos import Point
from django.core.exceptions import ValidationError
from django.db import ProgrammingError
from django.db import models
from django.contrib.gis.db import models as gis_models
from django.urls import reverse
from django.utils.text import slugify
from django.utils import timezone


class Plot(models.Model):
    LEASE_PAYMENT_FREQUENCY_CHOICES = [
        ("monthly", "Per Month"),
        ("seasonal", "Per Season"),
        ("yearly", "Per Year"),
    ]

    OWNER_APPROVAL_STATUS_CHOICES = [
        ("not_required", "Not Required"),
        ("pending", "Pending Landowner Approval"),
        ("approved", "Approved by Landowner"),
        ("rejected", "Rejected by Landowner"),
    ]

    AGENT_COMMISSION_TYPE_CHOICES = [
        ("percentage", "Percentage"),
        ("fixed", "Fixed Amount (KES)"),
    ]

    # ==========================================
    # TIMESTAMP FIELDS
    # ==========================================
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # ==========================================
    # CHOICES CONSTANTS
    # ==========================================
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

    MARKET_ZONE_CHOICES = [
        ("rural", "Rural"),
        ("peri_urban", "Peri-Urban"),
        ("urban", "Urban"),
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

    TOPOGRAPHY_CHOICES = [
        ("flat", "Flat"),
        ("gentle_slope", "Gentle Slope"),
        ("sloped", "Sloped"),
        ("hilly", "Hilly"),
        ("valley", "Valley Bottom"),
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

    AREA_UNIT_CHOICES = [
        ("acres", "Acres"),
        ("hectares", "Hectares"),
    ]

    OWNERSHIP_TYPE_CHOICES = [
        ("freehold", "Freehold"),
        ("leasehold", "Leasehold"),
        ("government", "Government"),
        ("community", "Community"),
    ]

    PRICE_BASIS_CHOICES = [
        ("owner_set", "Owner-set price"),
        ("agent_market", "Agent market analysis"),
        ("valuation_report", "Professional valuation report"),
        ("government_set", "Government-set price"),
        ("negotiated", "Negotiated (market demand)"),
    ]

    # ==========================================
    # LOCATION & GEOGRAPHY FIELDS
    # ==========================================
    county = models.CharField(max_length=100, blank=True, null=True)
    subcounty = models.CharField(max_length=100, blank=True, null=True)
    ward = models.CharField(max_length=100, blank=True, default="")
    nearest_town = models.CharField(max_length=150, blank=True)
    location = models.CharField(max_length=300)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    geom = gis_models.PointField(null=True, blank=True, srid=4326)

    # ==========================================
    # LAND INFORMATION FIELDS
    # ==========================================
    title = models.CharField(max_length=200)
    area = models.FloatField(help_text="Land area value")
    area_unit = models.CharField(
        max_length=10,
        choices=AREA_UNIT_CHOICES,
        default="acres",
        help_text="Unit for the land area",
    )
    land_type = models.CharField(
        max_length=20, choices=LAND_TYPE_CHOICES, default="agricultural"
    )
    land_use_description = models.TextField(blank=True)
    soil_type = models.CharField(max_length=100, blank=True, default="")
    topography = models.CharField(
        max_length=20,
        choices=TOPOGRAPHY_CHOICES,
        blank=True,
        default="",
    )
    ph_level = models.FloatField(null=True, blank=True)
    crop_suitability = models.CharField(max_length=200, blank=True, default="")
    climate_zone = models.CharField(max_length=100, blank=True, default="")
    elevation_meters = models.IntegerField(null=True, blank=True)
    is_protected_area = models.BooleanField(default=False)
    is_published = models.BooleanField(default=True)

    # ==========================================
    # OWNERSHIP & LEGAL FIELDS
    # ==========================================
    ownership_type = models.CharField(
        max_length=20,
        choices=OWNERSHIP_TYPE_CHOICES,
        default="freehold",
    )
    tenure_details = models.CharField(
        max_length=200, blank=True, help_text="Lease duration/expiry or tenure notes"
    )
    lease_term_remaining_years = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Years remaining on the leasehold title.",
    )
    encumbrances = models.BooleanField(default=False)
    encumbrance_details = models.TextField(blank=True)
    spousal_consent = models.BooleanField(
        default=False, help_text="Spousal consent provided (if matrimonial property)"
    )
    special_features = models.TextField(
        blank=True, 
        help_text="Special features of the land (e.g., water source, road access, fencing)"
    )

    
    # Registry/Land Title Information
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
    
    # Owner Information from Registry
    owner_full_name = models.CharField(
        max_length=200, blank=True, help_text="Name of registered owner as per title/search"
    )
    owner_id_number = models.CharField(
        max_length=50, blank=True, help_text="National ID number of the registered owner"
    )
    owner_kra_pin_number = models.CharField(
        max_length=20, blank=True, help_text="KRA PIN number of the registered owner"
    )
    
    # Registry Fetched Data
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
    # ==========================================
    # REGISTRY FIELD
    # ==========================================
    is_registry_record = models.BooleanField(
        default=False,
        db_index=True,
        help_text="Indicates if this plot has been verified against the land registry"
    )

    # ==========================================
    # ASSOCIATED PARTIES FIELDS
    # ==========================================
    landowner = models.ForeignKey(
        "accounts.LandownerProfile", on_delete=models.CASCADE, null=True, blank=True
    )
    agent = models.ForeignKey(
        "accounts.Agent", on_delete=models.CASCADE, null=True, blank=True
    )

    # ==========================================
    # LISTING & MARKETING FIELDS
    # ==========================================
    listing_type = models.CharField(
        max_length=10, choices=LISTING_TYPE_CHOICES, default="sale"
    )
    market_zone = models.CharField(
        max_length=20, choices=MARKET_ZONE_CHOICES, default="rural"
    )
    market_status = models.CharField(
        max_length=20, choices=MARKET_STATUS_CHOICES, default="available"
    )
    is_hidden = models.BooleanField(
        default=False,
        db_index=True,
        help_text="Hide this listing from public search results until it is reviewed.",
    )
    availability_notes = models.TextField(blank=True)
    
    # Lease specific fields
    lease_start_date = models.DateField(null=True, blank=True)
    lease_end_date = models.DateField(null=True, blank=True)
    lease_duration = models.CharField(
        max_length=20, choices=LEASE_DURATION_CHOICES, null=True, blank=True
    )
    lease_payment_frequency = models.CharField(
        max_length=20,
        choices=LEASE_PAYMENT_FREQUENCY_CHOICES,
        blank=True,
        default="",
    )
    lease_terms = models.TextField(blank=True)
    lease_basis = models.CharField(
        max_length=30, choices=PRICE_BASIS_CHOICES, default="owner_set"
    )
    owner_approval_status = models.CharField(
        max_length=20,
        choices=OWNER_APPROVAL_STATUS_CHOICES,
        default="not_required",
    )
    owner_approval_requested_at = models.DateTimeField(null=True, blank=True)
    owner_approval_at = models.DateTimeField(null=True, blank=True)
    owner_approval_notes = models.TextField(blank=True)
    landowner_phone_for_approval = models.CharField(max_length=20, blank=True)
    agency_agreement = models.FileField(
        upload_to="documents/agency_agreements/",
        null=True,
        blank=True,
        help_text="Signed authority letter or agency agreement from the owner.",
    )
    agent_commission_type = models.CharField(
        max_length=20,
        choices=AGENT_COMMISSION_TYPE_CHOICES,
        blank=True,
        default="",
    )
    agent_commission_value = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
    )

    # ==========================================
    # PRICING FIELDS
    # ==========================================
    price = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    sale_price = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True
    )
    price_per_acre = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True
    )
    price_basis = models.CharField(
        max_length=30, choices=PRICE_BASIS_CHOICES, default="owner_set"
    )
    price_notes = models.TextField(blank=True)
    is_price_negotiable = models.BooleanField(default=True)
    price_review_required = models.BooleanField(default=False)
    pricing_override_reason = models.TextField(blank=True)
    
    # Lease pricing
    lease_price_monthly = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True
    )
    lease_price_yearly = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True
    )

    # ==========================================
    # DOCUMENT UPLOADS FIELDS
    # ==========================================
    # Ownership documents
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
    
    # Verification documents
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
    rates_paid_up = models.BooleanField(default=False)
    rent_clearance = models.FileField(
        upload_to="documents/rent_clearance/",
        null=True,
        blank=True,
        help_text="Land rent clearance certificate",
    )
    rent_paid_up = models.BooleanField(default=False)
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
    valuation_report = models.FileField(
        upload_to="documents/valuation_reports/",
        null=True,
        blank=True,
        help_text="Optional valuation report (PDF/Image)",
    )
    government_price_proof = models.FileField(
        upload_to="documents/government_price_proofs/",
        null=True,
        blank=True,
        help_text="Official notice/gazette for government-set price",
    )
    
    # Owner identification documents
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
    soil_report = models.FileField(
        upload_to="documents/soil_reports/",
        null=True,
        blank=True,
        help_text="Soil test report (optional)",
    )

    # ==========================================
    # INFRASTRUCTURE FIELDS
    # ==========================================
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

    # ==========================================
    # VERIFICATION & RELATIONSHIPS
    # ==========================================
    verification = GenericRelation(
        "verification.VerificationStatus",
        content_type_field="content_type",
        object_id_field="object_id",
        related_query_name="plot",
    )

    # ==========================================
    # META CLASS
    # ==========================================
    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['-created_at']),
            models.Index(fields=['market_status', 'listing_type']),
            models.Index(fields=['county', 'subcounty']),
        ]

    # ==========================================
    # PROPERTIES
    # ==========================================
    
    @property
    def has_all_documents(self):
        """Check if all required documents are uploaded based on plot characteristics"""
        required_docs = [
            "title_deed",
            "official_search",
            "landowner_id_doc",
            "kra_pin",
            "rates_clearance",
        ]
        if self.spousal_consent:
            required_docs.append("spousal_consent_doc")
        if self.is_subdivision:
            required_docs.extend(["survey_map", "plupa1_form"])
        if self.ownership_type == "leasehold":
            required_docs.extend(["rent_clearance", "consent_to_transfer"])
        return all(bool(getattr(self, doc, None)) for doc in required_docs)
    
    @property
    def latest_surveyor_report(self):
        if not self.pk:
            return None
        return self.surveyor_reports.order_by("-submitted_at").first()

    @property
    def effective_usable_area_acres(self):
        report = self.latest_surveyor_report
        if report and report.acreage_confirmed:
            if report.ground_acreage and report.ground_acreage > 0:
                return report.ground_acreage
            if report.deed_area and report.deed_area > 0:
                return report.deed_area
        return self.area_acres

    @property
    def effective_usable_area_display(self):
        usable_area = self.effective_usable_area_acres
        if usable_area is None:
            return "Not verified yet"
        source = (
            "surveyor verified"
            if self.latest_surveyor_report and self.latest_surveyor_report.acreage_confirmed
            else "listing area"
        )
        return f"{usable_area:.2f} Acres ({source})"

    @property
    def area_display(self):
        if self.area is None:
            return "Not provided"
        unit = self.get_area_unit_display() if self.area_unit else "Acres"
        return f"{self.area} {unit}"
    
    @property
    def area_acres(self):
        """Convert area to acres based on unit"""
        if self.area is None:
            return None
        if self.area_unit == "hectares":
            return self.area * 2.47105
        return self.area

    @property
    def has_coordinates(self):
        return self.latitude is not None and self.longitude is not None

    @property
    def public_county_slug(self):
        return slugify(self.county or "kenya")

    @property
    def public_title_slug(self):
        return slugify(self.title or f"plot-{self.pk or 'draft'}")

    @property
    def has_active_lease(self):
        return (
            self.market_status == "leased"
            and self.lease_start_date is not None
            and self.lease_end_date is not None
            and self.lease_start_date <= timezone.localdate() <= self.lease_end_date
        )

    @property
    def requires_landowner_approval(self):
        return bool(self.agent_id and self.landowner_phone_for_approval)

    @property
    def is_pending_landowner_approval(self):
        return self.owner_approval_status == "pending"

    @property
    def is_hybrid_sale_lease(self):
        return self.listing_type == "both"

    @property
    def is_matrimonial_property(self):
        return self.spousal_consent

    @property
    def purchase_checkout_open(self):
        if self.market_status == "sold":
            return False
        if self.market_status == "reserved":
            return False
        if self.market_status == "leased" and not self.is_hybrid_sale_lease:
            return False
        return self.listing_type in {"sale", "both"}

    @property
    def lease_checkout_open(self):
        return self.market_status == "available" and self.listing_type in {"lease", "both"}

    @property
    def next_lease_booking_open(self):
        return (
            self.listing_type in {"lease", "both"}
            and self.market_status in {"reserved", "leased"}
            and self.lease_end_date is not None
        )

    @property
    def occupancy_status_label(self):
        if (
            self.market_status == "reserved"
            and self.listing_type in {"lease", "both"}
            and self.lease_end_date
        ):
            return "Lease Reserved"
        if self.has_active_lease and self.is_hybrid_sale_lease:
            return "Leased - Still for Sale"
        if self.has_active_lease:
            return "Currently Occupied"
        return self.market_status_label

    @property
    def market_status_label(self):
        return self.get_market_status_display()

    @property
    def market_status_css(self):
        return {
            "sold": "is-sold",
            "leased": "is-leased",
            "reserved": "is-reserved",
            "available": "is-available",
        }.get(self.market_status, "is-available")

    @property
    def is_checkout_open(self):
        return self.market_status == "available"

    @property
    def checkout_availability_message(self):
        if self.market_status == "sold":
            return "Checkout is closed because this land has already been sold."
        if (
            self.market_status == "reserved"
            and self.listing_type in {"lease", "both"}
            and self.lease_end_date
        ):
            return (
                "Checkout is closed because this land is already committed to an incoming lease, "
                f"with the current lease window expected to run until {self.lease_end_date:%b %d, %Y}. "
                "Another tenant may still reserve the next lease window."
            )
        if self.has_active_lease:
            if self.is_hybrid_sale_lease:
                return (
                    "Lease checkout is closed because this land is occupied, but purchase checkout stays open "
                    f"while the active tenancy runs until {self.lease_end_date:%b %d, %Y}. Another tenant may still reserve the next lease window."
                )
            return (
                "Checkout is closed because this land is already leased from "
                f"{self.lease_start_date:%b %d, %Y} to {self.lease_end_date:%b %d, %Y}. Another tenant may still reserve the next lease window."
            )
        if self.market_status == "reserved":
            return "Checkout is closed because this land is currently reserved."
        return "Checkout is open for this land."

    @property
    def availability_summary(self):
        if self.market_status == "sold":
            return "This land has already been sold."
        if (
            self.market_status == "reserved"
            and self.listing_type in {"lease", "both"}
            and self.lease_end_date
        ):
            return (
                f"This lease slot has already been committed through {self.lease_end_date:%b %d, %Y}. "
                "You can still reserve the next lease window if you are willing to wait."
            )
        if self.has_active_lease:
            if self.is_hybrid_sale_lease:
                return (
                    f"This land is leased until {self.lease_end_date:%b %d, %Y} and is still open for investors "
                    "who want to buy with the active tenant in place. Future tenants can still reserve the next lease window."
                )
            return (
                f"This land is already leased from "
                f"{self.lease_start_date:%b %d, %Y} to {self.lease_end_date:%b %d, %Y}. You can still reserve the next lease window if you are willing to wait."
            )
        if self.market_status == "reserved":
            return "This land is currently reserved."
        return "This land is currently available."

    @property
    def pricing_review_status(self):
        if self.price_review_required:
            return "review_required"
        guidance = self.pricing_guidance("sale") if self.listing_type in {"sale", "both"} else None
        if guidance and guidance.get("entered_price_per_unit") is not None:
            if guidance["entered_price_per_unit"] > guidance["band"].max_price_per_unit:
                return "review_required"
            if guidance["entered_price_per_unit"] < guidance["band"].min_price_per_unit:
                return "below_guide"
            return "within_guide"
        return "no_guide"

    @property
    def pricing_review_badge(self):
        mapping = {
            "review_required": ("Price Review Required", "danger"),
            "below_guide": ("Below Regional Guide", "warning"),
            "within_guide": ("Within Regional Guide", "success"),
            "no_guide": ("No Regional Guide", "secondary"),
        }
        label, tone = mapping.get(
            self.pricing_review_status,
            ("Pricing Pending", "secondary"),
        )
        return {"label": label, "tone": tone}

    # ==========================================
    # METHODS
    # ==========================================
    
    def __str__(self):
        return f"{self.title} - {self.location}"

    def get_absolute_url(self):
        return reverse(
            "listings:plot_detail_slug",
            kwargs={
                "county": self.public_county_slug,
                "title": self.public_title_slug,
                "id": self.id,
            },
        )

    def geo_point(self):
        if self.geom:
            return self.geom
        if self.has_coordinates:
            return Point(float(self.longitude), float(self.latitude), srid=4326)
        return None

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
        self.is_registry_record = bool(
            self.registry_owner_name or
            self.registry_owner_id_number or
            self.registry_owner_kra_pin or
            self.search_reference_number
        )
        self.full_clean()
        super().save(*args, **kwargs)

    def distance_to(self, point):
        origin = self.geo_point()
        if origin is None or point is None:
            return None
        if not isinstance(point, Point):
            raise TypeError("point must be a django.contrib.gis.geos.Point instance")
        return origin.distance(point.transform(3857, clone=True)) if origin.srid == 3857 else origin.transform(3857, clone=True).distance(point.transform(3857, clone=True))

    def distance_to_nearest_amenity(self, amenity_qs, field_name="location"):
        origin = self.geo_point()
        if origin is None:
            return None
        try:
            amenity = (
                amenity_qs.filter(**{f"{field_name}__isnull": False})
                .annotate(distance_m=DistanceFunction(field_name, origin))
                .order_by("distance_m")
                .first()
            )
        except ProgrammingError:
            return None
        if not amenity:
            return None
        distance = getattr(amenity, "distance_m", None)
        if distance is None:
            return None
        if hasattr(distance, "m"):
            return float(distance.m)
        return float(distance)

    def amenity_distance_summary(self):
        amenities = [
            ("water", self.water_sources.all(), "location"),
            ("road", self.roads.all(), "location"),
            ("market", self.markets.all(), "location"),
            ("school", self.schools.all(), "location"),
            ("health", self.health_facilities.all(), "location"),
        ]
        summary = {}
        for key, queryset, field_name in amenities:
            distance_meters = self.distance_to_nearest_amenity(queryset, field_name=field_name)
            summary[key] = None if distance_meters is None else round(distance_meters / 1000, 2)
        return summary

    def area_in_unit(self, unit):
        usable_area = self.effective_usable_area_acres
        if usable_area is None:
            return None
        usable_area = Decimal(str(usable_area))
        if unit == "hectares":
            return usable_area / Decimal("2.47105")
        return usable_area

    def sale_price_per_unit(self, unit="acres"):
        area_value = self.area_in_unit(unit)
        if not self.sale_price or not area_value:
            return None
        if area_value <= 0:
            return None
        return self.sale_price / area_value

    def lease_price_per_unit(self, unit="acres"):
        area_value = self.area_in_unit(unit)
        if not area_value or area_value <= 0:
            return None
        yearly_value = self.lease_price_yearly or (
            self.lease_price_monthly * 12 if self.lease_price_monthly else None
        )
        if not yearly_value:
            return None
        return yearly_value / area_value

    def get_market_price_band(self, transaction_type):
        from listings.models import MarketPriceBand  # Import here to avoid circular imports
        
        queryset = MarketPriceBand.objects.filter(
            county=self.county,
            land_type=self.land_type,
            listing_type=transaction_type,
            market_zone=self.market_zone,
            is_active=True,
        )
        if self.subcounty:
            exact_band = queryset.filter(subcounty=self.subcounty).order_by("-effective_from").first()
            if exact_band:
                return exact_band
        return queryset.filter(subcounty__in=["", None]).order_by("-effective_from").first()

    def pricing_guidance(self, transaction_type):
        band = self.get_market_price_band(transaction_type)
        if not band:
            return None
        entered = (
            self.sale_price_per_unit(band.area_unit)
            if transaction_type == "sale"
            else self.lease_price_per_unit(band.area_unit)
        )
        return {
            "band": band,
            "entered_price_per_unit": entered,
        }

    def comparable_pricing_snapshot(self, transaction_type="sale"):
        from listings.models import PriceComparable  # Import here to avoid circular imports
        
        comparables = []

        if self.pk:
            for comparable in self.comparables.exclude(price_per_acre__isnull=True):
                if comparable.price_per_acre and comparable.price_per_acre > 0:
                    comparables.append(Decimal(str(comparable.price_per_acre)))

        county_query = PriceComparable.objects.filter(verified=True)
        if self.county:
            county_query = county_query.filter(location__icontains=self.county)
        if self.soil_type:
            county_query = county_query.filter(soil_type__iexact=self.soil_type)

        comparables.extend(
            Decimal(str(value))
            for value in county_query.exclude(price_per_acre__isnull=True)
            .values_list("price_per_acre", flat=True)[:12]
            if value
        )

        if not comparables:
            return None

        average_per_acre = sum(comparables) / Decimal(len(comparables))
        usable_area = Decimal(str(self.effective_usable_area_acres or self.area_acres or 0))
        if usable_area <= 0:
            return None

        if transaction_type == "lease":
            average_per_unit = average_per_acre / Decimal("12")
            suggested_total = average_per_unit * usable_area
        else:
            average_per_unit = average_per_acre
            suggested_total = average_per_acre * usable_area

        return {
            "sample_size": len(comparables),
            "average_price_per_acre": average_per_acre.quantize(Decimal("0.01")),
            "suggested_total": suggested_total.quantize(Decimal("0.01")),
        }

    def pricing_recommendation(self, transaction_type="sale"):
        band_guidance = self.pricing_guidance(transaction_type)
        comparable_snapshot = self.comparable_pricing_snapshot(transaction_type)
        basis_points = []
        explanation_bits = []
        min_total = None
        max_total = None

        if band_guidance:
            band = band_guidance["band"]
            area_value = self.area_in_unit(band.area_unit)
            if area_value:
                min_total = (
                    Decimal(str(band.min_price_per_unit)) * Decimal(str(area_value))
                ).quantize(Decimal("0.01"))
                max_total = (
                    Decimal(str(band.max_price_per_unit)) * Decimal(str(area_value))
                ).quantize(Decimal("0.01"))
                basis_points.append((min_total + max_total) / Decimal("2"))
                explanation_bits.append(
                    f"regional {transaction_type} guide for {band.county}"
                    f"{' / ' + band.subcounty if band.subcounty else ''} ({band.get_market_zone_display()})"
                )

        if comparable_snapshot:
            basis_points.append(comparable_snapshot["suggested_total"])
            explanation_bits.append(
                f"{comparable_snapshot['sample_size']} comparable record(s) adjusted to {self.effective_usable_area_display.lower()}"
            )

        if not basis_points:
            return None

        suggested_total = (sum(basis_points) / Decimal(len(basis_points))).quantize(Decimal("0.01"))
        return {
            "transaction_type": transaction_type,
            "suggested_total": suggested_total,
            "price_range_min": min_total,
            "price_range_max": max_total,
            "band_guidance": band_guidance,
            "comparable_snapshot": comparable_snapshot,
            "usable_area_display": self.effective_usable_area_display,
            "explanation": "Blended from " + " and ".join(explanation_bits) + ".",
        }

    def special_features_list(self):
        """Return special_features as a list of individual features"""
        if not self.special_features:
            return []
        # Split by newline and filter out empty strings
        return [f.strip() for f in self.special_features.splitlines() if f.strip()]

class WaterSource(models.Model):
    plot = models.ForeignKey(Plot, on_delete=models.CASCADE, related_name="water_sources", null=True, blank=True)
    name = models.CharField(max_length=200)
    location = gis_models.PointField(srid=4326, null=True, blank=True)
    description = models.TextField(blank=True)

    def __str__(self):
        return self.name

class Road(models.Model):
    plot = models.ForeignKey(Plot, on_delete=models.CASCADE, related_name="roads", null=True, blank=True)
    name = models.CharField(max_length=200)
    location = gis_models.PointField(srid=4326, null=True, blank=True)
    road_type = models.CharField(max_length=20, choices=Plot.ROAD_TYPE_CHOICES, blank=True)

    def __str__(self):
        return self.name

class Market(models.Model):
    plot = models.ForeignKey(Plot, on_delete=models.CASCADE, related_name="markets", null=True, blank=True)
    name = models.CharField(max_length=200)
    location = gis_models.PointField(srid=4326, null=True, blank=True)
    description = models.TextField(blank=True)

    def __str__(self):
        return self.name

class School(models.Model):
    plot = models.ForeignKey(Plot, on_delete=models.CASCADE, related_name="schools", null=True, blank=True)
    name = models.CharField(max_length=200)
    location = gis_models.PointField(srid=4326, null=True, blank=True)
    level = models.CharField(max_length=50, blank=True)

    def __str__(self):
        return self.name

class HealthFacility(models.Model):
    plot = models.ForeignKey(Plot, on_delete=models.CASCADE, related_name="health_facilities", null=True, blank=True)
    name = models.CharField(max_length=200)
    location = gis_models.PointField(srid=4326, null=True, blank=True)
    facility_type = models.CharField(max_length=50, blank=True)

    def __str__(self):
        return self.name

class LandTransferAgreement(models.Model):
    plot = models.ForeignKey(Plot, on_delete=models.CASCADE, related_name="transfer_agreements")
    seller = models.ForeignKey(
        "accounts.LandownerProfile",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="selling_agreements",
    )
    buyer = models.ForeignKey(
        "accounts.Profile",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="buying_agreements",
    )
    advocate = models.ForeignKey(
        "accounts.Agent",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="advocate_agreements",
    )
    lawyer = models.ForeignKey(
        "accounts.Agent",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="lawyer_agreements",
    )
    agreement_date = models.DateField(null=True, blank=True)
    document = models.FileField(upload_to="agreements/", null=True, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        permissions = [
            ("view_transfer", "Can view assigned client transfer documents"),
            ("edit_transfer", "Can edit assigned client transfer documents"),
        ]

    def __str__(self):
        return f"Agreement for Plot {self.plot_id}"

    def _user_matches_professional(self, user):
        return (
            (self.advocate and self.advocate.user_id == user.id)
            or (self.lawyer and self.lawyer.user_id == user.id)
        )

    def can_user_view(self, user):
        if not getattr(user, "is_authenticated", False):
            return False
        if user.is_staff or user.is_superuser:
            return True
        if self._user_matches_professional(user):
            return True
        if self.seller and self.seller.user_id == user.id:
            return True
        if self.buyer and self.buyer.user_id == user.id:
            return True
        return False

    def can_user_edit(self, user):
        if not getattr(user, "is_authenticated", False):
            return False
        if user.is_staff or user.is_superuser:
            return True
        return self._user_matches_professional(user)

class FraudReport(models.Model):
    plot = models.ForeignKey(Plot, on_delete=models.CASCADE, related_name="fraud_reports")
    reporter = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    reason = models.TextField()
    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("reviewed", "Reviewed"),
        ("dismissed", "Dismissed"),
    ]
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")
    created_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)

    def __str__(self):
        return f"FraudReport {self.id} on Plot {self.plot_id}"


class UserPlotView(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="plot_views",
    )
    plot = models.ForeignKey(Plot, on_delete=models.CASCADE, related_name="view_events")
    view_count = models.PositiveIntegerField(default=1)
    viewed_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-viewed_at"]
        unique_together = ["user", "plot"]

    def __str__(self):
        return f"{self.user} viewed {self.plot}"

    @classmethod
    def record_view(cls, user, plot):
        obj, created = cls.objects.get_or_create(user=user, plot=plot)
        if not created:
            obj.view_count += 1
            obj.save(update_fields=["view_count", "viewed_at"])
        return obj


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
    subcounty = models.CharField(max_length=100, blank=True)
    market_zone = models.CharField(max_length=20, choices=Plot.MARKET_ZONE_CHOICES, default="rural")
    land_type = models.CharField(max_length=20, choices=Plot.LAND_TYPE_CHOICES)
    listing_type = models.CharField(max_length=10, choices=Plot.LISTING_TYPE_CHOICES)
    area_unit = models.CharField(max_length=10, choices=Plot.AREA_UNIT_CHOICES, default="acres")
    min_price_per_unit = models.DecimalField(max_digits=12, decimal_places=2)
    max_price_per_unit = models.DecimalField(max_digits=12, decimal_places=2)
    effective_from = models.DateField()
    effective_to = models.DateField(null=True, blank=True)
    source = models.CharField(max_length=200, blank=True)
    is_active = models.BooleanField(default=True)
    notes = models.TextField(blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["county", "subcounty", "market_zone", "land_type", "listing_type"]),
        ]

    def __str__(self):
        location = f"{self.county} / {self.subcounty}" if self.subcounty else self.county
        return f"{location} {self.market_zone} {self.land_type} {self.listing_type} band"


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
    "WaterSource",
    "Road",
    "Market",
    "School",
    "HealthFacility",
    "LandTransferAgreement",
    "FraudReport",
    "UserPlotView",
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
