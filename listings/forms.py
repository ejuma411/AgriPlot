import logging
import os
import hashlib
from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from django.db.models import Q
from django.utils import timezone
from .models import *
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from .location_utils import validate_kenyan_location, get_subcounties_for_county
from .kenya_data import KENYA_COUNTIES, KENYA_SUB_COUNTIES
from registry_mock.services import verify_with_registry
from registry_mock.models import RegistryMismatchAttempt
import re

# Get logger for this module
logger = logging.getLogger(__name__)
validation_logger = logging.getLogger('listings.validation')

ALLOWED_DOC_EXTENSIONS = {'.pdf', '.jpg', '.jpeg', '.png'}
MAX_UPLOAD_MB = 20

PARCEL_PATTERN_REGISTRY = re.compile(r"^[A-Za-z0-9]+(?:/[A-Za-z0-9]+)+$")
PARCEL_PATTERN_LR = re.compile(r"^L\.?R\.?\s*(NO\.?|NO|NUMBER)?\s*\d+(?:/\d+)*$", re.IGNORECASE)


def _normalize_kenyan_phone(value):
    phone = str(value or "").strip().replace(" ", "")
    if phone.startswith("+"):
        phone = phone[1:]
    if phone.startswith("0"):
        phone = "254" + phone[1:]
    elif phone.startswith("7"):
        phone = "254" + phone
    return phone


def _phone_exists_in_system(phone_value):
    from accounts.models import Agent, Profile
    from security.models import PhoneEmailVerification

    normalized_input = _normalize_kenyan_phone(phone_value)
    if not normalized_input:
        return False

    existing_numbers = list(
        Profile.objects.exclude(phone__isnull=True).exclude(phone__exact="").values_list("phone", flat=True)
    )
    existing_numbers += list(
        Agent.objects.exclude(phone__exact="").values_list("phone", flat=True)
    )
    existing_numbers += list(
        PhoneEmailVerification.objects.exclude(phone_number__exact="").values_list("phone_number", flat=True)
    )
    return any(_normalize_kenyan_phone(number) == normalized_input for number in existing_numbers)

def _validate_parcel_number(value):
    if not value:
        raise forms.ValidationError("Parcel number is required.")
    normalized = value.strip()
    if not (PARCEL_PATTERN_REGISTRY.match(normalized) or PARCEL_PATTERN_LR.match(normalized)):
        raise forms.ValidationError(
            "Use a valid parcel format (e.g., REGISTRY/BLOCK/PARCEL or LR 1234/567)."
        )
    return normalized

def _validate_upload(field_name, file_obj):
    if not file_obj:
        return
    max_size = MAX_UPLOAD_MB * 1024 * 1024
    if hasattr(file_obj, 'size') and file_obj.size > max_size:
        raise forms.ValidationError(
            f"{field_name} must be less than {MAX_UPLOAD_MB}MB."
        )
    if hasattr(file_obj, 'name'):
        ext = os.path.splitext(file_obj.name)[1].lower()
        if ext not in ALLOWED_DOC_EXTENSIONS:
            raise forms.ValidationError(
                f"{field_name} must be a PDF or image file."
            )


class PlotSearchForm(forms.Form):
    SIZE_PRESET_CHOICES = [
        ("small_scale", "Small-scale (Eighth/Quarter Acre)"),
        ("commercial", "Commercial (1-10 Acres)"),
        ("estate", "Large-scale/Estate (Over 10 Acres)"),
    ]
    REGISTRY_STATUS_CHOICES = [
        ("", "Any registry status"),
        ("ardhisasa", "Verified on Ardhisasa"),
        ("manual", "Manual registry trail"),
    ]
    ROAD_DISTANCE_CHOICES = [
        ("", "Any tarmac distance"),
        ("0_5", "0-5 km"),
        ("5_10", "5-10 km"),
        ("10_plus", "Over 10 km"),
    ]
    SORT_CHOICES = [
        ("-created_at", "Newest first"),
        ("price", "Price: Low to High"),
        ("-price", "Price: High to Low"),
        ("area", "Area: Small to Large"),
        ("-area", "Area: Large to Small"),
    ]
    SOIL_TYPE_CHOICES = [
        ("", "Any soil type"),
        ("Red Volcanic", "Red Volcanic"),
        ("Black Cotton", "Black Cotton"),
        ("Sandy", "Sandy"),
        ("Loam", "Loam"),
        ("Clay", "Clay"),
    ]

    q = forms.CharField(
        required=False,
        label="Search",
        widget=forms.TextInput(
            attrs={
                "placeholder": "Try: 3 acres for lease in Njoro under 1M",
                "class": "form-control",
            }
        ),
    )
    county = forms.ChoiceField(required=False, choices=[], widget=forms.Select(attrs={"class": "form-select"}))
    subcounty = forms.ChoiceField(required=False, choices=[("", "Any sub-county")], widget=forms.Select(attrs={"class": "form-select"}))
    ward = forms.CharField(required=False, widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "Any ward"}))
    listing_type = forms.ChoiceField(required=False, choices=[("", "Sale or lease")] + list(Plot.LISTING_TYPE_CHOICES), widget=forms.Select(attrs={"class": "form-select"}))
    land_type = forms.ChoiceField(required=False, choices=[("", "Any land type")] + list(Plot.LAND_TYPE_CHOICES), widget=forms.Select(attrs={"class": "form-select"}))
    soil_type = forms.ChoiceField(required=False, choices=SOIL_TYPE_CHOICES, widget=forms.Select(attrs={"class": "form-select"}))
    topography = forms.ChoiceField(required=False, choices=[("", "Any topography")] + list(Plot.TOPOGRAPHY_CHOICES), widget=forms.Select(attrs={"class": "form-select"}))
    crop = forms.CharField(required=False, widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "Crop or enterprise"}))
    water_source = forms.ChoiceField(required=False, choices=[("", "Any water access")] + [choice for choice in Plot.WATER_SOURCE_CHOICES if choice[0] != "none"], widget=forms.Select(attrs={"class": "form-select"}))
    ownership_type = forms.ChoiceField(required=False, choices=[("", "Any title type")] + list(Plot._meta.get_field("ownership_type").choices), widget=forms.Select(attrs={"class": "form-select"}))
    registry_status = forms.ChoiceField(required=False, choices=REGISTRY_STATUS_CHOICES, widget=forms.Select(attrs={"class": "form-select"}))
    road_distance_band = forms.ChoiceField(required=False, choices=ROAD_DISTANCE_CHOICES, widget=forms.Select(attrs={"class": "form-select"}))
    size_presets = forms.MultipleChoiceField(required=False, choices=SIZE_PRESET_CHOICES, widget=forms.CheckboxSelectMultiple())
    min_price = forms.DecimalField(required=False, min_value=0, widget=forms.NumberInput(attrs={"class": "form-control", "placeholder": "Min price"}))
    max_price = forms.DecimalField(required=False, min_value=0, widget=forms.NumberInput(attrs={"class": "form-control", "placeholder": "Max price"}))
    has_electricity = forms.BooleanField(required=False)
    encumbrance_free = forms.BooleanField(required=False)
    verified_only = forms.BooleanField(required=False)
    sort = forms.ChoiceField(required=False, choices=SORT_CHOICES, initial="-created_at")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["county"].choices = [("", "Any county")] + [(county, county) for county in KENYA_COUNTIES]

        selected_county = ""
        if self.is_bound:
            selected_county = self.data.get("county", "")
        else:
            selected_county = self.initial.get("county", "")
        if selected_county in KENYA_SUB_COUNTIES:
            self.fields["subcounty"].choices = [("", "Any sub-county")] + [
                (subcounty, subcounty) for subcounty in KENYA_SUB_COUNTIES[selected_county]
            ]

    @staticmethod
    def _parse_money_token(raw_value):
        normalized = raw_value.replace(",", "").strip().lower()
        multiplier = Decimal("1")
        if normalized.endswith("k"):
            multiplier = Decimal("1000")
            normalized = normalized[:-1]
        elif normalized.endswith("m"):
            multiplier = Decimal("1000000")
            normalized = normalized[:-1]
        elif normalized.endswith("b"):
            multiplier = Decimal("1000000000")
            normalized = normalized[:-1]
        try:
            return Decimal(normalized) * multiplier
        except InvalidOperation:
            return None

    @classmethod
    def _parse_natural_language_query(cls, query):
        if not query:
            return {}

        parsed = {}
        lowered = query.lower()

        if "lease" in lowered or "rent" in lowered:
            parsed["listing_type"] = "lease"
        elif "sale" in lowered or "buy" in lowered or "purchase" in lowered:
            parsed["listing_type"] = "sale"

        if "freehold" in lowered:
            parsed["ownership_type"] = "freehold"
        elif "leasehold" in lowered:
            parsed["ownership_type"] = "leasehold"

        if "ardhisasa" in lowered:
            parsed["registry_status"] = "ardhisasa"
        elif "manual search" in lowered or "manual registry" in lowered:
            parsed["registry_status"] = "manual"

        if "verified only" in lowered or "verified plot" in lowered:
            parsed["verified_only"] = True

        if "encumbrance-free" in lowered or "encumbrance free" in lowered or "no bank charges" in lowered:
            parsed["encumbrance_free"] = True

        if "riverfront" in lowered:
            parsed["water_source"] = "river"
        elif "borehole" in lowered:
            parsed["water_source"] = "borehole"
        elif "rain-fed" in lowered or "rain fed" in lowered:
            parsed["water_source"] = "rain"
        elif "irrigation" in lowered:
            parsed["water_source"] = "irrigation"

        if "flat" in lowered:
            parsed["topography"] = "flat"
        elif "gentle slope" in lowered:
            parsed["topography"] = "gentle_slope"
        elif "sloped" in lowered or "slope" in lowered:
            parsed["topography"] = "sloped"
        elif "hilly" in lowered:
            parsed["topography"] = "hilly"

        if "electricity" in lowered or "power" in lowered:
            parsed["has_electricity"] = True

        if "tarmac" in lowered:
            if "0-5" in lowered or "0 to 5" in lowered or "within 5" in lowered:
                parsed["road_distance_band"] = "0_5"
            elif "5-10" in lowered or "5 to 10" in lowered or "within 10" in lowered:
                parsed["road_distance_band"] = "5_10"

        area_match = re.search(r"(\d+(?:\.\d+)?)\s*(acres?|hectares?|ha)\b", lowered)
        if area_match:
            area_value = Decimal(area_match.group(1))
            area_unit = area_match.group(2)
            if area_unit.startswith("h"):
                area_value *= Decimal("2.47105")
            parsed["min_area"] = area_value
            parsed["max_area"] = area_value

        max_price_match = re.search(r"\b(?:under|below|max(?:imum)?|less than)\s+([\d,.]+(?:[kmb])?)\b", lowered)
        if max_price_match:
            max_price = cls._parse_money_token(max_price_match.group(1))
            if max_price is not None:
                parsed["max_price"] = max_price

        min_price_match = re.search(r"\b(?:over|above|min(?:imum)?|from)\s+([\d,.]+(?:[kmb])?)\b", lowered)
        if min_price_match:
            min_price = cls._parse_money_token(min_price_match.group(1))
            if min_price is not None:
                parsed["min_price"] = min_price

        location_match = re.search(
            r"\bin\s+([a-z][a-z\s]+?)(?=\s+(?:under|below|over|above|max|min|with|for)\b|$)",
            lowered,
        )
        if location_match:
            parsed["location_query"] = " ".join(location_match.group(1).split()).title()

        crop_match = re.search(r"\b(?:for|grow|growing|suitable for)\s+([a-z][a-z\s-]+?)(?=\s+(?:in|under|below|over|with)\b|$)", lowered)
        if crop_match:
            crop_value = " ".join(crop_match.group(1).split())
            if crop_value not in {"sale", "lease"}:
                parsed["crop"] = crop_value.title()

        for county in KENYA_COUNTIES:
            if county.lower() in lowered:
                parsed["county"] = county
                break

        if not parsed.get("county"):
            for county, subcounties in KENYA_SUB_COUNTIES.items():
                for subcounty in subcounties:
                    if subcounty.lower() in lowered:
                        parsed["county"] = county
                        parsed["subcounty"] = subcounty
                        parsed.setdefault("location_query", subcounty)
                        break
                if parsed.get("subcounty"):
                    break

        return parsed

    def clean(self):
        cleaned_data = super().clean()
        query = cleaned_data.get("q", "").strip()
        parsed_query = self._parse_natural_language_query(query)
        cleaned_data["parsed_query"] = parsed_query

        for key in (
            "county",
            "subcounty",
            "listing_type",
            "min_price",
            "max_price",
            "ownership_type",
            "registry_status",
            "water_source",
            "topography",
            "road_distance_band",
            "crop",
        ):
            if not cleaned_data.get(key) and parsed_query.get(key) is not None:
                cleaned_data[key] = parsed_query[key]

        if not cleaned_data.get("verified_only") and parsed_query.get("verified_only"):
            cleaned_data["verified_only"] = True
        if not cleaned_data.get("encumbrance_free") and parsed_query.get("encumbrance_free"):
            cleaned_data["encumbrance_free"] = True
        if not cleaned_data.get("has_electricity") and parsed_query.get("has_electricity"):
            cleaned_data["has_electricity"] = True

        cleaned_data["location_query"] = parsed_query.get("location_query", query).strip()
        cleaned_data["min_area"] = parsed_query.get("min_area")
        cleaned_data["max_area"] = parsed_query.get("max_area")

        county = cleaned_data.get("county")
        subcounty = cleaned_data.get("subcounty")
        if county and subcounty and subcounty not in KENYA_SUB_COUNTIES.get(county, []):
            self.add_error("subcounty", "Choose a valid sub-county for the selected county.")

        min_price = cleaned_data.get("min_price")
        max_price = cleaned_data.get("max_price")
        if min_price is not None and max_price is not None and min_price > max_price:
            self.add_error("max_price", "Maximum price must be greater than or equal to minimum price.")

        return cleaned_data

    def apply(self, queryset):
        base_queryset = queryset.exclude(market_status="sold")
        default_sort = "-created_at"

        if not self.is_bound:
            return base_queryset.order_by(default_sort).distinct()

        if not self.is_valid():
            return base_queryset.order_by(default_sort).distinct()

        data = self.cleaned_data
        queryset = base_queryset

        if data.get("county"):
            queryset = queryset.filter(county__iexact=data["county"])
        if data.get("subcounty"):
            queryset = queryset.filter(subcounty__iexact=data["subcounty"])
        if data.get("ward"):
            queryset = queryset.filter(ward__icontains=data["ward"])

        location_query = data.get("location_query")
        if location_query:
            queryset = queryset.filter(
                Q(county__icontains=location_query)
                | Q(subcounty__icontains=location_query)
                | Q(ward__icontains=location_query)
                | Q(nearest_town__icontains=location_query)
                | Q(location__icontains=location_query)
                | Q(title__icontains=location_query)
            )

        if data.get("listing_type"):
            listing_type = data["listing_type"]
            if listing_type == "both":
                queryset = queryset.filter(listing_type="both")
            else:
                queryset = queryset.filter(Q(listing_type=listing_type) | Q(listing_type="both"))

        if data.get("land_type"):
            queryset = queryset.filter(land_type=data["land_type"])
        if data.get("soil_type"):
            queryset = queryset.filter(soil_type__icontains=data["soil_type"])
        if data.get("topography"):
            queryset = queryset.filter(topography=data["topography"])
        if data.get("crop"):
            queryset = queryset.filter(crop_suitability__icontains=data["crop"])
        if data.get("water_source"):
            queryset = queryset.filter(water_source=data["water_source"])
        if data.get("ownership_type"):
            queryset = queryset.filter(ownership_type=data["ownership_type"])
        if data.get("has_electricity"):
            queryset = queryset.filter(has_electricity=True)
        if data.get("encumbrance_free"):
            queryset = queryset.filter(encumbrances=False, registry_has_encumbrances=False)

        min_price = data.get("min_price")
        max_price = data.get("max_price")
        if min_price is not None:
            queryset = queryset.filter(price__gte=min_price)
        if max_price is not None:
            queryset = queryset.filter(price__lte=max_price)

        min_area = data.get("min_area")
        max_area = data.get("max_area")
        if min_area is not None:
            queryset = queryset.filter(area__gte=float(min_area))
        if max_area is not None:
            queryset = queryset.filter(area__lte=float(max_area))

        size_presets = data.get("size_presets") or []
        if size_presets:
            size_query = Q()
            for preset in size_presets:
                if preset == "small_scale":
                    size_query |= Q(area__gte=0.125, area__lte=0.25, area_unit="acres")
                elif preset == "commercial":
                    size_query |= Q(area__gte=1, area__lte=10, area_unit="acres")
                elif preset == "estate":
                    size_query |= Q(area__gt=10, area_unit="acres")
            queryset = queryset.filter(size_query)

        road_distance_band = data.get("road_distance_band")
        if road_distance_band == "0_5":
            queryset = queryset.filter(road_distance_km__gte=0, road_distance_km__lte=5)
        elif road_distance_band == "5_10":
            queryset = queryset.filter(road_distance_km__gt=5, road_distance_km__lte=10)
        elif road_distance_band == "10_plus":
            queryset = queryset.filter(road_distance_km__gt=10)

        registry_status = data.get("registry_status")
        if registry_status == "ardhisasa":
            queryset = queryset.filter(search_result__verified=True)
        elif registry_status == "manual":
            queryset = queryset.filter(official_search__isnull=False).exclude(search_result__verified=True)

        if data.get("verified_only"):
            queryset = queryset.filter(
                official_search__isnull=False,
            ).filter(
                Q(survey_map__isnull=False) | Q(surveyor_reports__isnull=False)
            )

        sort_value = data.get("sort") or default_sort
        allowed_sorts = {choice[0] for choice in self.SORT_CHOICES}
        if sort_value not in allowed_sorts:
            sort_value = default_sort
        return queryset.order_by(sort_value).distinct()

    def active_filters(self):
        if not self.is_valid():
            return []

        data = self.cleaned_data
        filters = []
        if data.get("q"):
            filters.append({"label": "Search", "value": data["q"], "params": ["q"]})
        if data.get("county"):
            filters.append({"label": "County", "value": data["county"], "params": ["county"]})
        if data.get("subcounty"):
            filters.append({"label": "Sub-county", "value": data["subcounty"], "params": ["subcounty"]})
        if data.get("ward"):
            filters.append({"label": "Ward", "value": data["ward"], "params": ["ward"]})
        if data.get("listing_type"):
            filters.append({"label": "Listing", "value": dict(Plot.LISTING_TYPE_CHOICES).get(data["listing_type"], data["listing_type"]), "params": ["listing_type"]})
        if data.get("soil_type"):
            filters.append({"label": "Soil", "value": data["soil_type"], "params": ["soil_type"]})
        if data.get("topography"):
            filters.append({"label": "Topography", "value": dict(Plot.TOPOGRAPHY_CHOICES).get(data["topography"], data["topography"]), "params": ["topography"]})
        if data.get("crop"):
            filters.append({"label": "Crop", "value": data["crop"], "params": ["crop"]})
        if data.get("ownership_type"):
            filters.append({"label": "Title", "value": dict(Plot._meta.get_field("ownership_type").choices).get(data["ownership_type"], data["ownership_type"]), "params": ["ownership_type"]})
        if data.get("registry_status"):
            filters.append({"label": "Registry", "value": dict(self.REGISTRY_STATUS_CHOICES).get(data["registry_status"], data["registry_status"]), "params": ["registry_status"]})
        if data.get("encumbrance_free"):
            filters.append({"label": "Legal", "value": "Encumbrance-free", "params": ["encumbrance_free"]})
        if data.get("water_source"):
            filters.append({"label": "Water", "value": dict(Plot.WATER_SOURCE_CHOICES).get(data["water_source"], data["water_source"]), "params": ["water_source"]})
        if data.get("has_electricity"):
            filters.append({"label": "Power", "value": "Electricity available", "params": ["has_electricity"]})
        if data.get("road_distance_band"):
            filters.append({"label": "Road", "value": dict(self.ROAD_DISTANCE_CHOICES).get(data["road_distance_band"], data["road_distance_band"]), "params": ["road_distance_band"]})
        if data.get("verified_only"):
            filters.append({"label": "Trust", "value": "Verified pack only", "params": ["verified_only"]})
        if data.get("min_price") is not None or data.get("max_price") is not None:
            if data.get("min_price") is not None and data.get("max_price") is not None:
                value = f"KES {int(data['min_price'])} - {int(data['max_price'])}"
            elif data.get("min_price") is not None:
                value = f"From KES {int(data['min_price'])}"
            else:
                value = f"Up to KES {int(data['max_price'])}"
            filters.append({"label": "Budget", "value": value, "params": ["min_price", "max_price"]})
        if data.get("size_presets"):
            for preset in data["size_presets"]:
                filters.append({"label": "Size", "value": dict(self.SIZE_PRESET_CHOICES).get(preset, preset), "params": ["size_presets"]})
        return filters

# ============ CUSTOM FORM WIDGETS ============
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
            result = single_file_clean(data, initial)
        return result


# ============ USER REGISTRATION FORMS ============
class BaseUserRegistrationForm(UserCreationForm):
    """Base form with common user registration fields"""
    email = forms.EmailField(required=True)
    first_name = forms.CharField(max_length=50, required=True)
    last_name = forms.CharField(max_length=50, required=True)
    phone = forms.CharField(
        max_length=15,
        required=True,
        help_text="Phone number for verification (e.g., +254718810503)",
        widget=forms.TextInput(attrs={
            'class': 'form-control', 
            'placeholder': '+254718810503'
        })
    )
    
    class Meta:
        model = User
        fields = ['username', 'email', 'first_name', 'last_name', 'phone', 'password1', 'password2']
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Add Bootstrap classes to all fields
        for field_name, field in self.fields.items():
            field.widget.attrs.update({'class': 'form-control'})
        
        # Add phone validation
        self.fields['phone'].validators.append(self.validate_phone)
    
    def validate_phone(self, value):
        """Basic phone number validation"""
        import re
        pattern = r'^\+?254\d{9}$|^0\d{9}$'
        if not re.match(pattern, value):
            raise forms.ValidationError(
                "Enter a valid Kenyan phone number (e.g., 0712345678 or +254712345678)"
            )
        return True

    def clean_email(self):
        email = (self.cleaned_data.get("email") or "").strip().lower()
        if email and User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("An account with this email already exists.")
        return email

    def clean_phone(self):
        phone = (self.cleaned_data.get("phone") or "").strip()
        self.validate_phone(phone)
        if _phone_exists_in_system(phone):
            raise forms.ValidationError("An account with this phone number already exists.")
        return phone

class BuyerRegistrationForm(BaseUserRegistrationForm):
    """Simple buyer registration form"""
    pass


class LandownerRegistrationForm(BaseUserRegistrationForm):
    """Landowner registration with document uploads"""

    national_id = forms.FileField(
        required=True,
        help_text="Upload a copy of your national ID",
        widget=forms.FileInput(attrs={'class': 'form-control'})
    )
    kra_pin = forms.FileField(
        required=True,
        help_text="Upload a copy of your KRA PIN",
        widget=forms.FileInput(attrs={'class': 'form-control'})
    )
    title_deed = forms.FileField(
        required=True,
        help_text="Upload land title deed",
        widget=forms.FileInput(attrs={'class': 'form-control'})
    )
    land_search = forms.FileField(
        required=True,
        help_text="Upload official land search certificate",
        widget=forms.FileInput(attrs={'class': 'form-control'})
    )
    lcb_consent = forms.FileField(
        required=False,
        help_text="Optional: Upload LCB consent if applicable",
        widget=forms.FileInput(attrs={'class': 'form-control'})
    )

    def clean(self):
        cleaned = super().clean()
        _validate_upload("National ID", cleaned.get('national_id'))
        _validate_upload("KRA PIN", cleaned.get('kra_pin'))
        _validate_upload("Title Deed", cleaned.get('title_deed'))
        _validate_upload("Land Search", cleaned.get('land_search'))
        _validate_upload("LCB Consent", cleaned.get('lcb_consent'))
        return cleaned


class AgentRegistrationForm(BaseUserRegistrationForm):
    """Agent registration with professional details"""
    
    id_number = forms.CharField(
        max_length=20,
        required=True,
        help_text="National ID number",
        widget=forms.TextInput(attrs={'class': 'form-control'})
    )
    license_number = forms.CharField(
        max_length=100,
        required=True,
        widget=forms.TextInput(attrs={'class': 'form-control'})
    )
    kra_pin = forms.FileField(
        required=True,
        help_text="Upload your KRA PIN certificate",
        widget=forms.FileInput(attrs={'class': 'form-control'})
    )
    practicing_certificate = forms.FileField(
        required=False,
        help_text="Upload your practicing certificate (optional)",
        widget=forms.FileInput(attrs={'class': 'form-control'})
    )
    good_conduct = forms.FileField(
        required=False,
        help_text="Upload certificate of good conduct (optional)",
        widget=forms.FileInput(attrs={'class': 'form-control'})
    )
    professional_indemnity = forms.FileField(
        required=False,
        help_text="Upload professional indemnity insurance (optional)",
        widget=forms.FileInput(attrs={'class': 'form-control'})
    )
    license_doc = forms.FileField(
        required=True,
        widget=forms.FileInput(attrs={'class': 'form-control'}),
        help_text="Upload license certificate"
    )

    def clean(self):
        cleaned = super().clean()
        _validate_upload("KRA PIN", cleaned.get('kra_pin'))
        _validate_upload("License Document", cleaned.get('license_doc'))
        _validate_upload("Practicing Certificate", cleaned.get('practicing_certificate'))
        _validate_upload("Good Conduct", cleaned.get('good_conduct'))
        _validate_upload("Professional Indemnity", cleaned.get('professional_indemnity'))
        return cleaned


# ============ ROLE UPGRADE FORMS ============
class BaseUpgradeForm(forms.ModelForm):
    """Base form for role upgrades with user info display"""
    username = forms.CharField(
        required=False,
        disabled=True,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'readonly': 'readonly',
        })
    )
    email = forms.EmailField(
        required=False,
        disabled=True,
        widget=forms.EmailInput(attrs={
            'class': 'form-control',
            'readonly': 'readonly',
        })
    )
    account_phone = forms.CharField(
        required=False,
        disabled=True,
        label="Phone",
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'readonly': 'readonly',
        })
    )

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop("user", None)
        super().__init__(*args, **kwargs)

        source_user = self.user
        instance_user = getattr(getattr(self, "instance", None), "user", None)
        if source_user is None and instance_user is not None:
            source_user = instance_user

        profile_phone = ""
        if source_user is not None and hasattr(source_user, "profile"):
            profile_phone = source_user.profile.phone or ""

        if source_user is not None:
            self.fields["username"].initial = source_user.username
            self.fields["email"].initial = source_user.email
            self.fields["account_phone"].initial = profile_phone


class LandownerUpgradeForm(BaseUpgradeForm):
    """Form for existing users to upgrade to landowner"""
    
    class Meta:
        model = LandownerProfile
        fields = ['national_id', 'kra_pin', 'title_deed', 'land_search', 'lcb_consent']
        widgets = {
            'national_id': forms.FileInput(attrs={'class': 'form-control'}),
            'kra_pin': forms.FileInput(attrs={'class': 'form-control'}),
            'title_deed': forms.FileInput(attrs={'class': 'form-control'}),
            'land_search': forms.FileInput(attrs={'class': 'form-control'}),
            'lcb_consent': forms.FileInput(attrs={'class': 'form-control'}),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['national_id'].required = True
        self.fields['kra_pin'].required = True
        self.fields['title_deed'].required = True
        self.fields['land_search'].required = True
        self.fields['lcb_consent'].required = False
        self.order_fields([
            'username', 'email', 'account_phone', 'national_id',
            'kra_pin', 'title_deed', 'land_search', 'lcb_consent'
        ])
        
        # Add help texts
        self.fields['national_id'].help_text = "Upload your national ID (required)"
        self.fields['kra_pin'].help_text = "Upload your KRA PIN certificate (required)"
        self.fields['title_deed'].help_text = "Land title deed for verification (required)"
        self.fields['land_search'].help_text = "Official land search certificate (required)"
        self.fields['lcb_consent'].help_text = "Optional: Upload LCB consent if applicable"
    
    def save(self, user=None, commit=True):
        instance = super().save(commit=False)
        if user:
            instance.user = user
        instance.verified = False
        if commit:
            instance.save()
        return instance

    def clean(self):
        cleaned = super().clean()
        _validate_upload("National ID", cleaned.get('national_id'))
        _validate_upload("KRA PIN", cleaned.get('kra_pin'))
        _validate_upload("Title Deed", cleaned.get('title_deed'))
        _validate_upload("Land Search", cleaned.get('land_search'))
        _validate_upload("LCB Consent", cleaned.get('lcb_consent'))
        return cleaned


class AgentUpgradeForm(BaseUpgradeForm):
    """Form for existing users to upgrade to agent"""
    
    # Add all required professional fields
    id_number = forms.CharField(
        max_length=20,
        required=True,
        help_text="National ID number",
        widget=forms.TextInput(attrs={'class': 'form-control'})
    )
    kra_pin = forms.FileField(
        required=True,
        help_text="Upload your KRA PIN certificate",
        widget=forms.FileInput(attrs={'class': 'form-control'})
    )
    practicing_certificate = forms.FileField(
        required=False,
        help_text="Upload your practicing certificate (optional)",
        widget=forms.FileInput(attrs={'class': 'form-control'})
    )
    good_conduct = forms.FileField(
        required=False,
        help_text="Upload certificate of good conduct (optional)",
        widget=forms.FileInput(attrs={'class': 'form-control'})
    )
    professional_indemnity = forms.FileField(
        required=False,
        help_text="Upload professional indemnity insurance (optional)",
        widget=forms.FileInput(attrs={'class': 'form-control'})
    )
    
    class Meta:
        model = Agent
        fields = ['license_number', 'license_doc']
        widgets = {
            'license_number': forms.TextInput(attrs={'class': 'form-control'}),
            'license_doc': forms.FileInput(attrs={'class': 'form-control'}),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['license_number'].required = True
        self.fields['license_doc'].required = True
        
        # Reorder fields
        self.order_fields([
            'username', 'email', 'account_phone', 'id_number',
            'license_number', 'license_doc', 'kra_pin', 'practicing_certificate',
            'good_conduct', 'professional_indemnity'
        ])

    def clean(self):
        cleaned_data = super().clean()
        # Validate document uploads (Q7: robust server-side validation)
        doc_fields = [
            ('kra_pin', 10, ['.pdf', '.jpg', '.jpeg', '.png']),
            ('practicing_certificate', 10, ['.pdf', '.jpg', '.jpeg', '.png']),
            ('good_conduct', 10, ['.pdf', '.jpg', '.jpeg', '.png']),
            ('professional_indemnity', 10, ['.pdf', '.jpg', '.jpeg', '.png']),
            ('license_doc', 10, ['.pdf', '.jpg', '.jpeg', '.png']),
        ]
        for field_name, max_mb, allowed_ext in doc_fields:
            f = cleaned_data.get(field_name)
            if f:
                if f.size > max_mb * 1024 * 1024:
                    self.add_error(field_name, f"File must be under {max_mb}MB.")
                ext = os.path.splitext(getattr(f, 'name', ''))[1].lower()
                if ext and ext not in allowed_ext:
                    self.add_error(field_name, "Allowed: PDF, JPG, PNG.")
        return cleaned_data
    
    def save(self, user=None, commit=True):
        instance = super().save(commit=False)
        if user:
            instance.user = user
            instance.id_number = self.cleaned_data.get('id_number', '')
            if hasattr(user, "profile") and user.profile.phone:
                instance.phone = user.profile.phone
        
        # Save file fields
        if self.cleaned_data.get('kra_pin'):
            instance.kra_pin = self.cleaned_data['kra_pin']
        if self.cleaned_data.get('practicing_certificate'):
            instance.practicing_certificate = self.cleaned_data['practicing_certificate']
        if self.cleaned_data.get('good_conduct'):
            instance.good_conduct = self.cleaned_data['good_conduct']
        if self.cleaned_data.get('professional_indemnity'):
            instance.professional_indemnity = self.cleaned_data['professional_indemnity']
        
        instance.verified = False
        if commit:
            instance.save()
        return instance

    def clean(self):
        cleaned = super().clean()
        _validate_upload("KRA PIN", cleaned.get('kra_pin'))
        _validate_upload("License Document", cleaned.get('license_doc'))
        _validate_upload("Practicing Certificate", cleaned.get('practicing_certificate'))
        _validate_upload("Good Conduct", cleaned.get('good_conduct'))
        _validate_upload("Professional Indemnity", cleaned.get('professional_indemnity'))
        return cleaned


# ============ PLOT FORMS ============
# forms.py
import os
from decimal import Decimal, InvalidOperation
from django import forms
from .models import Plot, Agent, LandownerProfile
from .kenya_data import KENYA_COUNTIES, KENYA_SUB_COUNTIES

class PlotForm(forms.ModelForm):
    # Soil type choices
    SOIL_TYPE_CHOICES = [
        ('', 'Select Soil Type'),
        ('Loam', 'Loam'),
        ('Clay', 'Clay'),
        ('Sandy', 'Sandy'),
        ('Silty', 'Silty'),
        ('Peaty', 'Peaty'),
        ('Chalky', 'Chalky'),
        ('Clay Loam', 'Clay Loam'),
        ('Sandy Loam', 'Sandy Loam'),
        ('Silty Loam', 'Silty Loam'),
        ('Volcanic', 'Volcanic'),
        ('Other', 'Other'),
    ]
    
    # Listing type choices
    LISTING_TYPE_CHOICES = [
        ('sale', 'For Sale'),
        ('lease', 'For Lease'),
        ('both', 'For Sale & Lease'),
    ]
    
    # Land type choices
    LAND_TYPE_CHOICES = [
        ('agricultural', 'Agricultural Land'),
        ('residential', 'Residential Plot'),
        ('commercial', 'Commercial Land'),
        ('mixed_use', 'Mixed Use'),
        ('industrial', 'Industrial Land'),
    ]
    
    # Kenyan county and subcounty fields - make them not required at form level
    # since they're now model fields
    county = forms.ChoiceField(
        choices=[('', '-- Select County --')] + [(c, c) for c in KENYA_COUNTIES],
        required=True,
        widget=forms.Select(attrs={
            'class': 'form-control county-select',
            'id': 'id_county'
        })
    )
    
    subcounty = forms.ChoiceField(
        choices=[('', '-- Select Sub-county --')],
        required=True,
        widget=forms.Select(attrs={
            'class': 'form-control subcounty-select',
            'id': 'id_subcounty'
        })
    )
    
    # Keep location field but make it optional (will be auto-generated)
    location = forms.CharField(
        required=False,
        widget=forms.HiddenInput(),
        help_text="Auto-generated from county and subcounty"
    )
    
    # Add new fields for enhanced plot details
    listing_type = forms.ChoiceField(
        choices=LISTING_TYPE_CHOICES,
        required=True,
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    
    land_type = forms.ChoiceField(
        choices=LAND_TYPE_CHOICES,
        required=True,
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    
    land_use_description = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        help_text="Describe the current use of this land"
    )

    parcel_number = forms.CharField(
        required=True,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'e.g., REGISTRY/BLOCK/PARCEL or LR 1234/567'
        }),
        help_text="Parcel/Title/LR number used for official searches"
    )
    is_subdivision = forms.BooleanField(
        required=False,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        help_text="Check if you are selling a portion of a larger parcel"
    )
    original_parcel_number = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control'}),
        help_text="Original parcel number (required for subdivision listings)"
    )

    registration_section = forms.CharField(
        required=True,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'e.g., Nairobi/Block 10'
        }),
        help_text="Registration section / registry block"
    )
    search_certificate_date = forms.DateField(
        required=True,
        widget=forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
        help_text="Official land search date (must be within 30 days)"
    )
    search_reference_number = forms.CharField(
        required=True,
        widget=forms.TextInput(attrs={'class': 'form-control'}),
        help_text="Reference number from the official search certificate"
    )
    owner_full_name = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control'}),
        help_text="Registered owner's name as per title/search"
    )
    owner_id_number = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control'}),
        help_text="Registered owner's national ID number"
    )
    owner_kra_pin_number = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control'}),
        help_text="Registered owner's KRA PIN number"
    )
    spousal_consent = forms.BooleanField(
        required=False,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'})
    )
    
    # Sale fields
    sale_price = forms.DecimalField(
        required=False,
        max_digits=12,
        decimal_places=2,
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'placeholder': 'e.g., 5000000',
            'min': '0',
            'step': '0.01'
        }),
        help_text="Price if selling (KES)"
    )
    
    price_per_acre = forms.DecimalField(
        required=False,
        max_digits=12,
        decimal_places=2,
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'placeholder': 'Auto-calculated',
            'readonly': 'readonly',
            'step': '0.01'
        }),
        help_text="Price per unit (auto-calculated based on acres/hectares)"
    )
    
    # Lease fields
    lease_price_monthly = forms.DecimalField(
        required=False,
        max_digits=10,
        decimal_places=2,
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'placeholder': 'e.g., 50000',
            'min': '0',
            'step': '0.01'
        }),
        help_text="Monthly lease price (KES)"
    )
    
    lease_price_yearly = forms.DecimalField(
        required=False,
        max_digits=10,
        decimal_places=2,
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'placeholder': 'e.g., 500000',
            'min': '0',
            'step': '0.01'
        }),
        help_text="Yearly lease price (KES)"
    )
    
    lease_duration = forms.ChoiceField(
        choices=Plot.LEASE_DURATION_CHOICES,
        required=False,
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    
    lease_terms = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        help_text="Specific lease conditions and restrictions"
    )

    area_unit = forms.ChoiceField(
        choices=Plot.AREA_UNIT_CHOICES,
        required=True,
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    ownership_type = forms.ChoiceField(
        choices=Plot._meta.get_field('ownership_type').choices,
        required=True,
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    tenure_details = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control'}),
        help_text="Lease duration/expiry or tenure notes"
    )
    encumbrances = forms.BooleanField(
        required=False,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'})
    )
    encumbrance_details = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 2})
    )
    nearest_town = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control'})
    )
    ward = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g., Mauche, Kiamaina, Bahati'})
    )
    price_basis = forms.ChoiceField(
        choices=Plot.PRICE_BASIS_CHOICES,
        required=True,
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    valuation_report = forms.FileField(
        required=False,
        widget=forms.ClearableFileInput(attrs={'class': 'form-control', 'accept': '.pdf,.jpg,.jpeg,.png'})
    )
    price_notes = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
        help_text="Optional notes on market trends or negotiation"
    )
    is_price_negotiable = forms.BooleanField(
        required=False,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'})
    )
    lease_basis = forms.ChoiceField(
        choices=Plot.PRICE_BASIS_CHOICES,
        required=True,
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    
    # Infrastructure fields
    has_water = forms.BooleanField(
        required=False,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'})
    )
    
    water_source = forms.ChoiceField(
        choices=Plot.WATER_SOURCE_CHOICES,
        required=False,
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    
    has_electricity = forms.BooleanField(
        required=False,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'})
    )
    
    electricity_meter = forms.BooleanField(
        required=False,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        help_text="Has meter installed"
    )
    
    has_road_access = forms.BooleanField(
        required=False,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'})
    )
    
    road_type = forms.ChoiceField(
        choices=Plot.ROAD_TYPE_CHOICES,
        required=False,
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    
    road_distance_km = forms.DecimalField(
        required=False,
        max_digits=5,
        decimal_places=2,
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'placeholder': 'e.g., 0.5',
            'min': '0',
            'step': '0.1'
        }),
        help_text="Distance to main road (km)"
    )
    
    has_buildings = forms.BooleanField(
        required=False,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'})
    )
    
    building_description = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
        help_text="Describe any buildings or structures"
    )

    other_amenities = forms.CharField(
        required=False,
        widget=forms.Textarea(
            attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Any other useful infrastructure or amenities, e.g. borehole pump house, irrigation lines, staff quarters, storage shed...',
            }
        ),
        help_text="Optional: list any other amenities not already covered above."
    )
    
    fencing = forms.ChoiceField(
        choices=Plot.FENCING_CHOICES,
        required=False,
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    topography = forms.ChoiceField(
        choices=[("", "Select topography")] + list(Plot.TOPOGRAPHY_CHOICES),
        required=False,
        widget=forms.Select(attrs={'class': 'form-control'})
    )

    survey_map = forms.FileField(
        required=False,
        widget=forms.ClearableFileInput(attrs={'class': 'form-control', 'accept': '.pdf,.jpg,.jpeg,.png'})
    )
    spousal_consent_doc = forms.FileField(
        required=False,
        widget=forms.ClearableFileInput(attrs={'class': 'form-control', 'accept': '.pdf,.jpg,.jpeg,.png'})
    )
    rates_clearance = forms.FileField(
        required=False,
        widget=forms.ClearableFileInput(attrs={'class': 'form-control', 'accept': '.pdf,.jpg,.jpeg,.png'})
    )
    rent_clearance = forms.FileField(
        required=False,
        widget=forms.ClearableFileInput(attrs={'class': 'form-control', 'accept': '.pdf,.jpg,.jpeg,.png'})
    )
    lcb_consent_doc = forms.FileField(
        required=False,
        widget=forms.ClearableFileInput(attrs={'class': 'form-control', 'accept': '.pdf,.jpg,.jpeg,.png'})
    )
    plupa1_form = forms.FileField(
        required=False,
        widget=forms.ClearableFileInput(attrs={'class': 'form-control', 'accept': '.pdf,.jpg,.jpeg,.png'})
    )
    consent_to_transfer = forms.FileField(
        required=False,
        widget=forms.ClearableFileInput(attrs={'class': 'form-control', 'accept': '.pdf,.jpg,.jpeg,.png'})
    )
    
    class Meta:
        model = Plot
        fields = [
            'title', 'county', 'subcounty', 'ward', 'market_zone', 'location', 'area', 'area_unit', 'parcel_number', 'is_subdivision',
            'original_parcel_number', 'registration_section',
            'search_certificate_date', 'search_reference_number',
            'owner_full_name', 'owner_id_number', 'owner_kra_pin_number', 'spousal_consent',
            'listing_type', 'land_type',
            'land_use_description', 'nearest_town',
            'soil_type', 'topography', 'ph_level', 'crop_suitability',
            'ownership_type', 'tenure_details', 'encumbrances', 'encumbrance_details',
            'sale_price', 'price_per_acre',
            'lease_price_monthly', 'lease_price_yearly', 'lease_duration', 'lease_terms',
            'price_basis', 'valuation_report', 'price_notes', 'is_price_negotiable', 'price_review_required', 'pricing_override_reason', 'lease_basis', 'government_price_proof',
            'has_water', 'water_source', 'has_electricity', 'electricity_meter',
            'has_road_access', 'road_type', 'road_distance_km',
            'has_buildings', 'building_description', 'other_amenities', 'fencing',
            'title_deed', 'survey_map', 'spousal_consent_doc',
            'official_search', 'rates_clearance', 'rent_clearance',
            'lcb_consent_doc', 'plupa1_form', 'consent_to_transfer',
            'landowner_id_doc', 'kra_pin'
        ]
        widgets = {
            'title': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'e.g., 5-Acre Fertile Farm in Kitale'
            }),
            'area': forms.NumberInput(attrs={
                'class': 'form-control',
                'placeholder': 'e.g., 5.0',
                'min': '0',
                'step': '0.1'
            }),
            'market_zone': forms.Select(attrs={'class': 'form-control'}),
            'pricing_override_reason': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'title_deed': forms.ClearableFileInput(attrs={
                'class': 'form-control',
                'accept': '.pdf,.jpg,.jpeg,.png'
            }),
            'survey_map': forms.ClearableFileInput(attrs={
                'class': 'form-control',
                'accept': '.pdf,.jpg,.jpeg,.png'
            }),
            'spousal_consent_doc': forms.ClearableFileInput(attrs={
                'class': 'form-control',
                'accept': '.pdf,.jpg,.jpeg,.png'
            }),
            'official_search': forms.ClearableFileInput(attrs={
                'class': 'form-control',
                'accept': '.pdf,.jpg,.jpeg,.png'
            }),
            'rates_clearance': forms.ClearableFileInput(attrs={
                'class': 'form-control',
                'accept': '.pdf,.jpg,.jpeg,.png'
            }),
            'rent_clearance': forms.ClearableFileInput(attrs={
                'class': 'form-control',
                'accept': '.pdf,.jpg,.jpeg,.png'
            }),
            'lcb_consent_doc': forms.ClearableFileInput(attrs={
                'class': 'form-control',
                'accept': '.pdf,.jpg,.jpeg,.png'
            }),
            'plupa1_form': forms.ClearableFileInput(attrs={
                'class': 'form-control',
                'accept': '.pdf,.jpg,.jpeg,.png'
            }),
            'consent_to_transfer': forms.ClearableFileInput(attrs={
                'class': 'form-control',
                'accept': '.pdf,.jpg,.jpeg,.png'
            }),
            'search_certificate_date': forms.DateInput(attrs={
                'type': 'date',
                'class': 'form-control'
            }),
            'search_reference_number': forms.TextInput(attrs={
                'class': 'form-control'
            }),
            'landowner_id_doc': forms.ClearableFileInput(attrs={
                'class': 'form-control',
                'accept': '.pdf,.jpg,.jpeg,.png'
            }),
            'kra_pin': forms.ClearableFileInput(attrs={
                'class': 'form-control',
                'accept': '.pdf,.jpg,.jpeg,.png'
            }),
            'government_price_proof': forms.ClearableFileInput(attrs={
                'class': 'form-control',
                'accept': '.pdf,.jpg,.jpeg,.png'
            }),
        }
    
    def __init__(self, *args, **kwargs):
        # Pop owner from kwargs if provided
        self.owner = kwargs.pop('owner', None)
        self.user = kwargs.pop('user', None)
        self.is_edit = kwargs.get('instance', None) is not None
        super().__init__(*args, **kwargs)
        
        # If this is a POST request, update subcounty choices based on submitted county
        if self.data.get('county'):
            county = self.data.get('county')
            if county in KENYA_SUB_COUNTIES:
                self.fields['subcounty'].choices = [('', '-- Select Sub-county --')] + [
                    (sc, sc) for sc in KENYA_SUB_COUNTIES[county]
                ]
        
        # If editing an existing plot, set county and subcounty values
        elif self.instance and self.instance.county and self.instance.subcounty:
            self.fields['county'].initial = self.instance.county
            # Update subcounty choices for this county
            if self.instance.county in KENYA_SUB_COUNTIES:
                self.fields['subcounty'].choices = [('', '-- Select Sub-county --')] + [
                    (sc, sc) for sc in KENYA_SUB_COUNTIES[self.instance.county]
                ]
                self.fields['subcounty'].initial = self.instance.subcounty
        
        def _value(field_name, default=None):
            if field_name in self.data:
                return self.data.get(field_name) or default
            if self.instance and getattr(self.instance, field_name, None) is not None:
                return getattr(self.instance, field_name)
            return default

        # Set required fields for creation vs edit
        if not self.is_edit:
            land_type_value = _value('land_type')
            ownership_type_value = _value('ownership_type')
            is_subdivision_value = bool(_value('is_subdivision'))
            spousal_consent_value = bool(_value('spousal_consent'))

            required_docs = [
                'title_deed',
                'official_search',
                'landowner_id_doc',
                'kra_pin',
                'rates_clearance',
            ]
            if land_type_value == 'agricultural':
                required_docs.append('lcb_consent_doc')
            if is_subdivision_value:
                required_docs.extend(['survey_map', 'plupa1_form'])
            if ownership_type_value == 'leasehold':
                required_docs.extend(['rent_clearance', 'consent_to_transfer'])
            if spousal_consent_value:
                required_docs.append('spousal_consent_doc')

            for doc_field in required_docs:
                if doc_field in self.fields:
                    self.fields[doc_field].required = True

            if 'owner_full_name' in self.fields:
                self.fields['owner_full_name'].required = True
            if 'owner_id_number' in self.fields:
                self.fields['owner_id_number'].required = True
            if 'owner_kra_pin_number' in self.fields:
                self.fields['owner_kra_pin_number'].required = True
            if 'search_certificate_date' in self.fields:
                self.fields['search_certificate_date'].required = True
            if 'search_reference_number' in self.fields:
                self.fields['search_reference_number'].required = True
            
            # Listing type is required
            self.fields['listing_type'].required = True
            self.fields['land_type'].required = True
        else:
            # For editing, documents are optional (allow updates)
            if 'parcel_number' in self.fields:
                self.fields['parcel_number'].required = False
            if 'registration_section' in self.fields:
                self.fields['registration_section'].required = False
            if 'search_certificate_date' in self.fields:
                self.fields['search_certificate_date'].required = False
            if 'search_reference_number' in self.fields:
                self.fields['search_reference_number'].required = False
        
        # Add help texts
        self.fields['title'].help_text = "Give your plot a descriptive title"
        self.fields['county'].help_text = "Select the county where your plot is located"
        self.fields['subcounty'].help_text = "Select the specific sub-county"
        self.fields['ward'].help_text = "Optional but recommended for hyper-local search trust."
        self.fields['market_zone'].help_text = "Tell AgriPlot whether this land is rural, peri-urban, or urban for pricing guidance."
        self.fields['area'].help_text = "Land area value"
        self.fields['area_unit'].help_text = "Select acres or hectares"
        self.fields['parcel_number'].help_text = "Parcel/Title/LR number used for official search"
        self.fields['registration_section'].help_text = "Registry/Block as shown on the title (e.g., Nairobi/Block 10)"
        self.fields['owner_full_name'].help_text = "Registered owner's name (as per title/land search)"
        self.fields['owner_id_number'].help_text = "Registered owner's national ID number"
        self.fields['owner_kra_pin_number'].help_text = "Registered owner's KRA PIN number"
        self.fields['price_basis'].help_text = "How was the selling price determined?"
        self.fields['lease_basis'].help_text = "How was the lease price determined?"
        self.fields['topography'].help_text = "Describe the slope of the land for farming and access decisions."
        self.fields['valuation_report'].help_text = "Optional valuation report (PDF/Image)"
        self.fields['price_notes'].help_text = "Optional notes about market demand or negotiations"
        self.fields['price_review_required'].help_text = "Automatically turned on when your asking price goes beyond the regional guide."
        self.fields['pricing_override_reason'].help_text = "Explain boreholes, greenhouses, fencing, or any other value additions if you are above the guide."
        self.fields['other_amenities'].help_text = "Optional: mention any extra amenities or access features not captured above."
        self.fields['ownership_type'].help_text = "Legal tenure status"
        self.fields['encumbrance_details'].help_text = "Specify any caveats, loans, or disputes"
        self.fields['title_deed'].help_text = "Upload title deed document (PDF/Image, max 20MB)"
        self.fields['survey_map'].help_text = "Upload survey map or mutation form (PDF/Image, max 20MB)"
        self.fields['spousal_consent_doc'].help_text = "Upload spousal consent document if applicable"
        if 'soil_report' in self.fields:
            self.fields['soil_report'].help_text = "Upload soil test report (PDF/Image, max 20MB, optional)"
        self.fields['official_search'].help_text = "Official land search certificate (PDF/Image, max 20MB)"
        self.fields['rates_clearance'].help_text = "Land rates clearance certificate (PDF/Image, max 20MB)"
        self.fields['rent_clearance'].help_text = "Land rent clearance certificate (PDF/Image, max 20MB)"
        if 'lcb_consent_doc' in self.fields:
            self.fields['lcb_consent_doc'].help_text = "Land Control Board consent (PDF/Image, max 20MB)"
        if 'plupa1_form' in self.fields:
            self.fields['plupa1_form'].help_text = "PLUPA 1 / PPA 1 approval form (PDF/Image, max 20MB)"
        if 'consent_to_transfer' in self.fields:
            self.fields['consent_to_transfer'].help_text = "Consent to transfer (PDF/Image, max 20MB)"
        self.fields['landowner_id_doc'].help_text = "Landowner's national ID (PDF/Image, max 20MB)"
        self.fields['kra_pin'].help_text = "Landowner's KRA PIN certificate (PDF/Image, max 20MB)"
        self.fields['price_review_required'].widget = forms.HiddenInput()
        self.price_band_guidance = {
            'sale': self._build_price_guidance('sale'),
            'lease': self._build_price_guidance('lease'),
        }
        self.pricing_suggestions = {
            'sale': self._build_pricing_suggestion('sale'),
            'lease': self._build_pricing_suggestion('lease'),
        }

    def _build_price_guidance(self, listing_type):
        county = self.data.get('county') or getattr(self.instance, 'county', None)
        subcounty = self.data.get('subcounty') or getattr(self.instance, 'subcounty', None)
        market_zone = self.data.get('market_zone') or getattr(self.instance, 'market_zone', 'rural')
        land_type = self.data.get('land_type') or getattr(self.instance, 'land_type', None)
        if not county or not land_type:
            return None
        queryset = MarketPriceBand.objects.filter(
            county=county,
            land_type=land_type,
            listing_type=listing_type,
            market_zone=market_zone,
            is_active=True,
        )
        band = None
        if subcounty:
            band = queryset.filter(subcounty=subcounty).order_by('-effective_from').first()
        if band is None:
            band = queryset.filter(subcounty__in=['', None]).order_by('-effective_from').first()
        if not band:
            return None
        return {
            'county': county,
            'subcounty': subcounty or '',
            'market_zone': market_zone,
            'land_type': land_type,
            'area_unit': band.area_unit,
            'min_price_per_unit': band.min_price_per_unit,
            'max_price_per_unit': band.max_price_per_unit,
            'source': band.source,
            'notes': band.notes,
        }

    def _build_pricing_suggestion(self, listing_type):
        source = self.instance if getattr(self.instance, "pk", None) else Plot()
        raw_area = self.data.get('area') or getattr(self.instance, 'area', None)
        raw_area_unit = self.data.get('area_unit') or getattr(self.instance, 'area_unit', 'acres')
        raw_county = self.data.get('county') or getattr(self.instance, 'county', None)
        raw_subcounty = self.data.get('subcounty') or getattr(self.instance, 'subcounty', None)
        raw_market_zone = self.data.get('market_zone') or getattr(self.instance, 'market_zone', 'rural')
        raw_land_type = self.data.get('land_type') or getattr(self.instance, 'land_type', None)
        raw_soil_type = self.data.get('soil_type') or getattr(self.instance, 'soil_type', '')
        raw_sale_price = self.data.get('sale_price') or getattr(self.instance, 'sale_price', None)
        raw_lease_yearly = self.data.get('lease_price_yearly') or getattr(self.instance, 'lease_price_yearly', None)
        raw_lease_monthly = self.data.get('lease_price_monthly') or getattr(self.instance, 'lease_price_monthly', None)

        try:
            source.area = Decimal(str(raw_area)) if raw_area not in {None, ''} else None
        except (InvalidOperation, TypeError, ValueError):
            source.area = None

        source.area_unit = raw_area_unit or 'acres'
        source.county = raw_county
        source.subcounty = raw_subcounty
        source.market_zone = raw_market_zone or 'rural'
        source.land_type = raw_land_type
        source.soil_type = raw_soil_type or ''
        source.listing_type = listing_type

        try:
            source.sale_price = Decimal(str(raw_sale_price)) if raw_sale_price not in {None, ''} else None
        except (InvalidOperation, TypeError, ValueError):
            source.sale_price = None
        try:
            source.lease_price_yearly = Decimal(str(raw_lease_yearly)) if raw_lease_yearly not in {None, ''} else None
        except (InvalidOperation, TypeError, ValueError):
            source.lease_price_yearly = None
        try:
            source.lease_price_monthly = Decimal(str(raw_lease_monthly)) if raw_lease_monthly not in {None, ''} else None
        except (InvalidOperation, TypeError, ValueError):
            source.lease_price_monthly = None

        return source.pricing_recommendation(listing_type)
    
    def clean(self):
        """Validate all form data with comprehensive error checking"""
        cleaned_data = super().clean()
        
        # Track validation errors for logging
        validation_errors = []
        
        # =========================================================================
        # LOCATION VALIDATION (County & Subcounty)
        # =========================================================================
        county = cleaned_data.get('county')
        subcounty = cleaned_data.get('subcounty')
        
        logger.debug(f"Validating location - County: {county}, Subcounty: {subcounty}")
        
        # County validation
        if not county:
            error_msg = 'Please select a county'
            self.add_error('county', error_msg)
            validation_errors.append(f"county: {error_msg}")
            validation_logger.warning(f"County not selected")
        elif county not in KENYA_COUNTIES:
            error_msg = f'Invalid county selected: "{county}" is not a valid Kenyan county'
            self.add_error('county', error_msg)
            validation_errors.append(f"county: {error_msg}")
            validation_logger.error(f"Invalid county selected: {county}")
        
        # Subcounty validation
        if not subcounty:
            error_msg = 'Please select a sub-county'
            self.add_error('subcounty', error_msg)
            validation_errors.append(f"subcounty: {error_msg}")
            validation_logger.warning(f"Subcounty not selected")
        elif county and subcounty:
            # Validate that subcounty belongs to selected county
            valid_subcounties = KENYA_SUB_COUNTIES.get(county, [])
            if subcounty not in valid_subcounties:
                error_msg = f'"{subcounty}" is not a valid sub-county for {county}'
                self.add_error('subcounty', error_msg)
                validation_errors.append(f"subcounty: {error_msg}")
                validation_logger.error(f"Invalid subcounty '{subcounty}' for county '{county}'")
                validation_logger.debug(f"Valid subcounties for {county}: {valid_subcounties}")
        
        # Combine county and subcounty into location field for backward compatibility
        ward = cleaned_data.get('ward')
        if county and subcounty:
            location_parts = [county, subcounty]
            if ward:
                location_parts.append(ward)
            cleaned_data['location'] = " - ".join(location_parts)
            logger.debug(f"Generated location: {cleaned_data['location']}")
        
        # =========================================================================
        # OWNER VALIDATION
        # =========================================================================
        parcel_number = cleaned_data.get('parcel_number')
        registration_section = cleaned_data.get('registration_section')
        search_certificate_date = cleaned_data.get('search_certificate_date')
        search_reference_number = cleaned_data.get('search_reference_number')
        owner_full_name = cleaned_data.get('owner_full_name')
        owner_id_number = cleaned_data.get('owner_id_number')
        owner_kra_pin_number = cleaned_data.get('owner_kra_pin_number')
        is_subdivision = cleaned_data.get('is_subdivision')
        original_parcel_number = cleaned_data.get('original_parcel_number')
        area = cleaned_data.get('area')
        area_unit = cleaned_data.get('area_unit') or 'acres'
        spousal_consent = cleaned_data.get('spousal_consent')
        spousal_consent_doc = cleaned_data.get('spousal_consent_doc')
        
        def _norm(value):
            return (value or "").strip().lower()

        require_parcel = not self.is_edit

        if parcel_number:
            try:
                cleaned_data['parcel_number'] = _validate_parcel_number(parcel_number)
            except forms.ValidationError as e:
                self.add_error('parcel_number', e)
                validation_errors.append(f"parcel_number: {e}")
        elif require_parcel:
            self.add_error('parcel_number', "Parcel number is required.")
            validation_errors.append("parcel_number: required")

        if not registration_section and require_parcel:
            self.add_error('registration_section', "Registration section is required.")
            validation_errors.append("registration_section: required")

        if require_parcel:
            if not search_certificate_date:
                self.add_error('search_certificate_date', "Search certificate date is required.")
                validation_errors.append("search_certificate_date: required")
            if not search_reference_number:
                self.add_error('search_reference_number', "Search reference number is required.")
                validation_errors.append("search_reference_number: required")

        if search_certificate_date:
            today = timezone.localdate()
            if search_certificate_date > today:
                self.add_error('search_certificate_date', "Search certificate date cannot be in the future.")
                validation_errors.append("search_certificate_date: future date")
            else:
                age_days = (today - search_certificate_date).days
                if age_days > 30:
                    self.add_error(
                        'search_certificate_date',
                        "Search certificate is older than 30 days. Upload a recent search."
                    )
                    validation_errors.append("search_certificate_date: older than 30 days")

        if is_subdivision and not original_parcel_number:
            self.add_error('original_parcel_number', "Original parcel number is required for subdivisions.")
            validation_errors.append("original_parcel_number: required when subdivision is checked")

        if spousal_consent and not spousal_consent_doc:
            self.add_error('spousal_consent_doc', "Upload spousal consent document.")
            validation_errors.append("spousal_consent_doc: required when consent is checked")

        land_type = cleaned_data.get('land_type')
        ownership_type = cleaned_data.get('ownership_type')
        if land_type == 'agricultural' and not cleaned_data.get('lcb_consent_doc'):
            self.add_error('lcb_consent_doc', "LCB consent is required for agricultural land.")
            validation_errors.append("lcb_consent_doc: required for agricultural land")
        if is_subdivision:
            if not cleaned_data.get('survey_map'):
                self.add_error('survey_map', "Mutation/survey map is required for subdivision listings.")
                validation_errors.append("survey_map: required for subdivision")
            if not cleaned_data.get('plupa1_form'):
                self.add_error('plupa1_form', "PLUPA 1 / PPA 1 approval form is required for subdivision.")
                validation_errors.append("plupa1_form: required for subdivision")
        if ownership_type == 'leasehold':
            if not cleaned_data.get('rent_clearance'):
                self.add_error('rent_clearance', "Land rent clearance is required for leasehold plots.")
                validation_errors.append("rent_clearance: required for leasehold")
            if not cleaned_data.get('consent_to_transfer'):
                self.add_error('consent_to_transfer', "Consent to transfer is required for leasehold plots.")
                validation_errors.append("consent_to_transfer: required for leasehold")

        if self.owner and not self.is_edit:
            try:
                if isinstance(self.owner, Agent):
                    self.instance.agent = self.owner
                    logger.debug(f"Set agent owner: {self.owner.id}")
                elif isinstance(self.owner, LandownerProfile):
                    self.instance.landowner = self.owner
                    logger.debug(f"Set landowner owner: {self.owner.id}")
            except Exception as e:
                error_msg = f"Error setting owner: {str(e)}"
                logger.error(error_msg, exc_info=True)
                raise ValidationError(error_msg)

        if parcel_number:
            existing = Plot.objects.filter(parcel_number__iexact=parcel_number)
            if self.instance and self.instance.pk:
                existing = existing.exclude(pk=self.instance.pk)
            if existing.exists():
                error_msg = "This parcel number is already listed."
                self.add_error('parcel_number', error_msg)
                validation_errors.append(f"parcel_number: {error_msg}")

        # Registry verification (only for new listings)
        if require_parcel and parcel_number:
            mismatch_count = RegistryMismatchAttempt.objects.filter(
                parcel_number__iexact=parcel_number
            ).count()
            if mismatch_count >= 3:
                raise forms.ValidationError(
                    "This parcel number has been flagged for repeated mismatches. Contact support."
                )

            registry_result = verify_with_registry(parcel_number)
            if not registry_result.get("verified"):
                message = registry_result.get("message") or "Registry verification failed."
                validation_logger.warning(
                    "Registry verification failed for parcel=%s reason=%s",
                    parcel_number,
                    message
                )
                try:
                    RegistryMismatchAttempt.objects.create(
                        parcel_number=parcel_number,
                        provided_owner_name=owner_full_name or "",
                        provided_owner_id=owner_id_number or "",
                        user=self.user,
                        reason=message
                    )
                except Exception:
                    pass
                raise forms.ValidationError(f"Legal verification failed: {message}")

            # Store a JSON-serializable subset for audit trails
            record = registry_result.get("record")
            record_data = {}
            if record:
                record_data = {
                    "parcel_number": record.parcel_number,
                    "registered_owner_name": record.registered_owner_name,
                    "owner_id_number": record.owner_id_number,
                    "owner_kra_pin": record.owner_kra_pin,
                    "county": record.county,
                    "subcounty": record.subcounty,
                    "registration_section": record.registration_section,
                    "search_reference_number": record.search_reference_number,
                    "search_certificate_date": record.search_certificate_date.isoformat() if record.search_certificate_date else None,
                    "acreage_ha": float(record.acreage_ha) if record.acreage_ha is not None else None,
                    "land_type": record.land_type,
                    "is_charged": bool(record.is_charged),
                    "has_caution": bool(record.has_caution),
                }
                if owner_full_name and _norm(owner_full_name) != _norm(record.registered_owner_name):
                    self.add_error('owner_full_name', "Owner name must match registry.")
                    validation_errors.append("owner_full_name: registry mismatch")
                if owner_id_number and _norm(owner_id_number) != _norm(record.owner_id_number):
                    self.add_error('owner_id_number', "Owner ID must match registry.")
                    validation_errors.append("owner_id_number: registry mismatch")
                if owner_kra_pin_number and record.owner_kra_pin and _norm(owner_kra_pin_number) != _norm(record.owner_kra_pin):
                    self.add_error('owner_kra_pin_number', "Owner KRA PIN must match registry.")
                    validation_errors.append("owner_kra_pin_number: registry mismatch")
                if record.county and county and _norm(county) != _norm(record.county):
                    self.add_error('county', "County must match registry.")
                    validation_errors.append("county: registry mismatch")
                if record.subcounty and subcounty and _norm(subcounty) != _norm(record.subcounty):
                    self.add_error('subcounty', "Sub-county must match registry.")
                    validation_errors.append("subcounty: registry mismatch")
                if record.registration_section and registration_section and _norm(registration_section) != _norm(record.registration_section):
                    self.add_error('registration_section', "Registration section must match registry.")
                    validation_errors.append("registration_section: registry mismatch")
                if record.search_reference_number and search_reference_number and _norm(search_reference_number) != _norm(record.search_reference_number):
                    self.add_error('search_reference_number', "Search reference must match registry.")
                    validation_errors.append("search_reference_number: registry mismatch")
                if record.search_certificate_date and search_certificate_date and record.search_certificate_date != search_certificate_date:
                    self.add_error('search_certificate_date', "Search date must match registry.")
                    validation_errors.append("search_certificate_date: registry mismatch")

                cleaned_data['owner_full_name'] = record.registered_owner_name
                cleaned_data['owner_id_number'] = record.owner_id_number
                cleaned_data['owner_kra_pin_number'] = record.owner_kra_pin
                if record.county:
                    cleaned_data['county'] = record.county
                    county = record.county
                if record.subcounty:
                    cleaned_data['subcounty'] = record.subcounty
                    subcounty = record.subcounty
                if record.registration_section:
                    cleaned_data['registration_section'] = record.registration_section
                if record.search_reference_number:
                    cleaned_data['search_reference_number'] = record.search_reference_number
                if record.search_certificate_date:
                    cleaned_data['search_certificate_date'] = record.search_certificate_date
                if record.county and record.subcounty:
                    cleaned_data['location'] = f"{record.county} - {record.subcounty}"
                self.instance.registry_owner_name = record.registered_owner_name
                self.instance.registry_owner_id_number = record.owner_id_number
                self.instance.registry_owner_kra_pin = record.owner_kra_pin
                self.instance.registry_area_ha = record.acreage_ha
                self.instance.registry_land_type = record.land_type
                self.instance.registry_has_encumbrances = bool(record.is_charged or record.has_caution)
                self.instance.is_subdivision = bool(is_subdivision)
                self.instance.original_parcel_number = original_parcel_number or ""
            self.registry_result = {
                "verified": bool(registry_result.get("verified")),
                "message": registry_result.get("message"),
                "has_encumbrances": bool(registry_result.get("has_encumbrances")),
                "record": record_data,
            }
            if registry_result.get("has_encumbrances"):
                cleaned_data["__registry_has_encumbrance"] = True

            # Extra alignment checks: ownership type and acreage (if provided)
            if record:
                ownership_type = cleaned_data.get("ownership_type")
                if ownership_type in ("freehold", "leasehold"):
                    expected = "FREEHOLD" if ownership_type == "freehold" else "LEASEHOLD"
                    if record.land_type != expected:
                        raise forms.ValidationError(
                            f"Legal verification failed: title type mismatch (registry: {record.land_type})."
                        )
                # Compare area to registry within tolerance (5%)
                if area is not None:
                    area_ha = None
                    try:
                        area_val = float(area)
                        if area_unit == "hectares":
                            area_ha = area_val
                        elif area_unit == "acres":
                            area_ha = area_val / 2.47105
                    except (TypeError, ValueError):
                        area_ha = None
                    if area_ha and record.acreage_ha:
                        registry_ha = float(record.acreage_ha)
                        if registry_ha > 0:
                            diff_ratio = abs(area_ha - registry_ha) / registry_ha
                            if diff_ratio > 0.05 and not is_subdivision:
                                raise forms.ValidationError(
                                    "Area differs from registry by more than 5%. Use subdivision and upload a mutation map."
                                )
                            if is_subdivision and not cleaned_data.get('survey_map'):
                                self.add_error('survey_map', "Mutation/survey map is required for subdivision listings.")
                                validation_errors.append("survey_map: required for subdivision")

        # =========================================================================
        # LISTING TYPE AND PRICE VALIDATION
        # =========================================================================
        listing_type = cleaned_data.get('listing_type')
        sale_price = cleaned_data.get('sale_price')
        lease_price_monthly = cleaned_data.get('lease_price_monthly')
        lease_price_yearly = cleaned_data.get('lease_price_yearly')
        price_basis = cleaned_data.get('price_basis')
        lease_basis = cleaned_data.get('lease_basis')
        valuation_report = cleaned_data.get('valuation_report')
        government_price_proof = cleaned_data.get('government_price_proof')
        price_notes = cleaned_data.get('price_notes')
        county = cleaned_data.get('county')
        subcounty = cleaned_data.get('subcounty')
        market_zone = cleaned_data.get('market_zone')
        land_type = cleaned_data.get('land_type')
        pricing_override_reason = cleaned_data.get('pricing_override_reason')
        cleaned_data['price_review_required'] = False
        if pricing_override_reason:
            cleaned_data['pricing_override_reason'] = pricing_override_reason.strip()
        # area and area_unit already captured above for registry alignment checks

        def _to_acres(value, unit):
            if value is None:
                return None
            try:
                value_float = float(value)
            except (ValueError, TypeError):
                return None
            if unit == 'hectares':
                return value_float * 2.47105
            return value_float

        area_acres = _to_acres(area, area_unit)
        
        logger.debug(f"Validating listing type: {listing_type}")
        logger.debug(f"Sale price: {sale_price}, Lease monthly: {lease_price_monthly}, Lease yearly: {lease_price_yearly}")
        
        # Validate listing type
        valid_listing_types = ['sale', 'lease', 'both']
        if listing_type and listing_type not in valid_listing_types:
            error_msg = f'Invalid listing type: {listing_type}'
            self.add_error('listing_type', error_msg)
            validation_errors.append(f"listing_type: {error_msg}")
            logger.error(error_msg)
        
        # Sale price validation
        if listing_type in ['sale', 'both']:
            if not sale_price:
                error_msg = 'Sale price is required for properties listed for sale'
                self.add_error('sale_price', error_msg)
                validation_errors.append(f"sale_price: {error_msg}")
            elif sale_price < 0:
                error_msg = 'Sale price cannot be negative'
                self.add_error('sale_price', error_msg)
                validation_errors.append(f"sale_price: {error_msg}")
        
        # Lease price validation
        if listing_type in ['lease', 'both']:
            if not lease_price_monthly and not lease_price_yearly:
                error_msg = 'Either monthly or yearly lease price is required'
                self.add_error('lease_price_monthly', error_msg)
                self.add_error('lease_price_yearly', error_msg)
                validation_errors.append(f"lease_prices: {error_msg}")
            
            # Validate lease prices are positive
            if lease_price_monthly and lease_price_monthly < 0:
                error_msg = 'Monthly lease price cannot be negative'
                self.add_error('lease_price_monthly', error_msg)
                validation_errors.append(f"lease_price_monthly: {error_msg}")
            
            if lease_price_yearly and lease_price_yearly < 0:
                error_msg = 'Yearly lease price cannot be negative'
                self.add_error('lease_price_yearly', error_msg)
                validation_errors.append(f"lease_price_yearly: {error_msg}")

        # Pricing basis validation
        if price_basis == 'valuation_report' and not valuation_report:
            self.add_error('valuation_report', 'Valuation report is required for this price basis.')
        if price_basis == 'government_set' and not government_price_proof:
            self.add_error('government_price_proof', 'Government price proof is required for this price basis.')
        if price_basis in ['agent_market', 'negotiated'] and not price_notes:
            self.add_error('price_notes', 'Provide a brief note on market comps or negotiation basis.')

        if listing_type in ['lease', 'both']:
            if lease_basis == 'government_set' and not government_price_proof:
                self.add_error('government_price_proof', 'Government price proof is required for this lease basis.')

        other_amenities = (cleaned_data.get('other_amenities') or '').strip()
        if other_amenities:
            normalized_other_amenities = "\n".join(
                line.strip() for line in other_amenities.splitlines() if line.strip()
            )
            if len(normalized_other_amenities) < 3:
                self.add_error('other_amenities', 'Please provide a bit more detail for other amenities.')
            cleaned_data['other_amenities'] = normalized_other_amenities
        else:
            cleaned_data['other_amenities'] = ''

        # Market band validation (guardrails)
        def _get_band(listing_kind):
            queryset = MarketPriceBand.objects.filter(
                county=county,
                land_type=land_type,
                listing_type=listing_kind,
                market_zone=market_zone,
                is_active=True,
            )
            band = None
            if subcounty:
                band = queryset.filter(subcounty=subcounty).order_by('-effective_from').first()
            if band is None:
                band = queryset.filter(subcounty__in=['', None]).order_by('-effective_from').first()
            return band

        def _validate_band(listing_kind, entered_value, basis, field_name):
            if not entered_value or not county or not land_type or not market_zone:
                return
            band = _get_band(listing_kind)
            if not band:
                return
            area_in_band_unit = _to_acres(area, area_unit) if band.area_unit == 'acres' else (
                area if area_unit == 'hectares' else (_to_acres(area, area_unit) / 2.47105 if _to_acres(area, area_unit) else None)
            )
            if not area_in_band_unit:
                return
            price_per_unit = Decimal(str(entered_value)) / Decimal(str(area_in_band_unit))
            over_cap = price_per_unit > band.max_price_per_unit
            below_floor = price_per_unit < band.min_price_per_unit
            if over_cap:
                cleaned_data['price_review_required'] = True
                if not pricing_override_reason:
                    self.add_error(
                        'pricing_override_reason',
                        (
                            f"Your price exceeds the regional guide for {county}"
                            f"{' / ' + subcounty if subcounty else ''} ({market_zone.replace('_', ' ')}). "
                            "Explain the value additions or unique features that justify the higher price."
                        ),
                    )
                if basis != 'valuation_report' or not valuation_report:
                    self.add_error(
                        field_name,
                        (
                            f"Your price exceeds the regional cap of KES {band.max_price_per_unit:,.2f} per {band.area_unit}. "
                            "Upload a professional valuation report or reduce the price."
                        ),
                    )
            elif below_floor:
                self.add_error(
                    field_name,
                    (
                        f"Your price is below the regional guide floor of KES {band.min_price_per_unit:,.2f} per {band.area_unit}. "
                        "Double-check the entered amount or the plot area."
                    ),
                )
            else:
                cleaned_data['price_review_required'] = False

        if sale_price and area and county and land_type and listing_type in ['sale', 'both']:
            _validate_band('sale', sale_price, price_basis, 'sale_price')

        lease_reference_price = lease_price_yearly or (
            Decimal(str(lease_price_monthly)) * Decimal("12")
            if lease_price_monthly else None
        )
        if lease_reference_price and area and county and land_type and listing_type in ['lease', 'both']:
            _validate_band('lease', lease_reference_price, lease_basis, 'lease_price_yearly' if lease_price_yearly else 'lease_price_monthly')
        
        # =========================================================================
        # DOCUMENT VALIDATION
        # =========================================================================
        document_fields = [
            'title_deed',
            'survey_map',
            'spousal_consent_doc',
            'soil_report',
            'official_search',
            'rates_clearance',
            'rent_clearance',
            'lcb_consent_doc',
            'plupa1_form',
            'consent_to_transfer',
            'landowner_id_doc',
            'kra_pin',
        ]
        
        for field_name in document_fields:
            document = cleaned_data.get(field_name)
            if document and hasattr(document, 'size'):
                logger.debug(f"Validating document: {field_name}, Size: {document.size} bytes")
                
                # Check file size
                max_size = MAX_UPLOAD_MB * 1024 * 1024
                if document.size > max_size:
                    size_mb = document.size / (1024 * 1024)
                    error_msg = f"{field_name.replace('_', ' ').title()} must be less than {MAX_UPLOAD_MB}MB (current: {size_mb:.2f}MB)"
                    self.add_error(field_name, error_msg)
                    validation_errors.append(f"{field_name}: {error_msg}")
                    logger.warning(f"File too large: {field_name} - {size_mb:.2f}MB")
                
                # Check file type
                valid_extensions = ['.pdf', '.jpg', '.jpeg', '.png']
                file_extension = os.path.splitext(document.name)[1].lower()
                if file_extension not in valid_extensions:
                    error_msg = f"Invalid file type for {field_name.replace('_', ' ').title()}. Allowed: PDF, JPG, PNG"
                    self.add_error(field_name, error_msg)
                    validation_errors.append(f"{field_name}: {error_msg}")
                    logger.warning(f"Invalid file type: {field_name} - {file_extension}")
        
        # =========================================================================
        # PRICE PER ACRE CALCULATION
        # =========================================================================
        area = cleaned_data.get('area')
        
        if sale_price and area:
            try:
                area_decimal = Decimal(str(area))
                if area_decimal > 0:
                    price_per_unit = (Decimal(str(sale_price)) / area_decimal).quantize(
                        Decimal("0.01"), rounding=ROUND_HALF_UP
                    )
                    cleaned_data['price_per_acre'] = price_per_unit
                    cleaned_data['price'] = sale_price
                    logger.debug(f"Calculated price per unit ({area_unit}): {price_per_unit}")
                else:
                    error_msg = 'Area must be greater than 0'
                    self.add_error('area', error_msg)
                    validation_errors.append(f"area: {error_msg}")
            except (InvalidOperation, ZeroDivisionError, TypeError) as e:
                error_msg = f'Error calculating price per unit: {str(e)}'
                logger.error(error_msg, exc_info=True)
                # Don't add form error, just log it
        elif sale_price:
            cleaned_data['price'] = sale_price
        
        # =========================================================================
        # AREA VALIDATION
        # =========================================================================
        if area is not None:
            try:
                area_float = float(area)
                area_acres_check = _to_acres(area_float, area_unit)
                if area_float <= 0:
                    error_msg = 'Area must be greater than 0'
                    self.add_error('area', error_msg)
                    validation_errors.append(f"area: {error_msg}")
                elif area_acres_check and area_acres_check > 100000:  # Sanity check: max 100,000 acres
                    error_msg = 'Area seems unusually large. Please verify the size.'
                    self.add_error('area', error_msg)
                    validation_errors.append(f"area: {error_msg}")
            except (ValueError, TypeError):
                error_msg = 'Invalid area value'
                self.add_error('area', error_msg)
                validation_errors.append(f"area: {error_msg}")
        
        # =========================================================================
        # LOG VALIDATION RESULTS
        # =========================================================================
        if validation_errors:
            validation_logger.warning(f"Form validation failed with {len(validation_errors)} errors")
            for error in validation_errors:
                validation_logger.debug(f"Validation error: {error}")
        else:
            logger.debug("Form validation successful")
        
        return cleaned_data

    def save(self, commit=True):
        plot = super().save(commit=False)
        if self.cleaned_data.get("__registry_has_encumbrance"):
            plot.encumbrances = True
            if not plot.encumbrance_details:
                plot.encumbrance_details = "Registry indicates an active charge/caution."
        # Ensure price is set from derived values if not explicitly provided
        if not plot.price:
            derived_price = self.cleaned_data.get('price')
            if not derived_price:
                derived_price = self.cleaned_data.get('sale_price') or self.cleaned_data.get('lease_price_yearly') or self.cleaned_data.get('lease_price_monthly')
            if derived_price:
                plot.price = derived_price
        
        # Check if documents were uploaded
        docs_uploaded = []
        for field in [
            'title_deed',
            'survey_map',
            'spousal_consent_doc',
            'official_search',
            'rates_clearance',
            'rent_clearance',
            'landowner_id_doc',
            'kra_pin',
        ]:
            if field in self.changed_data:
                docs_uploaded.append(field)
        
        if commit:
            plot.save()
            sale_suggestion = plot.pricing_recommendation('sale')
            if sale_suggestion and plot.listing_type in ['sale', 'both']:
                latest_suggestion = plot.pricing_suggestions.order_by('-generated_at').first()
                suggestion_defaults = {
                    'suggested_price': sale_suggestion['suggested_total'],
                    'price_range_min': sale_suggestion['price_range_min'] or sale_suggestion['suggested_total'],
                    'price_range_max': sale_suggestion['price_range_max'] or sale_suggestion['suggested_total'],
                    'methodology': 'Regional band + comparable blend',
                    'comparable_plots_used': (
                        sale_suggestion['comparable_snapshot']['sample_size']
                        if sale_suggestion.get('comparable_snapshot')
                        else 0
                    ),
                    'explanation': sale_suggestion['explanation'],
                }
                if latest_suggestion:
                    for field_name, field_value in suggestion_defaults.items():
                        setattr(latest_suggestion, field_name, field_value)
                    latest_suggestion.save()
                else:
                    PricingSuggestion.objects.create(plot=plot, **suggestion_defaults)
            
            # If documents were uploaded, log it
            if docs_uploaded:
                VerificationLog.objects.create(
                    plot=plot,
                    verified_by=None,  # System action
                    verification_type='document_upload',
                    comment=f"Documents uploaded: {', '.join(docs_uploaded)}"
                )
                # Q8: store document hashes for integrity checks
                from .models import DocumentHash
                for field in docs_uploaded:
                    file_obj = getattr(plot, field, None)
                    if not file_obj:
                        continue
                    try:
                        file_obj.open('rb')
                        digest = hashlib.sha256(file_obj.read()).hexdigest()
                        DocumentHash.objects.get_or_create(
                            file_hash=digest,
                            defaults={
                                'file_name': file_obj.name or field,
                                'uploaded_by': getattr(plot, 'agent', None).user if plot.agent else (
                                    plot.landowner.user if plot.landowner else None
                                ),
                            }
                        )
                    finally:
                        try:
                            file_obj.close()
                        except Exception:
                            pass
        
        return plot

# ============ VERIFICATION FORMS ============
class VerificationDocumentForm(forms.ModelForm):
    """Form for uploading verification documents"""
    class Meta:
        model = VerificationDocument
        fields = ['doc_type', 'file']
        widgets = {
            'doc_type': forms.Select(attrs={'class': 'form-select'}),
            'file': forms.FileInput(attrs={'class': 'form-control'}),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['doc_type'].choices = VerificationDocument.DOC_TYPE_CHOICES

    def save(self, commit=True):
        instance = super().save(commit=False)
        if commit:
            instance.save()
            try:
                from .models import DocumentHash
                if instance.file:
                    instance.file.open('rb')
                    digest = hashlib.sha256(instance.file.read()).hexdigest()
                    DocumentHash.objects.get_or_create(
                        file_hash=digest,
                        defaults={
                            'file_name': instance.file.name or instance.doc_type,
                            'uploaded_by': instance.uploaded_by,
                        }
                    )
            finally:
                try:
                    instance.file.close()
                except Exception:
                    pass
        return instance


class TitleSearchResultForm(forms.ModelForm):
    """Form for official title search results"""
    class Meta:
        model = TitleSearchResult
        fields = ['search_platform', 'official_owner', 'parcel_number',
                 'encumbrances', 'lease_status', 'search_date', 'raw_response_file', 'verified', 'notes']
        widgets = {
            'search_platform': forms.Select(attrs={'class': 'form-control'}),
            'official_owner': forms.TextInput(attrs={'class': 'form-control'}),
            'parcel_number': forms.TextInput(attrs={'class': 'form-control'}),
            'encumbrances': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'lease_status': forms.TextInput(attrs={'class': 'form-control'}),
            'search_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'raw_response_file': forms.FileInput(attrs={'class': 'form-control'}),
            'verified': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['search_platform'].choices = [
            ('', 'Select Platform'),
            ('Ardhisasa', 'Ardhisasa'),
            ('eCitizen', 'eCitizen'),
            ('Manual', 'Manual Search'),
            ('Other', 'Other'),
        ]

    def clean_parcel_number(self):
        value = self.cleaned_data.get('parcel_number')
        if value:
            return _validate_parcel_number(value)
        return value


class PlotVerificationStatusForm(forms.ModelForm):
    """Form for updating plot verification status"""
    class Meta:
        model = VerificationStatus
        fields = ['current_stage', 'stage_details']
        widgets = {
            'current_stage': forms.Select(attrs={'class': 'form-select'}),
            'stage_details': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['current_stage'].choices = VerificationStatus.STAGES


# ============ SUPPORT ============
class SupportTicketForm(forms.ModelForm):
    class Meta:
        model = SupportTicket
        fields = ['name', 'email', 'subject', 'message']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Your full name'}),
            'email': forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'you@example.com'}),
            'subject': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Subject'}),
            'message': forms.Textarea(attrs={'class': 'form-control', 'rows': 5, 'placeholder': 'Describe your issue...'}),
        }


# ============ LANDOWNER WIZARD FORMS ============
class LandownerStep1Form(BaseUserRegistrationForm):
    """Step 1: Personal information"""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Remove phone from step 1 to avoid duplication (kept in step 2)
        if 'phone' in self.fields:
            self.fields.pop('phone')


class LandownerStep2Form(forms.Form):
    """Step 2: Contact information"""
    phone = forms.CharField(
        max_length=15, 
        required=True,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g., 0712345678'})
    )
    region = forms.CharField(
        max_length=100, 
        required=True,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g., Rift Valley'})
    )
    city = forms.CharField(
        max_length=100, 
        required=True,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g., Nakuru'})
    )

    def clean_phone(self):
        phone = (self.cleaned_data.get("phone") or "").strip()
        pattern = r'^\+?254\d{9}$|^0\d{9}$'
        if not re.match(pattern, phone):
            raise forms.ValidationError(
                "Enter a valid Kenyan phone number (e.g., 0712345678 or +254712345678)"
            )
        if _phone_exists_in_system(phone):
            raise forms.ValidationError("An account with this phone number already exists.")
        return phone


class LandownerStep3Form(forms.Form):
    """Step 3: Documents"""
    national_id = forms.FileField(
        required=True,
        widget=forms.FileInput(attrs={'class': 'form-control'}),
        help_text="Upload your national ID (PDF/Image)"
    )
    kra_pin = forms.FileField(
        required=True,
        widget=forms.FileInput(attrs={'class': 'form-control'}),
        help_text="Upload your KRA PIN certificate (PDF/Image)"
    )
    title_deed = forms.FileField(
        required=False,
        widget=forms.FileInput(attrs={'class': 'form-control'}),
        help_text="Upload land title deed (PDF/Image)"
    )
    land_search = forms.FileField(
        required=False,
        widget=forms.FileInput(attrs={'class': 'form-control'}),
        help_text="Upload official land search certificate (PDF/Image)"
    )
    lcb_consent = forms.FileField(
        required=False,
        widget=forms.FileInput(attrs={'class': 'form-control'}),
        help_text="Optional: Upload LCB consent if applicable"
    )

    def clean(self):
        cleaned = super().clean()
        _validate_upload("National ID", cleaned.get('national_id'))
        _validate_upload("KRA PIN", cleaned.get('kra_pin'))
        _validate_upload("Title Deed", cleaned.get('title_deed'))
        _validate_upload("Land Search", cleaned.get('land_search'))
        _validate_upload("LCB Consent", cleaned.get('lcb_consent'))

        missing = []
        for field_name in ['national_id', 'kra_pin', 'title_deed', 'land_search']:
            if not cleaned.get(field_name):
                missing.append(field_name.replace('_', ' ').title())
        if missing:
            raise forms.ValidationError(
                "Please upload all required documents: " + ", ".join(missing)
            )
        return cleaned


class LandownerStep4Form(forms.Form):
    """Step 4: Confirmation"""
    agree_terms = forms.BooleanField(
        required=True,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        error_messages={'required': 'You must agree to the terms and conditions to continue.'}
    )
    agree_privacy = forms.BooleanField(
        required=True,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        error_messages={'required': 'You must agree to the privacy policy.'}
    )

from verification.forms import (  # noqa: E402
    ExtensionOfficerProfileForm,
    ExtensionReportForm,
    LandSurveyorProfileForm,
    SurveyorReportForm,
)


from authentication.forms import TwoFactorSetupForm, TwoFactorVerifyForm  # noqa: E402
from security.forms import OTPVerificationForm, PhoneResendForm  # noqa: E402
