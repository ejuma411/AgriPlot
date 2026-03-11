from django import forms

from verification.models import (
    ExtensionOfficer,
    ExtensionReport,
    LandSurveyor,
    SurveyorReport,
)


class ExtensionOfficerProfileForm(forms.ModelForm):
    """Form for requesting extension officer role."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from listings.kenya_data import KENYA_COUNTIES

        self.fields["assigned_counties"].choices = [(c, c) for c in KENYA_COUNTIES]
        self.fields["assigned_counties"].required = True
        self.fields["assigned_counties"].help_text = "Select one or more counties you can verify."
        self.fields["max_daily_tasks"].required = True
        self.fields["years_of_experience"].required = True
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
            "phone",
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


class LandSurveyorProfileForm(forms.ModelForm):
    """Form for requesting land surveyor role."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from listings.kenya_data import KENYA_COUNTIES

        self.fields["assigned_counties"].choices = [(c, c) for c in KENYA_COUNTIES]
        self.fields["assigned_counties"].required = True
        self.fields["assigned_counties"].help_text = "Select one or more counties you can verify."
        self.fields["max_daily_tasks"].required = True
        self.fields["years_of_experience"].required = True
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
            "phone",
            "office_address",
            "assigned_counties",
            "max_daily_tasks",
        ]
        widgets = {
            "assigned_counties": forms.CheckboxSelectMultiple(),
            "qualifications": forms.Textarea(attrs={"rows": 3, "class": "form-control"}),
            "office_address": forms.Textarea(attrs={"rows": 2, "class": "form-control"}),
            "years_of_experience": forms.NumberInput(attrs={"min": 0, "class": "form-control"}),
            "max_daily_tasks": forms.NumberInput(attrs={"min": 1, "class": "form-control"}),
        }


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
            "recommended_crops": forms.Textarea(attrs={"rows": 2, "class": "form-control"}),
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
            "topography_summary": forms.Textarea(
                attrs={"rows": 3, "class": "form-control"}
            ),
            "soil_ph": forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
            "soil_classification": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "e.g., Black Cotton"}
            ),
            "topography": forms.Select(attrs={"class": "form-control"}),
            "current_land_use": forms.Textarea(attrs={"rows": 2, "class": "form-control"}),
            "lcb_zone": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "soil_texture": forms.Select(attrs={"class": "form-control"}),
            "soil_drainage": forms.Select(attrs={"class": "form-control"}),
            "crop_health": forms.Select(attrs={"class": "form-control"}),
            "water_quality": forms.Select(attrs={"class": "form-control"}),
            "power_access": forms.Select(attrs={"class": "form-control"}),
            "overall_suitability": forms.Select(attrs={"class": "form-control"}),
            "recommendation": forms.Select(attrs={"class": "form-control"}),
            "zoning_status": forms.Select(attrs={"class": "form-control"}),
            "lcb_approval_potential": forms.Select(attrs={"class": "form-control"}),
        }


class SurveyorReportForm(forms.ModelForm):
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

    def clean(self):
        cleaned = super().clean()
        price_realistic = cleaned.get("price_realistic")
        suggested_sale_price = cleaned.get("suggested_sale_price")
        suggested_price_per_acre = cleaned.get("suggested_price_per_acre")
        if price_realistic is False and not (suggested_sale_price or suggested_price_per_acre):
            self.add_error(
                "suggested_sale_price", "Provide a suggested sale price or price per acre."
            )
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
            "beacon_status": forms.Select(attrs={"class": "form-control"}),
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
            "topography_notes": forms.Textarea(attrs={"rows": 2, "class": "form-control"}),
            "access_road": forms.TextInput(attrs={"class": "form-control"}),
            "utilities_available": forms.Textarea(attrs={"rows": 2, "class": "form-control"}),
            "encroachment_found": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "encroachment_details": forms.Textarea(attrs={"rows": 2, "class": "form-control"}),
            "price_review_notes": forms.Textarea(attrs={"rows": 2, "class": "form-control"}),
            "suggested_price_per_acre": forms.NumberInput(attrs={"class": "form-control"}),
            "suggested_sale_price": forms.NumberInput(attrs={"class": "form-control"}),
            "notes": forms.Textarea(attrs={"rows": 3, "class": "form-control"}),
            "recommendation": forms.Select(attrs={"class": "form-control"}),
        }

