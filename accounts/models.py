from django.conf import settings
from django.db import models


class Profile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    phone = models.CharField(max_length=20, blank=True, null=True)
    phone_verified = models.BooleanField(default=False)
    email_verified = models.BooleanField(default=False)
    has_2fa_enabled = models.BooleanField(default=False)
    address = models.TextField(blank=True, default="")

    ROLE_CHOICES = [
        ("buyer", "Buyer"),
        ("landowner", "Landowner"),
        ("agent", "Agent"),
        ("admin", "Administrator"),
    ]
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default="buyer")

    class Meta:
        db_table = "listings_profile"

    def __str__(self):
        return self.user.username

    @property
    def is_verified_Seller(self):
        return hasattr(self.user, "landownerprofile") and self.user.landownerprofile.verified

    @property
    def is_verified_broker(self):
        return hasattr(self.user, "agent") and self.user.agent.verified

    @property
    def is_landowner(self):
        return hasattr(self.user, "landownerprofile")

    @property
    def is_agent(self):
        return hasattr(self.user, "agent")

    @property
    def is_Seller(self):
        return self.is_landowner

    @property
    def is_broker(self):
        return self.is_agent


class Agent(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)

    phone = models.CharField(
        max_length=20,
        blank=False,
        default="",
        help_text="Kindly provide your Phone Number",
    )
    license_number = models.CharField(
        max_length=100,
        blank=True,
        default="",
        help_text="Professional license number",
    )
    license_doc = models.FileField(
        upload_to="docs/agent_licenses/",
        null=True,
        blank=True,
    )
    verified = models.BooleanField(default=False)

    # Professional & Contact fields
    id_number = models.CharField(max_length=20, help_text="National ID")
    kra_pin = models.FileField(upload_to="docs/agent_kra/", null=True, blank=True)
    practicing_certificate = models.FileField(
        upload_to="docs/practicing_certs/", null=True, blank=True
    )
    good_conduct = models.FileField(upload_to="docs/good_conduct/", null=True, blank=True)
    professional_indemnity = models.FileField(
        upload_to="docs/indemnity/", null=True, blank=True
    )

    response_rate = models.FloatField(
        default=100.0, help_text="Percentage of inquiries responded to"
    )
    average_response_time = models.FloatField(
        default=24, help_text="Average response time in hours"
    )
    rating = models.FloatField(default=5.0)
    review_count = models.IntegerField(default=0)

    total_listings = models.IntegerField(default=0)
    verified_listings = models.IntegerField(default=0)

    contact_preference = models.CharField(
        max_length=20,
        choices=[
            ("email", "Email"),
            ("phone", "Phone"),
            ("whatsapp", "WhatsApp"),
            ("any", "Any"),
        ],
        default="any",
    )
    available_from = models.TimeField(default="09:00")
    available_to = models.TimeField(default="17:00")

    class Meta:
        db_table = "listings_agent"

    def __str__(self):
        return self.user.username

    def update_stats(self):
        self.total_listings = self.plot_set.count()
        self.verified_listings = self.plot_set.filter(
            verification_status__status="verified"
        ).count()
        self.save()


Broker = Agent


class LandownerProfile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)

    national_id = models.FileField(
        upload_to="docs/national_ids/",
        blank=False,
        null=False,
        help_text="Upload a copy of your national ID",
    )
    kra_pin = models.FileField(
        upload_to="docs/kra_pins/",
        blank=False,
        null=False,
        help_text="Upload a copy of your KRA PIN",
    )
    title_deed = models.FileField(
        upload_to="docs/landowner_title_deeds/",
        blank=True,
        null=True,
        help_text="Land title deed proving ownership (required for verification)",
    )
    land_search = models.FileField(
        upload_to="docs/land_searches/",
        blank=True,
        null=True,
        help_text="Official land search certificate (ARDHI/Ardhisasa, validity ~3 months)",
    )
    lcb_consent = models.FileField(
        upload_to="docs/lcb_consents/",
        blank=True,
        null=True,
        help_text="Optional: Upload LCB consent if applicable",
    )

    verified = models.BooleanField(default=False)
    verified_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="landowner_verifications_reviewed",
    )
    rejection_reason = models.TextField(
        blank=True,
        help_text="Reason for rejection if verification failed (allows re-submission)",
    )

    class Meta:
        db_table = "listings_landownerprofile"

    def __str__(self):
        return f"LandownerProfile: {self.user.username}"
