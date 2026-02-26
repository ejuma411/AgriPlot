from django.db import models
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.contrib.contenttypes.models import ContentType  # ✅ Add this import
from django.utils import timezone  # ✅ Add this for timestamps
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.fields import GenericRelation

# -----------------------------
# User & Role Models
# -----------------------------

class Profile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    phone = models.CharField(max_length=20, blank=True, null=True)
    phone_verified = models.BooleanField(default=False)
    email_verified = models.BooleanField(default=False)
    has_2fa_enabled = models.BooleanField(default=False)
    address = models.TextField(blank=True, default="")
    
    ROLE_CHOICES = [
        ('buyer', 'Buyer'),
        ('landowner', 'Landowner'),
        ('agent', 'Agent'),
        ('admin', 'Administrator'),
    ]
    
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='buyer')

    def __str__(self):
        return self.user.username
    
    @property
    def is_verified_seller(self):
        """Backward compatibility - checks if user is verified landowner"""
        return hasattr(self.user, 'landownerprofile') and self.user.landownerprofile.verified
    
    @property
    def is_verified_broker(self):
        """Backward compatibility - checks if user is verified agent"""
        return hasattr(self.user, 'agent') and self.user.agent.verified
    
    @property
    def is_landowner(self):
        return hasattr(self.user, 'landownerprofile')
    
    @property
    def is_agent(self):
        return hasattr(self.user, 'agent')
    
    @property
    def is_seller(self):
        return self.is_landowner
    
    @property
    def is_broker(self):
        return self.is_agent


class Agent(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)

    phone = models.CharField(
        max_length=20,
        blank=False,
        default="",
        help_text="Kindly provide your Phone Number"
    )

    license_number = models.CharField(
        max_length=100,
        blank=True,
        default="",
        help_text="Professional license number"
    )

    license_doc = models.FileField(
        upload_to="docs/agent_licenses/",
        null=True,
        blank=True
    )

    verified = models.BooleanField(default=False)

    def __str__(self):
        return self.user.username
    
    # Professional & Contact fields
    id_number = models.CharField(max_length=20, help_text="National ID")
    kra_pin = models.FileField(upload_to="docs/agent_kra/", null=True, blank=True)
    practicing_certificate = models.FileField(upload_to="docs/practicing_certs/", null=True, blank=True)
    good_conduct = models.FileField(upload_to="docs/good_conduct/", null=True, blank=True)
    professional_indemnity = models.FileField(upload_to="docs/indemnity/", null=True, blank=True)
    
    response_rate = models.FloatField(default=100.0, help_text="Percentage of inquiries responded to")
    average_response_time = models.FloatField(default=24, help_text="Average response time in hours")
    rating = models.FloatField(default=5.0)
    review_count = models.IntegerField(default=0)
    
    total_listings = models.IntegerField(default=0)
    verified_listings = models.IntegerField(default=0)
    
    contact_preference = models.CharField(
        max_length=20,
        choices=[
            ('email', 'Email'),
            ('phone', 'Phone'),
            ('whatsapp', 'WhatsApp'),
            ('any', 'Any'),
        ],
        default='any'
    )
    
    available_from = models.TimeField(default='09:00')
    available_to = models.TimeField(default='17:00')
    
    def update_stats(self):
        """Update agent statistics"""
        self.total_listings = self.plot_set.count()
        self.verified_listings = self.plot_set.filter(
            verification_status__status='verified'
        ).count()
        self.save()


# Backward compatibility: Broker is now Agent
Broker = Agent


class LandownerProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    
    national_id = models.FileField(
        upload_to="docs/national_ids/",
        blank=False,
        null=False,
        help_text="Upload a copy of your national ID"
    )
    
    kra_pin = models.FileField(
        upload_to="docs/kra_pins/",
        blank=False,
        null=False,
        help_text="Upload a copy of your KRA PIN"
    )
    
    title_deed = models.FileField(
        upload_to="docs/landowner_title_deeds/",
        blank=True,
        null=True,
        help_text="Land title deed proving ownership (required for verification)"
    )
    
    land_search = models.FileField(
        upload_to="docs/land_searches/",
        blank=True,
        null=True,
        help_text="Official land search certificate (ARDHI/Ardhisasa, validity ~3 months)"
    )
    
    lcb_consent = models.FileField(
        upload_to="docs/lcb_consents/",
        blank=True,
        null=True,
        help_text="Optional: Upload LCB consent if applicable"
    )
    
    verified = models.BooleanField(default=False)
    verified_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="landowner_verifications_reviewed"
    )
    rejection_reason = models.TextField(
        blank=True,
        help_text="Reason for rejection if verification failed (allows re-submission)"
    )
    
    def __str__(self):
        return f"LandownerProfile: {self.user.username}"


# -----------------------------
# Plot / Listing Model
# -----------------------------
class Plot(models.Model):
    LISTING_TYPE_CHOICES = [
        ('sale', 'For Sale'),
        ('lease', 'For Lease'),
        ('both', 'For Sale & Lease'),
    ]
    
    LEASE_DURATION_CHOICES = [
        ('monthly', 'Month-to-Month'),
        ('seasonal', 'Seasonal (3-6 months)'),
        ('1year', '1 Year'),
        ('3years', '3 Years'),
        ('5years', '5 Years'),
        ('10years', '10 Years'),
    ]
    
    LAND_TYPE_CHOICES = [
        ('agricultural', 'Agricultural Land'),
        ('residential', 'Residential Plot'),
        ('commercial', 'Commercial Land'),
        ('mixed_use', 'Mixed Use'),
        ('industrial', 'Industrial Land'),
    ]
    
    WATER_SOURCE_CHOICES = [
        ('borehole', 'Borehole'),
        ('river', 'River/Stream'),
        ('rain', 'Rain-fed'),
        ('irrigation', 'Irrigation System'),
        ('none', 'No Water Source'),
    ]
    
    ROAD_TYPE_CHOICES = [
        ('tarmac', 'Tarmac'),
        ('murram', 'Murram/Gravel'),
        ('earth', 'Earth Road'),
        ('footpath', 'Footpath Only'),
        ('none', 'No Access'),
    ]
    
    FENCING_CHOICES = [
        ('full', 'Full Perimeter'),
        ('partial', 'Partial'),
        ('none', 'No Fencing'),
        ('live', 'Live Fence'),
    ]

    # Location
    county = models.CharField(max_length=100, blank=True, null=True)
    subcounty = models.CharField(max_length=100, blank=True, null=True)
    nearest_town = models.CharField(max_length=150, blank=True)
    ownership_type = models.CharField(
        max_length=20,
        choices=[
            ('freehold', 'Freehold'),
            ('leasehold', 'Leasehold'),
            ('government', 'Government'),
            ('community', 'Community'),
        ],
        default='freehold'
    )
    tenure_details = models.CharField(max_length=200, blank=True, help_text="Lease duration/expiry or tenure notes")
    encumbrances = models.BooleanField(default=False)
    encumbrance_details = models.TextField(blank=True)

    # Ownership
    landowner = models.ForeignKey(LandownerProfile, on_delete=models.CASCADE, null=True, blank=True)
    agent = models.ForeignKey(Agent, on_delete=models.CASCADE, null=True, blank=True)

    # Basic Info
    title = models.CharField(max_length=200)
    location = models.CharField(max_length=300)
    area = models.FloatField(help_text="In acres or hectares")
    
    # Listing Type
    listing_type = models.CharField(max_length=10, choices=LISTING_TYPE_CHOICES, default='sale')
    land_type = models.CharField(max_length=20, choices=LAND_TYPE_CHOICES, default='agricultural')
    land_use_description = models.TextField(blank=True)
    
    # Sale-specific
    sale_price = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    price_per_acre = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    PRICE_BASIS_CHOICES = [
        ('owner_set', 'Owner-set price'),
        ('agent_market', 'Agent market analysis'),
        ('valuation_report', 'Professional valuation report'),
        ('government_set', 'Government-set price'),
        ('negotiated', 'Negotiated (market demand)'),
    ]
    price_basis = models.CharField(
        max_length=30,
        choices=PRICE_BASIS_CHOICES,
        default='owner_set'
    )
    valuation_report = models.FileField(
        upload_to="documents/valuation_reports/",
        null=True,
        blank=True,
        help_text="Optional valuation report (PDF/Image)"
    )
    price_notes = models.TextField(
        blank=True,
        help_text="Notes on how price was determined (market trends, valuation, negotiations)"
    )
    is_price_negotiable = models.BooleanField(default=True)
    
    # Lease-specific
    lease_price_monthly = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    lease_price_yearly = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    lease_duration = models.CharField(max_length=20, choices=LEASE_DURATION_CHOICES, null=True, blank=True)
    lease_terms = models.TextField(blank=True)
    lease_basis = models.CharField(
        max_length=30,
        choices=PRICE_BASIS_CHOICES,
        default='owner_set'
    )
    government_price_proof = models.FileField(
        upload_to="documents/government_price_proofs/",
        null=True,
        blank=True,
        help_text="Official notice/gazette for government-set price"
    )
    
    # Legacy price field (keep for backward compatibility)
    price = models.DecimalField(max_digits=12, decimal_places=2)

    # Agricultural Fields
    soil_type = models.CharField(max_length=100, blank=True, default="")
    ph_level = models.FloatField(null=True, blank=True)
    crop_suitability = models.CharField(max_length=200, blank=True, default="")

    # Infrastructure
    has_water = models.BooleanField(default=False)
    water_source = models.CharField(max_length=20, choices=WATER_SOURCE_CHOICES, null=True, blank=True)
    
    has_electricity = models.BooleanField(default=False)
    electricity_meter = models.BooleanField(default=False, help_text="Has meter installed")
    
    has_road_access = models.BooleanField(default=False)
    road_type = models.CharField(max_length=20, choices=ROAD_TYPE_CHOICES, null=True, blank=True)
    road_distance_km = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    
    has_buildings = models.BooleanField(default=False)
    building_description = models.TextField(blank=True)
    
    fencing = models.CharField(max_length=50, choices=FENCING_CHOICES, null=True, blank=True)

    verification = GenericRelation('VerificationStatus', 
                                   content_type_field='content_type',
                                   object_id_field='object_id',
                                   related_query_name='plot')

    # PRIMARY DOCUMENTS
    title_deed = models.FileField(
        upload_to="documents/title_deeds/", 
        null=True, 
        blank=True,
        help_text="Official title deed document"
    )
    
    soil_report = models.FileField(
        upload_to="documents/soil_reports/", 
        null=True, 
        blank=True,
        help_text="Soil test report (optional)"
    )
    
    # VERIFICATION DOCUMENTS
    official_search = models.FileField(
        upload_to="documents/official_searches/",
        null=True,
        blank=True,
        help_text="Official land search certificate"
    )
    
    landowner_id_doc = models.FileField(  # ✅ Changed from landowner_id
        upload_to="documents/landowner_ids/",
        null=True,
        blank=True,
        help_text="Landowner's national ID"
    )
    
    kra_pin = models.FileField(
        upload_to="documents/kra_pins/",
        null=True,
        blank=True,
        help_text="KRA PIN certificate"
    )
    
    # GIS / Location (latitude & longitude for mapping)
    latitude = models.DecimalField(
        max_digits=9,
        decimal_places=6,
        null=True,
        blank=True,
        help_text="Latitude (e.g. -1.292066 for Nairobi)"
    )
    longitude = models.DecimalField(
        max_digits=9,
        decimal_places=6,
        null=True,
        blank=True,
        help_text="Longitude (e.g. 36.821946 for Nairobi)"
    )
    
    # Environmental / regulatory (Q4)
    elevation_meters = models.IntegerField(null=True, blank=True, help_text="Elevation in metres")
    climate_zone = models.CharField(max_length=100, blank=True)
    is_protected_area = models.BooleanField(
        default=False,
        help_text="Conservancy, forest reserve, etc."
    )
    special_features = models.TextField(
        blank=True,
        help_text="e.g., mature trees, water tank, scenic view"
    )
    
    # Additional metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_published = models.BooleanField(default=False)
    class Meta:
        indexes = [
            models.Index(fields=['-created_at']),
            models.Index(fields=['listing_type']),
            models.Index(fields=['land_type']),
            models.Index(fields=['soil_type']),
            models.Index(fields=['latitude', 'longitude']),
        ]

    def __str__(self):
        return self.title
    
    def clean(self):
        """Validate plot data"""
        if not self.landowner and not self.agent:
            raise ValidationError("Either landowner or agent must be associated with this plot")
        
        if self.listing_type in ['sale', 'both'] and not self.sale_price:
            raise ValidationError("Sale price is required for listings marked 'For Sale'")
        
        if self.listing_type in ['lease', 'both'] and not (self.lease_price_monthly or self.lease_price_yearly):
            raise ValidationError("Lease price is required for listings marked 'For Lease'")

        if self.encumbrances and not self.encumbrance_details:
            raise ValidationError("Provide encumbrance details when encumbrances are marked as present.")
        
    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    @property
    def has_coordinates(self):
        """True if plot has latitude and longitude for GIS mapping."""
        return self.latitude is not None and self.longitude is not None
    
    @property
    def has_all_documents(self):
        """Check if plot has all required documents"""
        required_docs = ['title_deed', 'official_search', 'landowner_id_doc', 'kra_pin']
        for doc_field in required_docs:
            if not getattr(self, doc_field):
                return False
        return True
    
    def get_reaction_counts(self):
        """Get all reaction counts for this plot"""
        return {
            'love': self.reactions.filter(reaction_type='love').count(),
            'like': self.reactions.filter(reaction_type='like').count(),
            'potential': self.reactions.filter(reaction_type='potential').count(),
        }
    
    def get_user_reactions(self, user):
        """Get reactions for a specific user on this plot"""
        if not user.is_authenticated:
            return []
        return list(self.reactions.filter(user=user).values_list('reaction_type', flat=True))
    
    def total_reaction_count(self):
        """Get total number of all reactions"""
        return self.reactions.count()


# -----------------------------
# Document Uploads for Verification
# -----------------------------
class VerificationDocument(models.Model):
    DOC_TYPE_CHOICES = [
        ('title_deed', "Title Deed"),
        ('official_search', "Official Search Certificate"),
        ('landowner_id', "Landowner National ID"),
        ('kra_pin', "KRA PIN Certificate"),
        ('survey_plan', "Survey Plan"),
        ('rates_clearance', "Land Rates Clearance"),
        ('lcb_consent', "LCB Consent"),
    ]

    plot = models.ForeignKey(Plot, on_delete=models.CASCADE, related_name="verification_docs")
    uploaded_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    doc_type = models.CharField(max_length=30, choices=DOC_TYPE_CHOICES)
    file = models.FileField(upload_to="verification_docs/")
    uploaded_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.plot.title} — {self.get_doc_type_display()}"


# -----------------------------
# Official Title Search Results
# -----------------------------
class TitleSearchResult(models.Model):
    plot = models.OneToOneField(Plot, on_delete=models.CASCADE, related_name="search_result")
    search_platform = models.CharField(max_length=50)
    official_owner = models.CharField(max_length=200)
    parcel_number = models.CharField(max_length=100)
    encumbrances = models.TextField(null=True, blank=True)
    lease_status = models.CharField(max_length=100, null=True, blank=True)
    search_date = models.DateField(null=True, blank=True)
    raw_response_file = models.FileField(upload_to="search_responses/", null=True, blank=True)
    verified = models.BooleanField(default=False)
    notes = models.TextField(null=True, blank=True)

    def __str__(self):
        return f"SearchResult — {self.plot.title} ({self.search_platform})"


# -----------------------------
# Plot Verification Workflow Status
# -----------------------------
class VerificationStatus(models.Model):
    """Track verification progress for landowners and agents"""
    
    STAGES = [
        ('document_uploaded', 'Documents Uploaded'),
        ('api_verification_started', 'API Verification Started'),
        ('title_search_completed', 'Title Search Completed'),
        ('owner_verified', 'Owner Identity Verified'),
        ('encumbrance_check', 'Encumbrance Check'),
        ('physical_location_verified', 'Physical Location Verified'),
        ('admin_review', 'Under Admin Review'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ]
    
    # Generic relation to either LandownerProfile or Agent
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveIntegerField()
    content_object = GenericForeignKey('content_type', 'object_id')
    
    current_stage = models.CharField(max_length=50, choices=STAGES, default='document_uploaded')
    stage_details = models.JSONField(default=dict, blank=True)  # Store stage-specific data
    is_complete = models.BooleanField(default=False)
    
    # API response data
    api_responses = models.JSONField(default=list, blank=True)  # Store all API responses
    search_reference = models.CharField(max_length=100, blank=True)
    search_fee_paid = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    
    # Timestamps for each stage
    document_uploaded_at = models.DateTimeField(null=True, blank=True)
    api_started_at = models.DateTimeField(null=True, blank=True)
    title_search_at = models.DateTimeField(null=True, blank=True)
    owner_verified_at = models.DateTimeField(null=True, blank=True)
    admin_review_at = models.DateTimeField(null=True, blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    rejected_at = models.DateTimeField(null=True, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [['content_type', 'object_id']]
    
    def __str__(self):
        return f"Verification for {self.content_object} - {self.get_current_stage_display()}"
    
    def update_stage(self, stage, details=None):
        """Update to next stage with timestamp"""
        # Store original values
        original_stage = self.current_stage
        
        # Update the instance
        self.current_stage = stage
        if details:
            self.stage_details[stage] = details
        
        # Set corresponding timestamp
        timestamp_field = f"{stage}_at"
        if hasattr(self, timestamp_field):
            setattr(self, timestamp_field, timezone.now())
        
        if stage == 'approved':
            self.is_complete = True
        
        # Use update() to bypass signals if we're in a recursive situation
        # But for now, just save normally
        self.save()

        # Notify plot owner on stage change
        try:
            if original_stage != stage and self.content_type.model == 'plot':
                if stage not in ('approved', 'rejected'):
                    from .notification_service import NotificationService
                    NotificationService.notify_plot_stage(self.content_object, stage, details)
        except Exception:
            pass
        
    # In VerificationStatus, add method to trigger API check
    def trigger_ardhisasa_check(self):
        """Call Ardhisasa API to verify title"""
        if self.current_stage == 'document_uploaded':
            self.update_stage('api_verification_started')
        
    
    def add_api_response(self, response_data):
        """Store API response for audit trail"""
        self.api_responses.append({
            'timestamp': timezone.now().isoformat(),
            'data': response_data
        })
        self.save()

    @property
    def progress_percentage(self):
        """Calculate progress percentage based on current stage"""
        stages = [stage[0] for stage in self.STAGES]
        
        if self.current_stage == 'approved':
            return 100
        elif self.current_stage == 'rejected':
            return 100  # Also show 100% for rejected (completed)
        elif self.current_stage in stages:
            index = stages.index(self.current_stage)
            # Calculate percentage: (index + 1) / total_stages * 100
            total_stages = len(stages)
            return int((index + 1) / total_stages * 100)
        return 0
    
    @property
    def estimated_completion(self):
        """Return estimated completion message"""
        if self.current_stage == 'approved':
            return "Verification complete"
        elif self.current_stage == 'rejected':
            return "Verification rejected"
        elif self.current_stage == 'admin_review':
            return "Awaiting admin review (usually within 24 hours)"
        elif self.current_stage in ['title_search_completed', 'owner_verified', 'encumbrance_check']:
            return "API verification in progress (typically 2-3 business days)"
        else:
            return "Verification in progress"

class PlotVerification(models.Model):
    """Track verification for individual plots"""
    
    plot = models.OneToOneField('Plot', on_delete=models.CASCADE, related_name='verification')
    owner_verified = models.ForeignKey(VerificationStatus, on_delete=models.SET_NULL, null=True)
    
    # Similar stages for plot verification
    STAGES = [
        ('submitted', 'Submitted for Verification'),
        ('document_check', 'Document Check'),
        ('title_search', 'Title Search with Ardhisasa'),
        ('physical_verification', 'Physical Verification'),
        ('admin_approval', 'Admin Approval'),
        ('approved', 'Approved for Listing'),
        ('rejected', 'Rejected'),
    ]
    
    current_stage = models.CharField(max_length=50, choices=STAGES, default='submitted')
    stage_details = models.JSONField(default=dict)
    api_responses = models.JSONField(default=list)
    
    # Timestamps
    submitted_at = models.DateTimeField(auto_now_add=True)
    title_search_at = models.DateTimeField(null=True, blank=True)
    admin_review_at = models.DateTimeField(null=True, blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    
    def __str__(self):
        return f"Verification for Plot {self.plot.id}"

# -----------------------------
# Soil Report Model
# -----------------------------
class SoilReport(models.Model):
    VERIFICATION_CHOICES = [
        ('draft', 'Draft'),
        ('unverified', 'Unverified'),
        ('lab_verified', 'Lab Verified'),
        ('rejected', 'Rejected'),
    ]

    plot = models.ForeignKey(Plot, on_delete=models.CASCADE, related_name='soil_reports')
    pH = models.DecimalField(max_digits=4, decimal_places=2, null=True, blank=True)
    organic_matter_pct = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    nitrogen_mgkg = models.DecimalField(max_digits=7, decimal_places=2, null=True, blank=True)
    phosphorus_mgkg = models.DecimalField(max_digits=7, decimal_places=2, null=True, blank=True)
    potassium_mgkg = models.DecimalField(max_digits=7, decimal_places=2, null=True, blank=True)
    sand_pct = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    silt_pct = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    clay_pct = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    ec_salinity = models.DecimalField(max_digits=6, decimal_places=3, null=True, blank=True)
    lab_id = models.CharField(max_length=100, blank=True, default="")
    sample_date = models.DateField(null=True, blank=True)
    geo_lat = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    geo_lng = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    report_file = models.FileField(upload_to='documents/soil_reports/', null=True, blank=True)
    verification_status = models.CharField(max_length=20, choices=VERIFICATION_CHOICES, default='draft')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ('-created_at',)
        indexes = [
            models.Index(fields=['pH']),
            models.Index(fields=['organic_matter_pct']),
        ]

    def __str__(self):
        return f"SoilReport {self.id} — {self.plot.title} ({self.verification_status})"


# -----------------------------
# User Interest Model
# -----------------------------
class UserInterest(models.Model):
    """Tracks buyer interest in plots."""
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('contacted', 'Contacted'),
        ('scheduled', 'Viewing Scheduled'),
        ('rejected', 'Not Interested'),
        ('accepted', 'Accepted Offer'),
    ]
    
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='plot_interests')
    plot = models.ForeignKey(Plot, on_delete=models.CASCADE, related_name='buyer_interests')
    message = models.TextField(blank=True, help_text="Buyer's message or inquiry")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    notes = models.TextField(blank=True, help_text="Internal notes from agent")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-created_at']
        unique_together = ['user', 'plot']
    
    def __str__(self):
        return f"{self.user.username} → {self.plot.title}"
    

# -----------------------------
# Messaging / Contact Request Model
# -----------------------------
class ContactRequest(models.Model):
    REQUEST_TYPES = [
        ('email', 'Email Inquiry'),
        ('phone_request', 'Phone Number Request'),
        ('phone_view', 'Phone Number Viewed'),
        ('visit_request', 'Site Visit Request'),
        ('message', 'Direct Message'),
    ]
    
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='contact_requests')
    plot = models.ForeignKey(Plot, on_delete=models.CASCADE, related_name='contact_requests')
    agent = models.ForeignKey(
        Agent,
        on_delete=models.CASCADE,
        related_name='contact_requests',
        null=True,
        blank=True
    )
    request_type = models.CharField(max_length=20, choices=REQUEST_TYPES)
    message = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    responded = models.BooleanField(default=False)
    responded_at = models.DateTimeField(null=True, blank=True)
    admin_notes = models.TextField(
        blank=True,
        null=True,
        help_text="Internal notes for admin use only"
    )
    
    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['-created_at']),
            models.Index(fields=['responded']),
        ]
    
    def __str__(self):
        if self.agent:
            recipient = self.agent.user.username
        elif self.plot.landowner:
            recipient = self.plot.landowner.user.username
        else:
            recipient = "plot-owner"
        return f"{self.user.username} → {recipient} ({self.request_type})"


# -----------------------------
# Plot Reactions Model
# -----------------------------
class PlotReaction(models.Model):
    """Track user reactions (love, like, potential) on plots."""
    REACTION_CHOICES = [
        ('love', '❤️ Love'),
        ('like', '👍 Like'),
        ('potential', '🌱 Growth Potential'),
    ]
    
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='plot_reactions')
    plot = models.ForeignKey(Plot, on_delete=models.CASCADE, related_name='reactions')
    reaction_type = models.CharField(max_length=20, choices=REACTION_CHOICES)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-created_at']
        unique_together = ['user', 'plot', 'reaction_type']
        indexes = [
            models.Index(fields=['plot', 'reaction_type']),
        ]
    
    def __str__(self):
        return f"{self.user.username} {self.get_reaction_type_display()} {self.plot.title}"


# -----------------------------
# Audit Log (ZTA/CIA)
# -----------------------------
class AuditLog(models.Model):
    """Log sensitive actions for compliance and security (who did what when)."""
    ACTION_CHOICES = [
        ('create_plot', 'Create Listing'),
        ('edit_plot', 'Edit Listing'),
        ('delete_plot', 'Delete Listing'),
        ('verify_landowner', 'Verify Landowner'),
        ('reject_landowner', 'Reject Landowner'),
        ('verify_agent', 'Verify Agent'),
        ('verify_plot', 'Verify Plot'),
        ('reject_plot', 'Reject Plot'),
        ('change_price', 'Change Price'),
        ('login', 'Login'),
        ('failed_login', 'Failed Login'),
    ]
    user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='audit_logs'
    )
    action = models.CharField(max_length=50, choices=ACTION_CHOICES)
    object_type = models.CharField(max_length=50, blank=True)  # e.g. 'Plot', 'LandownerProfile'
    object_id = models.PositiveIntegerField(null=True, blank=True)
    extra = models.JSONField(default=dict, blank=True)  # e.g. {'plot_id': 1, 'old_price': 100}
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['-created_at']),
            models.Index(fields=['user', 'action']),
        ]

    def __str__(self):
        return f"{self.get_action_display()} by {self.user_id} at {self.created_at}"


# -----------------------------
# Pricing - Comparables & Suggestions 
# -----------------------------
class PriceComparable(models.Model):
    """Market comparable sales for pricing suggestions."""
    location = models.CharField(max_length=300)
    area_acres = models.DecimalField(max_digits=10, decimal_places=2)
    sale_price = models.DecimalField(max_digits=12, decimal_places=2)
    price_per_acre = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    soil_type = models.CharField(max_length=100, blank=True)
    crop_type = models.CharField(max_length=200, blank=True)
    sale_date = models.DateField(null=True, blank=True)
    data_source = models.CharField(max_length=100, blank=True)  # Ardhisasa, Agent, Manual
    verified = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-sale_date', '-created_at']

    def save(self, *args, **kwargs):
        if self.area_acres and self.area_acres > 0 and not self.price_per_acre:
            self.price_per_acre = self.sale_price / self.area_acres
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.location} — {self.area_acres} ac @ {self.sale_price}"


class PricingSuggestion(models.Model):
    """AI/system-generated pricing recommendation for a plot."""
    plot = models.ForeignKey(Plot, on_delete=models.CASCADE, related_name='pricing_suggestions')
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
        ordering = ['-generated_at']

    def __str__(self):
        return f"Suggestion for Plot {self.plot_id}: {self.suggested_price}"


# -----------------------------
# Verification Task & Log
# -----------------------------
class VerificationTask(models.Model):
    """Assign verification tasks to staff (document review, extension review, surveyor)."""
    TASK_TYPE_CHOICES = [
        ('document_review', 'Document Review'),
        ('extension_review', 'Extension Officer Review'),
        ('surveyor_inspection', 'Land Surveyor Inspection'),
    ]
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('in_progress', 'In Progress'),
        ('completed', 'Completed'),
    ]
    plot = models.ForeignKey(Plot, on_delete=models.CASCADE, related_name='verification_tasks')
    verification_type = models.CharField(max_length=30, choices=TASK_TYPE_CHOICES)
    assigned_to = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='assigned_verification_tasks'
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    assigned_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)
    approved = models.BooleanField(null=True, blank=True)  # True/False/None

    class Meta:
        ordering = ['-assigned_at']

    def __str__(self):
        return f"{self.get_verification_type_display()} — Plot {self.plot_id} ({self.status})"


class VerificationLog(models.Model):
    """Track all verification events (audit trail)."""
    plot = models.ForeignKey(Plot, on_delete=models.CASCADE, related_name='verification_logs')
    verified_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name='verification_actions'
    )
    verification_type = models.CharField(max_length=50)
    comment = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Plot {self.plot_id} — {self.verification_type} by {self.verified_by_id}"


# -----------------------------
# Document Verification (impersonation prevention)
# -----------------------------
class DocumentVerification(models.Model):
    """Per-document verification checks (readability, name match, approval)."""
    DOC_TYPE_CHOICES = [
        ('national_id', 'National ID'),
        ('kra_pin', 'KRA PIN'),
        ('title_deed', 'Title Deed'),
        ('official_search', 'Official Search'),
    ]
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='document_verifications')
    plot = models.ForeignKey('Plot', on_delete=models.SET_NULL, null=True, blank=True, related_name='document_verifications')
    task = models.ForeignKey('VerificationTask', on_delete=models.SET_NULL, null=True, blank=True, related_name='document_verifications')
    document_type = models.CharField(max_length=30, choices=DOC_TYPE_CHOICES)
    document_file = models.FileField(upload_to="verification_docs/", null=True, blank=True)

    is_readable = models.BooleanField(null=True, blank=True)
    is_not_expired = models.BooleanField(null=True, blank=True)
    name_matches_user = models.BooleanField(null=True, blank=True)
    all_names_match = models.BooleanField(null=True, blank=True)

    verified_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='documents_verified'
    )
    verified_at = models.DateTimeField(null=True, blank=True)
    verification_notes = models.TextField(blank=True)
    approved = models.BooleanField(null=True, blank=True)  # True/False/None (pending)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    @classmethod
    def verify_document(cls, plot, doc_type, reviewer, approved, notes, task=None):
        doc_file = None
        if doc_type == 'national_id':
            doc_file = getattr(plot, 'landowner_id_doc', None)
        elif doc_type == 'kra_pin':
            doc_file = getattr(plot, 'kra_pin', None)
        elif doc_type == 'title_deed':
            doc_file = getattr(plot, 'title_deed', None)
        elif doc_type == 'official_search':
            doc_file = getattr(plot, 'official_search', None)

        verification = cls.objects.create(
            user=plot.agent.user if plot.agent else plot.landowner.user,
            plot=plot,
            task=task,
            document_type=doc_type,
            document_file=doc_file,
            is_readable=True,
            name_matches_user=approved,
            all_names_match=approved,
            verified_by=reviewer,
            verified_at=timezone.now(),
            verification_notes=notes,
            approved=approved
        )
        return verification

    class Meta:
        ordering = ['-created_at']
        unique_together = [['user', 'document_type', 'plot']]

    def __str__(self):
        return f"{self.user.username} — {self.get_document_type_display()} ({self.approved})"

# -----------------------------
# Impersonation Detection (Q7)
# -----------------------------
class ImpersonationDetection(models.Model):
    ALERT_TYPES = [
        ('duplicate_id', 'Same ID multiple accounts'),
        ('name_mismatch', 'Name mismatch across documents'),
        ('rapid_listings', 'Too many listings too quickly'),
        ('geographic_mismatch', 'Listings far apart'),
        ('content_similarity', 'Listing description copied'),
    ]
    SEVERITY_CHOICES = [
        ('low', 'Low Risk'),
        ('medium', 'Medium Risk'),
        ('high', 'High Risk - Block'),
    ]
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='impersonation_alerts')
    alert_type = models.CharField(max_length=50, choices=ALERT_TYPES)
    severity = models.CharField(max_length=20, choices=SEVERITY_CHOICES, default='low')
    description = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    resolved = models.BooleanField(default=False)

    class Meta:
        ordering = ['-created_at']
        indexes = [models.Index(fields=['severity', '-created_at'])]

    def __str__(self):
        return f"{self.user_id} — {self.alert_type} ({self.severity})"

# -----------------------------
# Phone/Email Verification (Q7)
# -----------------------------
class PhoneEmailVerification(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='contact_verification')
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

    def __str__(self):
        return f"{self.user_id} — phone:{self.phone_verified} email:{self.email_verified}"

# -----------------------------
# Document Hashing (Q8 Integrity)
# -----------------------------
class DocumentHash(models.Model):
    file_hash = models.CharField(max_length=64, unique=True)
    file_name = models.CharField(max_length=255, blank=True, default="")
    uploaded_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-uploaded_at']

    def __str__(self):
        return f"{self.file_name} — {self.file_hash[:10]}"

# NOTIFICATION/EMAILING

class Notification(models.Model):
    """System notifications for users"""
    
    NOTIFICATION_TYPES = [
        ('task_assigned', 'Task Assigned'),
        ('task_completed', 'Task Completed'),
        ('plot_approved', 'Plot Approved'),
        ('plot_rejected', ' Plot Rejected'),
        ('changes_requested', 'Changes Requested'),
        ('document_uploaded', 'Document Uploaded'),
        ('verification_started', 'Verification Started'),
        ('verification_completed', 'Verification Completed'),
    ]
    
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='notifications')
    notification_type = models.CharField(max_length=50, choices=NOTIFICATION_TYPES)
    title = models.CharField(max_length=200)
    message = models.TextField()
    plot = models.ForeignKey(Plot, on_delete=models.CASCADE, null=True, blank=True, related_name='notifications')
    task = models.ForeignKey(VerificationTask, on_delete=models.CASCADE, null=True, blank=True, related_name='notifications')
    
    is_read = models.BooleanField(default=False)
    is_email_sent = models.BooleanField(default=False)
    email_sent_at = models.DateTimeField(null=True, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    read_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', '-created_at']),
            models.Index(fields=['user', 'is_read']),
        ]
    
    def __str__(self):
        return f"{self.user.username} - {self.notification_type} - {self.created_at}"
    
    def mark_as_read(self):
        """Mark notification as read"""
        self.is_read = True
        self.read_at = timezone.now()
        self.save()


class EmailLog(models.Model):
    """Track all emails sent by the system"""
    
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('sent', 'Sent'),
        ('failed', 'Failed'),
    ]
    
    recipient = models.EmailField()
    subject = models.CharField(max_length=500)
    template = models.CharField(max_length=100)
    context = models.JSONField(default=dict)
    
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    error_message = models.TextField(blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        ordering = ['-created_at']

class ExtensionOfficer(models.Model):
    """Extension Officer role for agricultural verification"""
    
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='extension_officer')
    
    # Professional Details
    employee_id = models.CharField(max_length=50, unique=True, help_text="Government/Institution employee ID")
    designation = models.CharField(max_length=100, help_text="e.g., Agricultural Officer, Livestock Officer")
    department = models.CharField(max_length=100, default="Ministry of Agriculture")
    station = models.CharField(max_length=200, help_text="Assigned location/office")
    
    # Qualifications
    qualifications = models.TextField(help_text="Academic and professional qualifications")
    specializations = models.CharField(max_length=300, blank=True, help_text="e.g., Crop Science, Soil Science")
    years_of_experience = models.IntegerField(default=0)
    
    # Contact
    phone = models.CharField(max_length=20)
    office_address = models.TextField(blank=True)
    
    # Verification jurisdiction
    assigned_counties = models.JSONField(default=list, help_text="List of counties they can verify")
    max_daily_tasks = models.IntegerField(default=5, help_text="Maximum tasks per day")
    
    # Status
    is_active = models.BooleanField(default=True)
    verified = models.BooleanField(default=False)
    verified_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='verified_officers')
    verified_at = models.DateTimeField(null=True, blank=True)
    
    # Performance metrics
    total_tasks_completed = models.IntegerField(default=0)
    average_rating = models.FloatField(default=0.0)
    response_time_avg = models.FloatField(default=0, help_text="Average response time in hours")
    
    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        indexes = [
            models.Index(fields=['station']),
            models.Index(fields=['is_active']),
        ]
    
    def __str__(self):
        return f"{self.user.get_full_name()} - {self.designation} ({self.station})"
    
    @property
    def current_workload(self):
        """Get current number of assigned tasks"""
        from .models import VerificationTask
        return VerificationTask.objects.filter(
            assigned_to=self.user,
            status='in_progress'
        ).count()
    
    @property
    def can_accept_tasks(self):
        """Check if officer can accept more tasks"""
        return self.current_workload < self.max_daily_tasks and self.is_active


class ExtensionReport(models.Model):
    """Reports submitted by Extension Officers after site visits"""
    
    task = models.OneToOneField('VerificationTask', on_delete=models.CASCADE, related_name='extension_report')
    officer = models.ForeignKey(ExtensionOfficer, on_delete=models.CASCADE, related_name='reports')
    plot = models.ForeignKey('Plot', on_delete=models.CASCADE, related_name='extension_reports')
    
    # Visit details
    visit_date = models.DateTimeField()
    weather_conditions = models.CharField(max_length=100, blank=True)
    
    # Soil assessment
    soil_ph_verified = models.FloatField(null=True, blank=True)
    soil_texture = models.CharField(max_length=50, choices=[
        ('sandy', 'Sandy'),
        ('loamy', 'Loamy'),
        ('clay', 'Clay'),
        ('silty', 'Silty'),
        ('peaty', 'Peaty'),
    ], blank=True)
    soil_depth = models.CharField(max_length=50, blank=True, help_text="e.g., Deep (>50cm), Medium (25-50cm), Shallow (<25cm)")
    soil_drainage = models.CharField(max_length=50, choices=[
        ('excellent', 'Excellent'),
        ('good', 'Good'),
        ('moderate', 'Moderate'),
        ('poor', 'Poor'),
    ], blank=True)
    
    # Crop assessment
    existing_crops = models.TextField(blank=True, help_text="Crops currently growing")
    crop_health = models.CharField(max_length=50, choices=[
        ('excellent', 'Excellent'),
        ('good', 'Good'),
        ('fair', 'Fair'),
        ('poor', 'Poor'),
    ], blank=True)
    pest_issues = models.TextField(blank=True)
    disease_issues = models.TextField(blank=True)
    
    # Water assessment
    water_source_verified = models.CharField(max_length=100, blank=True)
    water_quality = models.CharField(max_length=50, choices=[
        ('excellent', 'Excellent'),
        ('good', 'Good'),
        ('fair', 'Fair'),
        ('poor', 'Poor'),
    ], blank=True)
    irrigation_system = models.CharField(max_length=100, blank=True)
    
    # Photos
    site_photos = models.JSONField(default=list, help_text="List of photo URLs")
    
    # Recommendations
    recommended_crops = models.TextField(blank=True)
    improvement_suggestions = models.TextField(blank=True)
    
    # FIXED: Increased max_length to 25
    overall_suitability = models.CharField(max_length=25, choices=[
        ('highly_suitable', 'Highly Suitable'),
        ('moderately_suitable', 'Moderately Suitable'),
        ('marginally_suitable', 'Marginally Suitable'),
        ('not_suitable', 'Not Suitable'),
    ])
    
    # FIXED: Increased max_length to 25
    recommendation = models.CharField(max_length=25, choices=[
        ('approve', 'Approve'),
        ('approve_with_conditions', 'Approve with Conditions'),
        ('reject', 'Reject'),
        ('further_review', 'Further Review Required'),
    ])
    
    comments = models.TextField()
    
    submitted_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        indexes = [
            models.Index(fields=['visit_date']),
            models.Index(fields=['officer', '-submitted_at']),
        ]
    
    def __str__(self):
        return f"Extension Report for {self.plot.title} by {self.officer}"   


# -----------------------------
# Land Surveyor Role (Q5)
# -----------------------------
class LandSurveyor(models.Model):
    """Land Surveyor role for boundary/GPS verification"""

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='land_surveyor')

    # Professional Details
    license_number = models.CharField(max_length=100, unique=True)
    designation = models.CharField(max_length=100, help_text="e.g., Licensed Land Surveyor")
    station = models.CharField(max_length=200, help_text="Assigned location/office")
    qualifications = models.TextField(help_text="Academic and professional qualifications")
    years_of_experience = models.IntegerField(default=0)

    # Contact
    phone = models.CharField(max_length=20)
    office_address = models.TextField(blank=True)

    # Verification jurisdiction
    assigned_counties = models.JSONField(default=list, help_text="List of counties they can verify")
    max_daily_tasks = models.IntegerField(default=5, help_text="Maximum tasks per day")

    # Status
    is_active = models.BooleanField(default=True)
    verified = models.BooleanField(default=False)
    verified_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='verified_surveyors')
    verified_at = models.DateTimeField(null=True, blank=True)

    # Performance metrics
    total_tasks_completed = models.IntegerField(default=0)
    average_rating = models.FloatField(default=0.0)
    response_time_avg = models.FloatField(default=0, help_text="Average response time in hours")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=['station']),
            models.Index(fields=['is_active']),
        ]

    def __str__(self):
        return f"{self.user.get_full_name()} - {self.designation} ({self.station})"

    @property
    def current_workload(self):
        from .models import VerificationTask
        return VerificationTask.objects.filter(
            assigned_to=self.user,
            status='in_progress'
        ).count()

    @property
    def can_accept_tasks(self):
        return self.current_workload < self.max_daily_tasks and self.is_active


class SurveyorReport(models.Model):
    """Reports submitted by Land Surveyors after site inspections"""

    task = models.OneToOneField('VerificationTask', on_delete=models.CASCADE, related_name='surveyor_report')
    surveyor = models.ForeignKey(LandSurveyor, on_delete=models.CASCADE, related_name='reports')
    plot = models.ForeignKey('Plot', on_delete=models.CASCADE, related_name='surveyor_reports')

    visit_date = models.DateTimeField()
    gps_latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    gps_longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    boundary_confirmed = models.BooleanField(default=False)
    acreage_confirmed = models.BooleanField(default=False)
    encumbrances_found = models.BooleanField(default=False)
    encumbrance_details = models.TextField(blank=True)
    boundary_markers = models.TextField(blank=True, help_text="Describe boundary markers or beacons found on site")
    topography_notes = models.TextField(blank=True, help_text="Slope, terrain, drainage patterns, or obstacles")
    access_road = models.CharField(max_length=200, blank=True, help_text="Describe road access and distance to main road")
    utilities_available = models.TextField(blank=True, help_text="Water, electricity, irrigation, other utilities")
    subdivision_required = models.BooleanField(default=False)
    mutation_required = models.BooleanField(default=False)
    price_realistic = models.BooleanField(default=True)
    suggested_price_per_acre = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    suggested_sale_price = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    price_review_notes = models.TextField(blank=True)
    notes = models.TextField(blank=True)

    recommendation = models.CharField(max_length=25, choices=[
        ('approve', 'Approve'),
        ('approve_with_conditions', 'Approve with Conditions'),
        ('reject', 'Reject'),
        ('further_review', 'Further Review Required'),
    ])

    submitted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=['visit_date']),
            models.Index(fields=['surveyor', '-submitted_at']),
        ]

    def __str__(self):
        return f"Surveyor Report for {self.plot.title} by {self.surveyor}"


class MarketPriceBand(models.Model):
    """Reference pricing band per county + land use."""
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
            models.Index(fields=['county', 'land_type', 'listing_type']),
        ]

    def __str__(self):
        return f"{self.county} {self.land_type} {self.listing_type} band"


class ComparableSale(models.Model):
    """Comparable sales for price basis evidence."""
    plot = models.ForeignKey(Plot, on_delete=models.CASCADE, related_name='comparables')
    title = models.CharField(max_length=200, blank=True)
    county = models.CharField(max_length=100, blank=True)
    price_per_acre = models.DecimalField(max_digits=12, decimal_places=2)
    source = models.CharField(max_length=200, blank=True, help_text="Market source or reference")
    notes = models.TextField(blank=True)

    def __str__(self):
        return f"Comparable {self.price_per_acre} for {self.plot_id}"

# listings/models.py - Add if not present

class PhoneOTP(models.Model):
    """Store OTP for phone verification"""
    user = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True)
    phone = models.CharField(max_length=20)
    otp = models.CharField(max_length=6)
    purpose = models.CharField(max_length=20, choices=[
        ('registration', 'Registration'),
        ('login', 'Login'),
        ('verification', 'Verification')
    ])
    is_verified = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    
    class Meta:
        indexes = [
            models.Index(fields=['phone', 'otp', 'expires_at']),
        ]
    
    def is_valid(self):
        return not self.is_verified and timezone.now() < self.expires_at


class EmailOTP(models.Model):
    """Store OTP for email verification"""
    user = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True)
    email = models.EmailField()
    otp = models.CharField(max_length=6)
    purpose = models.CharField(max_length=20, choices=[
        ('registration', 'Registration'),
        ('login', 'Login'),
        ('verification', 'Verification')
    ])
    is_verified = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()

    class Meta:
        indexes = [
            models.Index(fields=['email', 'otp', 'expires_at']),
        ]

    def is_valid(self):
        return not self.is_verified and timezone.now() < self.expires_at
    
    
