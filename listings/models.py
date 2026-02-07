from django.db import models
from django.contrib.auth.models import User

# -----------------------------
# User & Role Models
# -----------------------------

class Profile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    phone = models.CharField(max_length=20, blank=True, default="")
    address = models.TextField(blank=True, default="")
    
    # Track user roles
    is_verified_seller = models.BooleanField(default=False)
    is_verified_broker = models.BooleanField(default=False)

    def __str__(self):
        return self.user.username
    
    @property
    def is_seller(self):
        return hasattr(self.user, 'sellerprofile')
    
    @property
    def is_broker(self):
        return hasattr(self.user, 'broker')

class Broker(models.Model):
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

    # Optional upload — not required for listing, can be added later
    license_doc = models.FileField(
        upload_to="docs/broker_licenses/",
        null=True,
        blank=True
    )

    # Whether an admin has verified this broker’s identity/license
    verified = models.BooleanField(default=False)

    def __str__(self):
        return self.user.username
    
    # Contact and rating fields
    phone_number = models.CharField(max_length=15, blank=True, null=True)
    response_rate = models.FloatField(default=100.0, help_text="Percentage of inquiries responded to")
    average_response_time = models.FloatField(default=24, help_text="Average response time in hours")
    rating = models.FloatField(default=5.0)
    review_count = models.IntegerField(default=0)
    
    # Stats
    total_listings = models.IntegerField(default=0)
    verified_listings = models.IntegerField(default=0)
    
    # Contact preferences
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
    
    # Availability
    available_from = models.TimeField(default='09:00')
    available_to = models.TimeField(default='17:00')
    
    # Methods
    def update_stats(self):
        """Update broker statistics"""
        self.total_listings = self.plot_set.count()
        self.verified_listings = self.plot_set.filter(
            verification_status__status='verified'
        ).count()
        self.save()


class SellerProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    
    national_id = models.FileField(
        upload_to="docs/national_ids/",
        blank=True,  # Was: blank=True (correct)
        null=True,
        help_text="Upload a copy of the seller's national ID"
    )
    
    kra_pin = models.FileField(
        upload_to="docs/kra_pins/",
        blank=True,  # Was: blank=True (correct)
        null=True,
        help_text="Upload a copy of the seller's KRA PIN"
    )
    
    title_deed = models.FileField(
        upload_to="docs/title_deeds/",
        blank=True,  # CHANGE: from blank=False to blank=True
        null=True,   # Should also be null=True for optional fields
        help_text="Upload a copy of the title deed"
    )
    
    land_search = models.FileField(
        upload_to="docs/land_searches/",
        blank=True,  # CHANGE: from blank=False to blank=True
        null=True,   # Should also be null=True for optional fields
        help_text="Upload the official land search certificate"
    )
    
    lcb_consent = models.FileField(
        upload_to="docs/lcb_consents/",
        blank=True,  # Already correct
        null=True,
        help_text="Optional: Upload LCB consent if applicable"
    )
    
    verified = models.BooleanField(default=False)
    
    def __str__(self):
        return f"SellerProfile: {self.user.username}"

# -----------------------------
# Plot / Listing Model
# -----------------------------
class Plot(models.Model):
    broker = models.ForeignKey(Broker, on_delete=models.CASCADE)
    title = models.CharField(max_length=200)
    location = models.CharField(max_length=300)
    price = models.DecimalField(max_digits=12, decimal_places=2)
    area = models.FloatField(help_text="In acres or hectares")

    # Agricultural Fields
    soil_type = models.CharField(max_length=100)
    ph_level = models.FloatField(null=True, blank=True)
    crop_suitability = models.CharField(max_length=200)

    # PRIMARY DOCUMENTS - on Plot model
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
    
    # VERIFICATION DOCUMENTS - Added to Plot model
    official_search = models.FileField(
        upload_to="documents/official_searches/",
        null=True,
        blank=True,
        help_text="Official land search certificate"
    )
    seller_id = models.FileField(
        upload_to="documents/seller_ids/",
        null=True,
        blank=True,
        help_text="Seller's national ID"
    )
    kra_pin = models.FileField(
        upload_to="documents/kra_pins/",
        null=True,
        blank=True,
        help_text="KRA PIN certificate"
    )
    
    # Additional metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.title

    @property
    def images_list(self):
        """Return all images for this plot"""
        return self.images.all()
    
    @property
    def has_all_documents(self):
        """Check if plot has all required documents"""
        required_docs = ['title_deed', 'official_search', 'seller_id', 'kra_pin']
        for doc_field in required_docs:
            if not getattr(self, doc_field):
                return False
        return True
    
class PlotImage(models.Model):
    plot = models.ForeignKey('Plot', on_delete=models.CASCADE, related_name='images_list')
    image = models.ImageField(upload_to='plot_images/')
    uploaded_at = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        return f"Image for {self.plot.title}"
    
# -----------------------------
# Document Uploads for Verification
# -----------------------------

class VerificationDocument(models.Model):
    DOC_TYPE_CHOICES = [
        ('title_deed', "Title Deed"),
        ('official_search', "Official Search Certificate"),
        ('seller_id', "Seller ID"),
        ('kra_pin', "KRA PIN Certificate"),
        ('survey_plan', "Survey Plan"),
        ('rates_clearance', "Land Rates Clearance"),
        ('lcb_consent', "LCB Consent (if required)"),
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
    search_platform = models.CharField(max_length=50)  # e.g. "Ardhisasa", "eCitizen", "Manual"
    official_owner = models.CharField(max_length=200)
    parcel_number = models.CharField(max_length=100)
    encumbrances = models.TextField(null=True, blank=True)  # caveats, charges, disputes found
    lease_status = models.CharField(max_length=100, null=True, blank=True)
    search_date = models.DateField(null=True, blank=True)
    raw_response_file = models.FileField(upload_to="search_responses/", null=True, blank=True)
    verified = models.BooleanField(default=False)  # Whether the official search result matches the plot data
    notes = models.TextField(null=True, blank=True)

    def __str__(self):
        return f"SearchResult — {self.plot.title} ({self.search_platform})"


# -----------------------------
# Plot Verification Workflow Status
# -----------------------------

class PlotVerificationStatus(models.Model):
    STATUS_CHOICES = [
        ('pending', "Pending Verification"),
        ('in_review', "In Review"),
        ('verified', "Verified"),
        ('rejected', "Rejected"),
    ]

    plot = models.OneToOneField(Plot, on_delete=models.CASCADE, related_name="verification_status")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")
    reviewed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="verified_plots")
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_notes = models.TextField(null=True, blank=True)

    def __str__(self):
        return f"{self.plot.title} — {self.status}"


# UserInterest model
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
    notes = models.TextField(blank=True, help_text="Internal notes from broker")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-created_at']
        unique_together = ['user', 'plot']  # Prevent duplicate interests
    
    def __str__(self):
        return f"{self.user.username} → {self.plot.title}"
    
# MESSAGING MODEL
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
    broker = models.ForeignKey(Broker, on_delete=models.CASCADE, related_name='contact_requests')
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
    
    def __str__(self):
        return f"{self.user.username} → {self.broker.user.username} ({self.request_type})"