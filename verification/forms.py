import os

from django import forms

from crops.models import CropProfile
from verification.models import (
    ExtensionOfficer,
    ExtensionReport,
    LandSurveyor,
    SurveyorReport,
)


MAX_UPLOAD_MB = 20
ALLOWED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png"}
ALLOWED_DOC_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png"}
ALLOWED_BOUNDARY_EXTENSIONS = {".geojson", ".kml", ".shp"}


def _validate_uploaded_file(field_name, file_obj, allowed_extensions, max_upload_mb=MAX_UPLOAD_MB):
    if not file_obj:
        return
    max_size = max_upload_mb * 1024 * 1024
    if hasattr(file_obj, "size") and file_obj.size > max_size:
        raise forms.ValidationError(
            f"{field_name} must be less than {max_upload_mb}MB."
        )
    if hasattr(file_obj, "name"):
        ext = os.path.splitext(file_obj.name)[1].lower()
        if ext not in allowed_extensions:
            allowed_labels = ", ".join(ext.upper().lstrip(".") for ext in sorted(allowed_extensions))
            raise forms.ValidationError(
                f"{field_name} must be one of: {allowed_labels}."
            )


def _validate_multiple_files(field_name, files, allowed_extensions, max_upload_mb=MAX_UPLOAD_MB):
    for file_obj in files or []:
        _validate_uploaded_file(field_name, file_obj, allowed_extensions, max_upload_mb=max_upload_mb)


class AccountLinkedRoleRequestForm(forms.ModelForm):
    username = forms.CharField(
        required=False,
        disabled=True,
        widget=forms.TextInput(attrs={"class": "form-control", "readonly": "readonly"}),
    )
    email = forms.EmailField(
        required=False,
        disabled=True,
        widget=forms.EmailInput(attrs={"class": "form-control", "readonly": "readonly"}),
    )
    account_phone = forms.CharField(
        required=False,
        disabled=True,
        label="Phone",
        widget=forms.TextInput(attrs={"class": "form-control", "readonly": "readonly"}),
    )

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop("user", None)
        super().__init__(*args, **kwargs)

        source_user = self.user or getattr(getattr(self, "instance", None), "user", None)
        if source_user is not None:
            self.fields["username"].initial = source_user.username
            self.fields["email"].initial = source_user.email
            profile = getattr(source_user, "profile", None)
            self.fields["account_phone"].initial = getattr(profile, "phone", "") or ""


class ExtensionOfficerProfileForm(AccountLinkedRoleRequestForm):
    """Form for requesting extension officer role."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from listings.kenya_data import KENYA_COUNTIES

        self.fields["assigned_counties"].choices = [(c, c) for c in KENYA_COUNTIES]
        self.fields["assigned_counties"].required = True
        self.fields["assigned_counties"].help_text = "Select one or more counties you can verify."
        self.fields["max_daily_tasks"].required = True
        self.fields["years_of_experience"].required = True
        self.order_fields(
            [
                "username",
                "email",
                "account_phone",
                "employee_id",
                "designation",
                "department",
                "station",
                "qualifications",
                "specializations",
                "years_of_experience",
                "office_address",
                "assigned_counties",
                "max_daily_tasks",
            ]
        )
        for field in self.fields.values():
            if not isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs.setdefault("class", "form-control")
            if field.required:
                field.widget.attrs["required"] = "required"

    class Meta:
        model = ExtensionOfficer
        fields = [
            "employee_id",
            "designation",
            "department",
            "station",
            "qualifications",
            "specializations",
            "years_of_experience",
            "office_address",
            "assigned_counties",
            "max_daily_tasks",
        ]
        widgets = {
            "assigned_counties": forms.CheckboxSelectMultiple(),
            "qualifications": forms.Textarea(attrs={"rows": 3, "class": "form-control"}),
            "specializations": forms.TextInput(attrs={"class": "form-control"}),
            "office_address": forms.Textarea(attrs={"rows": 2, "class": "form-control"}),
            "years_of_experience": forms.NumberInput(attrs={"min": 0, "class": "form-control"}),
            "max_daily_tasks": forms.NumberInput(attrs={"min": 1, "class": "form-control"}),
        }

    def save(self, commit=True):
        instance = super().save(commit=False)
        source_user = self.user or getattr(instance, "user", None)
        profile = getattr(source_user, "profile", None)
        instance.phone = getattr(profile, "phone", "") or ""
        if commit:
            instance.save()
        return instance


class LandSurveyorProfileForm(AccountLinkedRoleRequestForm):
    """Form for requesting land surveyor role."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from listings.kenya_data import KENYA_COUNTIES

        self.fields["assigned_counties"].choices = [(c, c) for c in KENYA_COUNTIES]
        self.fields["assigned_counties"].required = True
        self.fields["assigned_counties"].help_text = "Select one or more counties you can verify."
        self.fields["max_daily_tasks"].required = True
        self.fields["years_of_experience"].required = True
        self.order_fields(
            [
                "username",
                "email",
                "account_phone",
                "license_number",
                "designation",
                "station",
                "qualifications",
                "years_of_experience",
                "office_address",
                "practicing_certificate_expiry",
                "assigned_counties",
                "max_daily_tasks",
            ]
        )
        for field in self.fields.values():
            if not isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs.setdefault("class", "form-control")
            if field.required:
                field.widget.attrs["required"] = "required"

    class Meta:
        model = LandSurveyor
        fields = [
            "license_number",
            "designation",
            "station",
            "qualifications",
            "years_of_experience",
            "office_address",
            "practicing_certificate_expiry",
            "assigned_counties",
            "max_daily_tasks",
        ]
        widgets = {
            "assigned_counties": forms.CheckboxSelectMultiple(),
            "qualifications": forms.Textarea(attrs={"rows": 3, "class": "form-control"}),
            "office_address": forms.Textarea(attrs={"rows": 2, "class": "form-control"}),
            "practicing_certificate_expiry": forms.DateInput(
                attrs={"type": "date", "class": "form-control"}
            ),
            "years_of_experience": forms.NumberInput(attrs={"min": 0, "class": "form-control"}),
            "max_daily_tasks": forms.NumberInput(attrs={"min": 1, "class": "form-control"}),
        }

    def save(self, commit=True):
        instance = super().save(commit=False)
        source_user = self.user or getattr(instance, "user", None)
        profile = getattr(source_user, "profile", None)
        instance.phone = getattr(profile, "phone", "") or ""
        if commit:
            instance.save()
        return instance


class MultipleFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class MultipleFileField(forms.FileField):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("widget", MultipleFileInput())
        super().__init__(*args, **kwargs)

    def clean(self, data, initial=None):
        single_file_clean = super().clean
        if isinstance(data, (list, tuple)):
            result = [single_file_clean(d, initial) for d in data]
        else:
            result = [single_file_clean(data, initial)]
        return result


class ExtensionReportForm(forms.ModelForm):
    soil_classification = forms.ChoiceField(
        required=True,
        choices=[("", "Select primary soil type")] + list(ExtensionReport.SOIL_CLASSIFICATION_CHOICES),
        widget=forms.Select(attrs={"class": "form-control"}),
        help_text="Choose the primary verified soil type for this parcel.",
    )
    current_land_use = forms.ChoiceField(
        required=True,
        choices=[("", "Select current land usage")] + list(ExtensionReport.CURRENT_LAND_USE_CHOICES),
        widget=forms.Select(attrs={"class": "form-control"}),
    )
    water_sources_available = forms.MultipleChoiceField(
        required=False,
        choices=[
            ("river", "Permanent River/Stream Access"),
            ("borehole", "Active Borehole on site"),
            ("mains", "Piping/Mains Connected"),
            ("rainfed", "Rain-fed Only"),
        ],
        widget=forms.CheckboxSelectMultiple(),
        help_text="Select all verified water sources available on or near the plot.",
    )
    recommended_crops = forms.MultipleChoiceField(
        required=False,
        choices=[],
        widget=forms.SelectMultiple(attrs={"class": "form-select", "size": 6}),
        help_text="Select up to 3 recommended crops from the agronomy library.",
    )

    site_photos = MultipleFileField(
        required=False,
        help_text="Upload photos from the site visit (you can select multiple files)",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if "soil_ph_verified" in self.fields:
            self.fields.pop("soil_ph_verified")
        if "soil_ph" in self.fields:
            self.fields["soil_ph"].required = True
            self.fields["soil_ph"].help_text = "Measured soil pH value (e.g., 6.5)"
        if "topography" in self.fields:
            self.fields["topography"].required = True
        if "current_land_use" in self.fields:
            self.fields["current_land_use"].required = True
        if "lcb_zone" in self.fields:
            self.fields["lcb_zone"].required = False
        if "recommended_crops" in self.fields:
            self.fields["recommended_crops"].choices = [
                (crop.name, crop.name) for crop in CropProfile.objects.filter(is_active=True)
            ]
        if self.instance and self.instance.water_sources_available:
            self.initial["water_sources_available"] = [
                item.strip()
                for item in self.instance.water_sources_available.split(",")
                if item.strip()
            ]
        if self.instance and self.instance.recommended_crops:
            self.initial["recommended_crops"] = [
                item.strip()
                for item in self.instance.recommended_crops.split(",")
                if item.strip()
            ]

    def clean_recommended_crops(self):
        crops = self.cleaned_data.get("recommended_crops") or []
        if len(crops) > 3:
            raise forms.ValidationError("Select at most 3 recommended crops.")
        return ", ".join(crops)

    def clean(self):
        cleaned = super().clean()
        selected_sources = cleaned.get("water_sources_available") or []
        soil_ph = cleaned.get("soil_ph")
        distance_to_tarmac_m = cleaned.get("distance_to_tarmac_m")
        distance_to_market_m = cleaned.get("distance_to_market_m")
        site_photos = cleaned.get("site_photos") or []
        soil_analysis_report = cleaned.get("soil_analysis_report")

        if soil_ph is not None and not (0 <= soil_ph <= 14):
            self.add_error("soil_ph", "Soil pH must be between 0 and 14.")

        if distance_to_tarmac_m is not None and distance_to_tarmac_m < 0:
            self.add_error("distance_to_tarmac_m", "Distance to tarmac road cannot be negative.")

        if distance_to_market_m is not None and distance_to_market_m < 0:
            self.add_error("distance_to_market_m", "Distance to market cannot be negative.")

        try:
            _validate_multiple_files("Site photos", site_photos, ALLOWED_IMAGE_EXTENSIONS)
        except forms.ValidationError as exc:
            self.add_error("site_photos", exc)

        try:
            _validate_uploaded_file(
                "Official soil analysis report", soil_analysis_report, ALLOWED_DOC_EXTENSIONS
            )
        except forms.ValidationError as exc:
            self.add_error("soil_analysis_report", exc)

        if selected_sources:
            cleaned["water_sources_available"] = ", ".join(selected_sources)
            if not cleaned.get("water_source_verified"):
                cleaned["water_source_verified"] = ", ".join(selected_sources)
        return cleaned

    class Meta:
        model = ExtensionReport
        exclude = ["task", "officer", "plot", "submitted_at", "site_photos"]
        widgets = {
            "visit_date": forms.DateTimeInput(
                attrs={"type": "datetime-local", "class": "form-control"}
            ),
            "existing_crops": forms.Textarea(attrs={"rows": 2, "class": "form-control"}),
            "pest_issues": forms.Textarea(attrs={"rows": 2, "class": "form-control"}),
            "disease_issues": forms.Textarea(attrs={"rows": 2, "class": "form-control"}),
            "improvement_suggestions": forms.Textarea(
                attrs={"rows": 3, "class": "form-control"}
            ),
            "comments": forms.Textarea(attrs={"rows": 3, "class": "form-control"}),
            "project_feasibility_note": forms.Textarea(
                attrs={"rows": 3, "class": "form-control"}
            ),
            "soil_analysis_notes": forms.Textarea(
                attrs={"rows": 3, "class": "form-control"}
            ),
            "soil_analysis_report": forms.ClearableFileInput(
                attrs={"class": "form-control", "accept": ".pdf,.jpg,.jpeg,.png"}
            ),
            "topography_summary": forms.Textarea(
                attrs={"rows": 3, "class": "form-control"}
            ),
            "soil_ph": forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
            "topography": forms.Select(attrs={"class": "form-control"}),
            "lcb_zone": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "soil_texture": forms.Select(attrs={"class": "form-control"}),
            "soil_drainage": forms.Select(attrs={"class": "form-control"}),
            "crop_health": forms.Select(attrs={"class": "form-control"}),
            "water_quality": forms.Select(attrs={"class": "form-control"}),
            "distance_to_tarmac_m": forms.NumberInput(attrs={"class": "form-control", "min": 0}),
            "distance_to_market_m": forms.NumberInput(attrs={"class": "form-control", "min": 0}),
            "irrigation_viability": forms.RadioSelect(),
            "power_access": forms.Select(attrs={"class": "form-control"}),
            "overall_suitability": forms.Select(attrs={"class": "form-control"}),
            "recommendation": forms.Select(attrs={"class": "form-control"}),
            "zoning_status": forms.Select(attrs={"class": "form-control"}),
            "lcb_approval_potential": forms.Select(attrs={"class": "form-control"}),
        }


class SurveyorReportForm(forms.ModelForm):
    beacon_status = forms.MultipleChoiceField(
        required=True,
        choices=SurveyorReport._meta.get_field("beacon_status").choices,
        widget=forms.CheckboxSelectMultiple(),
        help_text="Select all beacon and boundary conditions confirmed during the site visit.",
    )
    plot_images = MultipleFileField(
        required=False,
        label="Plot Images (Survey Photos)",
        help_text="Upload clear photos of the plot (JPG/PNG).",
        widget=MultipleFileInput(attrs={"class": "form-control", "accept": "image/*"}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if "surveyor_license_number" in self.fields:
            self.fields.pop("surveyor_license_number")
        if "lsb_license_number" in self.fields:
            self.fields["lsb_license_number"].required = True
            self.fields["lsb_license_number"].help_text = (
                "Land Surveyors Board (LSB) registration number"
            )
        if "mutation_form" in self.fields:
            self.fields["mutation_form"].required = True
        if "ground_acreage" in self.fields:
            self.fields["ground_acreage"].label = "Measured Area (Ha)"
            self.fields["ground_acreage"].help_text = (
                "Actual area measured on the ground (hectares)"
            )
        if "reference_number" in self.fields:
            self.fields["reference_number"].help_text = "RIM sheet number, mutation number, or equivalent official reference."
        if "boundary_data_file" in self.fields:
            self.fields["boundary_data_file"].help_text = "Upload the site boundary as .geojson, .kml, or .shp."
        if self.instance and self.instance.beacon_status:
            # Handle comma-separated values from the model
            self.initial["beacon_status"] = [
                item.strip()
                for item in self.instance.beacon_status.split(",")
                if item.strip()
            ]

    def clean(self):
        cleaned = super().clean()
        price_realistic = cleaned.get("price_realistic")
        suggested_sale_price = cleaned.get("suggested_sale_price")
        suggested_price_per_acre = cleaned.get("suggested_price_per_acre")
        beacon_status = cleaned.get("beacon_status") or []
        gps_latitude = cleaned.get("gps_latitude")
        gps_longitude = cleaned.get("gps_longitude")
        ground_acreage = cleaned.get("ground_acreage")
        deed_area = cleaned.get("deed_area")
        boundary_data_file = cleaned.get("boundary_data_file")
        plot_images = cleaned.get("plot_images") or []
        
        if not cleaned.get("surveyor_declaration"):
            self.add_error(
                "surveyor_declaration",
                "You must certify that you physically visited and verified the parcel."
            )
            
        # Standardize the beacon_status into a comma-separated string for the model
        if beacon_status:
            cleaned["beacon_status"] = ", ".join(beacon_status)
        
        # Legacy value mapping (if any)
        if "all_present" in beacon_status:
            beacon_status = ["all_present_and_intact" if x == "all_present" else x for x in beacon_status]
            cleaned["beacon_status"] = ", ".join(beacon_status)
        if "missing" in beacon_status:
            beacon_status = ["beacons_missing" if x == "missing" else x for x in beacon_status]
            cleaned["beacon_status"] = ", ".join(beacon_status)
        if price_realistic is False and not (suggested_sale_price or suggested_price_per_acre):
            self.add_error(
                "suggested_sale_price", "Provide a suggested sale price or price per acre."
            )

        if gps_latitude is not None and not (-90 <= gps_latitude <= 90):
            self.add_error("gps_latitude", "Latitude must be between -90 and 90.")

        if gps_longitude is not None and not (-180 <= gps_longitude <= 180):
            self.add_error("gps_longitude", "Longitude must be between -180 and 180.")

        if ground_acreage is not None and ground_acreage <= 0:
            self.add_error("ground_acreage", "Measured area must be greater than zero.")

        if deed_area is not None and deed_area <= 0:
            self.add_error("deed_area", "Deed area must be greater than zero.")

        for field_name, label, allowed_extensions in (
            ("mutation_form", "Mutation form", ALLOWED_DOC_EXTENSIONS),
            ("beacon_certificate", "Beacon certificate", ALLOWED_DOC_EXTENSIONS),
            ("boundary_report", "Boundary report", ALLOWED_DOC_EXTENSIONS),
            ("signed_survey_plan", "Signed survey plan", ALLOWED_DOC_EXTENSIONS),
            ("boundary_data_file", "Boundary data file", ALLOWED_BOUNDARY_EXTENSIONS),
        ):
            try:
                _validate_uploaded_file(label, cleaned.get(field_name), allowed_extensions)
            except forms.ValidationError as exc:
                self.add_error(field_name, exc)

        try:
            _validate_multiple_files("Plot images", plot_images, ALLOWED_IMAGE_EXTENSIONS)
        except forms.ValidationError as exc:
            self.add_error("plot_images", exc)

        return cleaned

    class Meta:
        model = SurveyorReport
        exclude = ["task", "surveyor", "plot", "submitted_at"]
        widgets = {
            "visit_date": forms.DateTimeInput(
                attrs={"type": "datetime-local", "class": "form-control"}
            ),
            "gps_latitude": forms.NumberInput(attrs={"class": "form-control"}),
            "gps_longitude": forms.NumberInput(attrs={"class": "form-control"}),
            "encumbrance_details": forms.Textarea(attrs={"rows": 2, "class": "form-control"}),
            "boundary_markers": forms.Textarea(attrs={"rows": 2, "class": "form-control"}),
            "official_document_reference": forms.Select(attrs={"class": "form-control"}),
            "reference_number": forms.TextInput(attrs={"class": "form-control"}),
            "rim_map_sheet_no": forms.TextInput(attrs={"class": "form-control"}),
            "ground_acreage": forms.NumberInput(
                attrs={"class": "form-control", "step": "0.0001"}
            ),
            "deed_area": forms.NumberInput(attrs={"class": "form-control", "step": "0.0001"}),
            "lsb_license_number": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "LSB/123"}
            ),
            "mutation_form": forms.ClearableFileInput(
                attrs={"class": "form-control", "accept": ".pdf,.jpg,.jpeg,.png"}
            ),
            "beacon_certificate": forms.ClearableFileInput(
                attrs={"class": "form-control", "accept": ".pdf,.jpg,.jpeg,.png"}
            ),
            "boundary_report": forms.ClearableFileInput(
                attrs={"class": "form-control", "accept": ".pdf,.jpg,.jpeg,.png"}
            ),
            "signed_survey_plan": forms.ClearableFileInput(
                attrs={"class": "form-control", "accept": ".pdf,.jpg,.jpeg,.png"}
            ),
            "boundary_data_file": forms.ClearableFileInput(
                attrs={"class": "form-control", "accept": ".geojson,.kml,.shp"}
            ),
            "topography_notes": forms.Textarea(attrs={"rows": 2, "class": "form-control"}),
            "access_road": forms.TextInput(attrs={"class": "form-control"}),
            "utilities_available": forms.Textarea(attrs={"rows": 2, "class": "form-control"}),
            "encroachment_found": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "encroachment_details": forms.Textarea(attrs={"rows": 2, "class": "form-control"}),
            "price_review_notes": forms.Textarea(attrs={"rows": 2, "class": "form-control"}),
            "suggested_price_per_acre": forms.NumberInput(attrs={"class": "form-control"}),
            "suggested_sale_price": forms.NumberInput(attrs={"class": "form-control"}),
            "surveyor_declaration": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "notes": forms.Textarea(attrs={"rows": 3, "class": "form-control"}),
            "recommendation": forms.Select(attrs={"class": "form-control"}),
        }
