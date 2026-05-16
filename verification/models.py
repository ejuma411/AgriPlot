from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.contrib.postgres.fields import ArrayField
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class VerificationDocument(models.Model):
    DOC_TYPE_CHOICES = [
        ("title_deed", "Title Deed"),
        ("official_search", "Official Search Certificate"),
        ("landowner_id", "Landowner National ID"),
        ("kra_pin", "KRA PIN Certificate"),
        ("survey_map", "Survey Map / Mutation Form"),
        ("rates_clearance", "Land Rates Clearance"),
        ("rent_clearance", "Land Rent Clearance"),
        ("spousal_consent", "Spousal Consent"),
        ("survey_plan", "Survey Plan"),
        ("lcb_consent", "LCB Consent"),
        ("plupa1_form", "PLUPA 1 / PPA 1"),
        ("consent_to_transfer", "Consent to Transfer"),
    ]

    plot = models.ForeignKey(
        "listings.Plot", on_delete=models.CASCADE, related_name="verification_docs"
    )
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True
    )
    doc_type = models.CharField(max_length=30, choices=DOC_TYPE_CHOICES)
    file = models.FileField(upload_to="verification_docs/")
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "listings_verificationdocument"

    def __str__(self):
        return f"{self.plot.title} — {self.get_doc_type_display()}"


class TitleSearchResult(models.Model):
    plot = models.OneToOneField(
        "listings.Plot", on_delete=models.CASCADE, related_name="search_result"
    )
    search_platform = models.CharField(max_length=50)
    official_owner = models.CharField(max_length=200)
    parcel_number = models.CharField(max_length=100)
    encumbrances = models.TextField(null=True, blank=True)
    lease_status = models.CharField(max_length=100, null=True, blank=True)
    search_date = models.DateField(null=True, blank=True)
    raw_response_file = models.FileField(
        upload_to="search_responses/", null=True, blank=True
    )
    verified = models.BooleanField(default=False)
    notes = models.TextField(null=True, blank=True)

    class Meta:
        db_table = "listings_titlesearchresult"

    def __str__(self):
        return f"SearchResult — {self.plot.title} ({self.search_platform})"


class VerificationStatus(models.Model):
    STAGES = [
        ("document_uploaded", "Documents Uploaded"),
        ("api_verification_started", "API Verification Started"),
        ("title_search_completed", "Title Search Completed"),
        ("owner_verified", "Owner Identity Verified"),
        ("encumbrance_check", "Encumbrance Check"),
        ("physical_location_verified", "Physical Location Verified"),
        ("admin_review", "Under Admin Review"),
        ("approved", "Approved"),
        ("rejected", "Rejected"),
    ]

    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveIntegerField()
    content_object = GenericForeignKey("content_type", "object_id")

    current_stage = models.CharField(
        max_length=50, choices=STAGES, default="document_uploaded"
    )
    stage_details = models.JSONField(default=dict, blank=True)
    is_complete = models.BooleanField(default=False)

    api_responses = models.JSONField(default=list, blank=True)
    search_reference = models.CharField(max_length=100, blank=True)
    search_fee_paid = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True
    )

    document_uploaded_at = models.DateTimeField(null=True, blank=True)
    api_started_at = models.DateTimeField(null=True, blank=True)
    title_search_at = models.DateTimeField(null=True, blank=True)
    owner_verified_at = models.DateTimeField(null=True, blank=True)
    encumbrance_check_at = models.DateTimeField(null=True, blank=True)
    physical_location_verified_at = models.DateTimeField(null=True, blank=True)
    admin_review_at = models.DateTimeField(null=True, blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    rejected_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "listings_verificationstatus"
        unique_together = [["content_type", "object_id"]]
        verbose_name_plural="Verification Statuses"

    def __str__(self):
        model_class = self.content_type.model_class() if self.content_type_id else None
        if not model_class:
            return f"Verification (missing model) - {self.get_current_stage_display()}"

        try:
            content_object = model_class._base_manager.filter(pk=self.object_id).first()
        except Exception:
            content_object = None

        if not content_object:
            return f"Verification for missing {self.content_type} #{self.object_id} - {self.get_current_stage_display()}"

        return f"Verification for {content_object} - {self.get_current_stage_display()}"

    def update_stage(self, stage, details=None):
        original_stage = self.current_stage
        self.current_stage = stage
        if details:
            self.stage_details[stage] = details

        stage_timestamp_map = {
            "document_uploaded": "document_uploaded_at",
            "api_verification_started": "api_started_at",
            "title_search_completed": "title_search_at",
            "owner_verified": "owner_verified_at",
            "encumbrance_check": "encumbrance_check_at",
            "physical_location_verified": "physical_location_verified_at",
            "admin_review": "admin_review_at",
            "approved": "approved_at",
            "rejected": "rejected_at",
        }
        timestamp_field = stage_timestamp_map.get(stage)
        if timestamp_field and hasattr(self, timestamp_field):
            setattr(self, timestamp_field, timezone.now())

        if stage == "approved":
            self.is_complete = True

        self.save()

        try:
            if original_stage != stage and self.content_type.model == "plot":
                if stage not in ("approved", "rejected"):
                    from notifications.notification_service import NotificationService

                    NotificationService.notify_plot_stage(
                        self.content_object, stage, details
                    )
        except Exception:
            pass

    def trigger_ardhisasa_check(self):
        if self.current_stage == "document_uploaded":
            self.update_stage("api_verification_started")

    def add_api_response(self, response_data):
        self.api_responses.append(
            {"timestamp": timezone.now().isoformat(), "data": response_data}
        )
        self.save()

    @property
    def progress_percentage(self):
        stages = [stage[0] for stage in self.STAGES]
        if self.current_stage in ("approved", "rejected"):
            return 100
        if self.current_stage in stages:
            index = stages.index(self.current_stage)
            total_stages = len(stages)
            return int((index + 1) / total_stages * 100)
        return 0

    @property
    def estimated_completion(self):
        if self.current_stage == "approved":
            return "Verification complete"
        if self.current_stage == "rejected":
            return "Verification rejected"
        if self.current_stage == "admin_review":
            return "Awaiting admin review (usually within 24 hours)"
        if self.current_stage in [
            "title_search_completed",
            "owner_verified",
            "encumbrance_check",
        ]:
            return "API verification in progress (typically 2-3 business days)"
        return "Verification in progress"


class PlotVerification(models.Model):
    plot = models.OneToOneField(
        "listings.Plot", on_delete=models.CASCADE, related_name="verification"
    )
    owner_verified = models.ForeignKey(
        "verification.VerificationStatus", on_delete=models.SET_NULL, null=True
    )

    STAGES = [
        ("submitted", "Submitted for Verification"),
        ("document_check", "Document Check"),
        ("title_search", "Title Search with Ardhisasa"),
        ("physical_verification", "Physical Verification"),
        ("admin_approval", "Admin Approval"),
        ("approved", "Approved for Listing"),
        ("rejected", "Rejected"),
    ]

    current_stage = models.CharField(max_length=50, choices=STAGES, default="submitted")
    stage_details = models.JSONField(default=dict)
    api_responses = models.JSONField(default=list)

    submitted_at = models.DateTimeField(auto_now_add=True)
    title_search_at = models.DateTimeField(null=True, blank=True)
    admin_review_at = models.DateTimeField(null=True, blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "listings_plotverification"

    def __str__(self):
        return f"Verification for Plot {self.plot.id}"


class SoilReport(models.Model):
    VERIFICATION_CHOICES = [
        ("draft", "Draft"),
        ("unverified", "Unverified"),
        ("lab_verified", "Lab Verified"),
        ("rejected", "Rejected"),
    ]

    plot = models.ForeignKey(
        "listings.Plot", on_delete=models.CASCADE, related_name="soil_reports"
    )
    pH = models.DecimalField(max_digits=4, decimal_places=2, null=True, blank=True)
    organic_matter_pct = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True
    )
    nitrogen_mgkg = models.DecimalField(
        max_digits=7, decimal_places=2, null=True, blank=True
    )
    phosphorus_mgkg = models.DecimalField(
        max_digits=7, decimal_places=2, null=True, blank=True
    )
    potassium_mgkg = models.DecimalField(
        max_digits=7, decimal_places=2, null=True, blank=True
    )
    sand_pct = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    silt_pct = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    clay_pct = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    ec_salinity = models.DecimalField(
        max_digits=6, decimal_places=3, null=True, blank=True
    )
    lab_id = models.CharField(max_length=100, blank=True, default="")
    sample_date = models.DateField(null=True, blank=True)
    geo_lat = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    geo_lng = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    report_file = models.FileField(
        upload_to="documents/soil_reports/", null=True, blank=True
    )
    verification_status = models.CharField(
        max_length=20, choices=VERIFICATION_CHOICES, default="draft"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "listings_soilreport"
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["pH"]),
            models.Index(fields=["organic_matter_pct"]),
        ]

    def __str__(self):
        return f"SoilReport {self.id} — {self.plot.title} ({self.verification_status})"


class VerificationTask(models.Model):
    TASK_TYPE_CHOICES = [
        ("registry_search", "Registry Search"),
        ("document_review", "Document Review"),
        ("extension_review", "Extension Officer Review"),
        ("surveyor_inspection", "Land Surveyor Inspection"),
    ]
    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("in_progress", "In Progress"),
        ("completed", "Completed"),
    ]
    CONFIRMATION_CHOICES = [
        ("pending", "Pending"),
        ("confirmed", "Confirmed"),
        ("declined", "Declined"),
        ("expired", "Expired"),
    ]
    plot = models.ForeignKey(
        "listings.Plot", on_delete=models.CASCADE, related_name="verification_tasks"
    )
    verification_type = models.CharField(max_length=30, choices=TASK_TYPE_CHOICES)
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_verification_tasks",
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")
    assigned_at = models.DateTimeField(auto_now_add=True)
    confirm_by = models.DateTimeField(null=True, blank=True)
    confirmed_at = models.DateTimeField(null=True, blank=True)
    confirmation_status = models.CharField(
        max_length=20, choices=CONFIRMATION_CHOICES, default="pending"
    )
    benefit_amount = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True
    )
    benefit_currency = models.CharField(max_length=10, default="KES")
    benefit_status = models.CharField(
        max_length=20,
        choices=[
            ("not_applicable", "Not Applicable"),
            ("pending", "Pending"),
            ("earned", "Earned"),
            ("paid", "Paid"),
        ],
        default="pending",
    )
    benefit_notes = models.TextField(blank=True)
    benefit_recorded_at = models.DateTimeField(null=True, blank=True)
    deadline_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)
    approved = models.BooleanField(null=True, blank=True)
    review_metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "listings_verificationtask"
        ordering = ["-assigned_at"]

    def __str__(self):
        return (
            f"{self.get_verification_type_display()} — Plot {self.plot_id} ({self.status})"
        )

    @property
    def has_field_benefit(self):
        return self.verification_type in {"extension_review", "surveyor_inspection"}


class VerificationLog(models.Model):
    plot = models.ForeignKey(
        "listings.Plot", on_delete=models.CASCADE, related_name="verification_logs"
    )
    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="verification_actions",
    )
    verification_type = models.CharField(max_length=50)
    comment = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "listings_verificationlog"
        ordering = ["-created_at"]

    def __str__(self):
        return f"Plot {self.plot_id} — {self.verification_type} by {self.verified_by_id}"


class DocumentVerification(models.Model):
    DOC_TYPE_CHOICES = [
        ("national_id", "National ID"),
        ("kra_pin", "KRA PIN"),
        ("title_deed", "Title Deed"),
        ("official_search", "Official Search"),
    ]
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="document_verifications",
    )
    plot = models.ForeignKey(
        "listings.Plot",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="document_verifications",
    )
    task = models.ForeignKey(
        "verification.VerificationTask",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="document_verifications",
    )
    document_type = models.CharField(max_length=30, choices=DOC_TYPE_CHOICES)
    document_file = models.FileField(upload_to="verification_docs/", null=True, blank=True)

    is_readable = models.BooleanField(null=True, blank=True)
    is_not_expired = models.BooleanField(null=True, blank=True)
    name_matches_user = models.BooleanField(null=True, blank=True)
    all_names_match = models.BooleanField(null=True, blank=True)

    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="documents_verified",
    )
    verified_at = models.DateTimeField(null=True, blank=True)
    verification_notes = models.TextField(blank=True)
    approved = models.BooleanField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "listings_documentverification"
        ordering = ["-created_at"]
        unique_together = [["user", "document_type", "plot"]]

    @classmethod
    def verify_document(cls, plot, doc_type, reviewer, approved, notes, task=None):
        doc_file = None
        if doc_type == "national_id":
            doc_file = getattr(plot, "landowner_id_doc", None)
        elif doc_type == "kra_pin":
            doc_file = getattr(plot, "kra_pin", None)
        elif doc_type == "title_deed":
            doc_file = getattr(plot, "title_deed", None)
        elif doc_type == "official_search":
            doc_file = getattr(plot, "official_search", None)

        return cls.objects.create(
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
            approved=approved,
        )

    def __str__(self):
        return f"{self.user.username} — {self.get_document_type_display()} ({self.approved})"


class ExtensionOfficer(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="extension_officer"
    )
    employee_id = models.CharField(
        max_length=50, unique=True, help_text="Government/Institution employee ID"
    )
    designation = models.CharField(
        max_length=100, help_text="e.g., Agricultural Officer, Livestock Officer"
    )
    department = models.CharField(max_length=100, default="Ministry of Agriculture")
    station = models.CharField(max_length=200, help_text="Assigned location/office")

    qualifications = models.TextField(help_text="Academic and professional qualifications")
    specializations = models.CharField(max_length=300, blank=True)
    years_of_experience = models.IntegerField(default=0)

    phone = models.CharField(max_length=20)
    office_address = models.TextField(blank=True)

    assigned_counties = ArrayField(
        models.CharField(max_length=100),
        default=list,
        blank=True,
        help_text="List of counties they can verify",
    )
    max_daily_tasks = models.IntegerField(default=5)

    is_active = models.BooleanField(default=True)
    verified = models.BooleanField(default=False)
    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="verified_officers",
    )
    verified_at = models.DateTimeField(null=True, blank=True)

    total_tasks_completed = models.IntegerField(default=0)
    average_rating = models.FloatField(default=0.0)
    response_time_avg = models.FloatField(default=0, help_text="Average response time in hours")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "listings_extensionofficer"
        indexes = [
            models.Index(fields=["station"]),
            models.Index(fields=["is_active"]),
        ]

    def __str__(self):
        return f"{self.user.get_full_name()} - {self.designation} ({self.station})"

    @property
    def current_workload(self):
        return VerificationTask.objects.filter(
            assigned_to=self.user, status="in_progress"
        ).count()

    @property
    def can_accept_tasks(self):
        return self.current_workload < self.max_daily_tasks and self.is_active

    @property
    def earned_benefits_total(self):
        return (
            VerificationTask.objects.filter(
                assigned_to=self.user, benefit_status__in=["earned", "paid"]
            ).aggregate(total=models.Sum("benefit_amount"))["total"]
            or 0
        )


class ExtensionReport(models.Model):
    SOIL_CLASSIFICATION_CHOICES = [
        ("Red Volcanic", "Red Volcanic (Best for Coffee/Tea/Veggies)"),
        ("Black Cotton", "Black Cotton (High water retention, needs special management)"),
        ("Sandy Soil", "Sandy Soil (Well-drained, good for specific tubers)"),
        ("Loam", "Loam Soil (Rich, versatile agricultural soil)"),
        ("Alluvial Soil", "Alluvial Soil (Riverbed silt, highly fertile)"),
    ]

    CURRENT_LAND_USE_CHOICES = [
        ("Virgin/Uncultivated", "Virgin/Uncultivated"),
        ("Active Farming", "Active Farming"),
        ("Idle/Fallow", "Idle/Fallow"),
        ("Exhausted", "Exhausted"),
    ]

    IRRIGATION_VIABILITY_CHOICES = [
        ("high", "High Viability"),
        ("moderate", "Moderate Viability"),
        ("not_viable", "Not Viable"),
    ]

    task = models.OneToOneField(
        "verification.VerificationTask",
        on_delete=models.CASCADE,
        related_name="extension_report",
    )
    officer = models.ForeignKey(
        "verification.ExtensionOfficer", on_delete=models.CASCADE, related_name="reports"
    )
    plot = models.ForeignKey(
        "listings.Plot", on_delete=models.CASCADE, related_name="extension_reports"
    )

    visit_date = models.DateTimeField()
    weather_conditions = models.CharField(max_length=100, blank=True)

    soil_ph_verified = models.FloatField(null=True, blank=True)
    soil_ph = models.DecimalField(
        max_digits=4, decimal_places=2, null=True, blank=True, help_text="Measured soil pH"
    )
    soil_classification = models.CharField(max_length=50, blank=True)
    soil_texture = models.CharField(
        max_length=50,
        choices=[
            ("sandy", "Sandy"),
            ("loamy", "Loamy"),
            ("clay", "Clay"),
            ("silty", "Silty"),
            ("peaty", "Peaty"),
        ],
        blank=True,
    )
    soil_depth = models.CharField(max_length=50, blank=True)
    soil_drainage = models.CharField(
        max_length=50,
        choices=[
            ("excellent", "Excellent"),
            ("good", "Good"),
            ("moderate", "Moderate"),
            ("poor", "Poor"),
        ],
        blank=True,
    )
    topography = models.CharField(
        max_length=20,
        choices=[
            ("flat", "Flat / Level"),
            ("gentle", "Gentle Slope"),
            ("steep", "Steep Slope"),
            ("valley", "Valley / Bottom Land"),
        ],
        blank=True,
    )

    current_land_use = models.TextField(blank=True)
    existing_crops = models.TextField(blank=True)
    crop_health = models.CharField(
        max_length=50,
        choices=[
            ("excellent", "Excellent"),
            ("good", "Good"),
            ("fair", "Fair"),
            ("poor", "Poor"),
        ],
        blank=True,
    )
    pest_issues = models.TextField(blank=True)
    disease_issues = models.TextField(blank=True)

    water_source_verified = models.CharField(max_length=100, blank=True)
    water_sources_available = models.TextField(
        blank=True,
        help_text="Comma-separated verified water sources, e.g. Borehole, River, Rain-fed only.",
    )
    distance_to_tarmac_m = models.PositiveIntegerField(null=True, blank=True)
    distance_to_market_m = models.PositiveIntegerField(null=True, blank=True)
    water_quality = models.CharField(
        max_length=50,
        choices=[
            ("excellent", "Excellent"),
            ("good", "Good"),
            ("fair", "Fair"),
            ("poor", "Poor"),
        ],
        blank=True,
    )
    irrigation_system = models.CharField(max_length=100, blank=True)
    irrigation_viability = models.CharField(
        max_length=20,
        choices=IRRIGATION_VIABILITY_CHOICES,
        blank=True,
    )
    power_access = models.CharField(
        max_length=50,
        choices=[
            ("onsite", "On-site"),
            ("within_100m", "Within 100m"),
            ("offgrid", "Off-grid / Solar"),
            ("none", "Not Available"),
            ("unknown", "Unknown"),
        ],
        default="unknown",
    )

    zoning_status = models.CharField(
        max_length=50,
        choices=[
            ("agricultural", "Agricultural"),
            ("residential", "Residential"),
            ("commercial", "Commercial"),
            ("mixed_use", "Mixed Use"),
            ("unknown", "Unknown"),
        ],
        default="unknown",
    )
    lcb_approval_potential = models.CharField(
        max_length=50,
        choices=[
            ("likely", "Likely"),
            ("uncertain", "Uncertain"),
            ("unlikely", "Unlikely"),
            ("not_applicable", "Not Applicable"),
        ],
        default="uncertain",
    )
    lcb_zone = models.BooleanField(default=False)
    project_feasibility_note = models.TextField(blank=True)
    soil_analysis_notes = models.TextField(blank=True)
    soil_analysis_report = models.FileField(
        upload_to="documents/soil_analysis_reports/",
        null=True,
        blank=True,
        help_text="Official soil analysis report from the field or lab.",
    )
    topography_summary = models.TextField(blank=True)

    site_photos = models.JSONField(default=list)

    recommended_crops = models.TextField(blank=True)
    improvement_suggestions = models.TextField(blank=True)

    overall_suitability = models.CharField(
        max_length=25,
        choices=[
            ("highly_suitable", "Highly Suitable"),
            ("moderately_suitable", "Moderately Suitable"),
            ("marginally_suitable", "Marginally Suitable"),
            ("not_suitable", "Not Suitable"),
        ],
    )
    recommendation = models.CharField(
        max_length=25,
        choices=[
            ("approve", "Approve"),
            ("approve_with_conditions", "Approve with Conditions"),
            ("reject", "Reject"),
            ("further_review", "Further Review Required"),
        ],
    )
    comments = models.TextField()
    submitted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "listings_extensionreport"
        indexes = [
            models.Index(fields=["visit_date"]),
            models.Index(fields=["officer", "-submitted_at"]),
        ]

    def __str__(self):
        return f"Extension Report for {self.plot.title} by {self.officer}"

    @property
    def soil_classification_display(self):
        mapping = dict(self.SOIL_CLASSIFICATION_CHOICES)
        return mapping.get(self.soil_classification, self.soil_classification)

    @property
    def current_land_use_display(self):
        mapping = dict(self.CURRENT_LAND_USE_CHOICES)
        return mapping.get(self.current_land_use, self.current_land_use)


class LandSurveyor(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="land_surveyor"
    )

    license_number = models.CharField(max_length=100, unique=True)
    designation = models.CharField(max_length=100)
    station = models.CharField(max_length=200)
    qualifications = models.TextField()
    years_of_experience = models.IntegerField(default=0)

    phone = models.CharField(max_length=20)
    office_address = models.TextField(blank=True)
    practicing_certificate_expiry = models.DateField(null=True, blank=True)

    assigned_counties = ArrayField(
        models.CharField(max_length=100),
        default=list,
        blank=True,
        help_text="List of counties they can verify",
    )
    max_daily_tasks = models.IntegerField(default=5)

    is_active = models.BooleanField(default=True)
    verified = models.BooleanField(default=False)
    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="verified_surveyors",
    )
    verified_at = models.DateTimeField(null=True, blank=True)

    total_tasks_completed = models.IntegerField(default=0)
    average_rating = models.FloatField(default=0.0)
    response_time_avg = models.FloatField(default=0, help_text="Average response time in hours")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "listings_landsurveyor"
        indexes = [
            models.Index(fields=["station"]),
            models.Index(fields=["is_active"]),
        ]

    def __str__(self):
        return f"{self.user.get_full_name()} - {self.designation} ({self.station})"

    @property
    def current_workload(self):
        return VerificationTask.objects.filter(
            assigned_to=self.user, status="in_progress"
        ).count()

    @property
    def can_accept_tasks(self):
        if self.practicing_certificate_expiry and self.practicing_certificate_expiry < timezone.localdate():
            return False
        return self.current_workload < self.max_daily_tasks and self.is_active

    @property
    def earned_benefits_total(self):
        return (
            VerificationTask.objects.filter(
                assigned_to=self.user, benefit_status__in=["earned", "paid"]
            ).aggregate(total=models.Sum("benefit_amount"))["total"]
            or 0
        )


class SurveyorReport(models.Model):
    REFERENCE_DOCUMENT_TYPE_CHOICES = [
        ("rim", "Registry Index Map (RIM)"),
        ("mutation", "Mutation Form"),
        ("share_certificate_map", "Share Certificate Map"),
    ]

    task = models.OneToOneField(
        "verification.VerificationTask",
        on_delete=models.CASCADE,
        related_name="surveyor_report",
    )
    surveyor = models.ForeignKey(
        "verification.LandSurveyor", on_delete=models.CASCADE, related_name="reports"
    )
    plot = models.ForeignKey(
        "listings.Plot", on_delete=models.CASCADE, related_name="surveyor_reports"
    )

    visit_date = models.DateTimeField()
    gps_latitude = models.DecimalField(
        max_digits=9, decimal_places=6, null=True, blank=True
    )
    gps_longitude = models.DecimalField(
        max_digits=9, decimal_places=6, null=True, blank=True
    )
    boundary_confirmed = models.BooleanField(default=False)
    acreage_confirmed = models.BooleanField(default=False)
    encumbrances_found = models.BooleanField(default=False)
    encumbrance_details = models.TextField(blank=True)
    boundary_markers = models.TextField(blank=True)
    beacon_status = models.CharField(
        max_length=50,
        choices=[
            ("all_present_and_intact", "All beacons present and intact"),
            ("beacons_missing", "Some beacons missing (re-establishment required)"),
            ("displaced", "Beacons displaced or tampered with"),
            ("boundary_dispute", "Boundary dispute noted with adjacent plots"),
        ],
        blank=True,
    )
    official_document_reference = models.CharField(
        max_length=30,
        choices=REFERENCE_DOCUMENT_TYPE_CHOICES,
        blank=True,
    )
    reference_number = models.CharField(max_length=100, blank=True)
    beacon_certificate = models.FileField(
        upload_to="documents/beacon_certificates/", null=True, blank=True
    )
    mutation_form = models.FileField(
        upload_to="documents/mutation_forms/", null=True, blank=True
    )
    rim_map_sheet_no = models.CharField(max_length=100, blank=True)
    ground_acreage = models.DecimalField(
        max_digits=10, decimal_places=4, null=True, blank=True
    )
    deed_area = models.DecimalField(max_digits=10, decimal_places=4, null=True, blank=True)
    variance_flagged = models.BooleanField(default=False)
    boundary_data_file = models.FileField(
        upload_to="documents/boundary_data/",
        null=True,
        blank=True,
        help_text="Upload .geojson, .kml, or .shp field boundary data.",
    )
    boundary_report = models.FileField(
        upload_to="documents/boundary_reports/", null=True, blank=True
    )
    signed_survey_plan = models.FileField(
        upload_to="documents/signed_survey_plans/", null=True, blank=True
    )
    encroachment_found = models.BooleanField(default=False)
    encroachment_details = models.TextField(blank=True)
    lsb_license_number = models.CharField(max_length=100, blank=True)
    surveyor_license_number = models.CharField(max_length=100, blank=True)
    topography_notes = models.TextField(blank=True)
    access_road = models.CharField(max_length=200, blank=True)
    utilities_available = models.TextField(blank=True)
    subdivision_required = models.BooleanField(default=False)
    mutation_required = models.BooleanField(default=False)
    price_realistic = models.BooleanField(default=True)
    suggested_price_per_acre = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True
    )
    suggested_sale_price = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True
    )
    price_review_notes = models.TextField(blank=True)
    surveyor_declaration = models.BooleanField(default=False)
    notes = models.TextField(blank=True)

    recommendation = models.CharField(
        max_length=25,
        choices=[
            ("approve", "Approve"),
            ("approve_with_conditions", "Approve with Conditions"),
            ("reject", "Reject"),
            ("further_review", "Further Review Required"),
        ],
    )
    submitted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "listings_surveyorreport"
        indexes = [
            models.Index(fields=["visit_date"]),
            models.Index(fields=["surveyor", "-submitted_at"]),
        ]

    def __str__(self):
        return f"Surveyor Report for {self.plot.title} by {self.surveyor}"

    @property
    def beacon_status_list(self):
        if not self.beacon_status:
            return []
        mapping = dict(self._meta.get_field("beacon_status").choices)
        values = [value.strip() for value in self.beacon_status.split(",") if value.strip()]
        return [mapping.get(value, value) for value in values]

    @property
    def beacon_status_display(self):
        return ", ".join(self.beacon_status_list)
