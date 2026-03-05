import logging
import os
import hashlib
from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from .models import *
from decimal import Decimal, InvalidOperation
from .location_utils import validate_kenyan_location, get_subcounties_for_county

# Get logger for this module
logger = logging.getLogger(__name__)
validation_logger = logging.getLogger('listings.validation')

ALLOWED_DOC_EXTENSIONS = {'.pdf', '.jpg', '.jpeg', '.png'}
MAX_UPLOAD_MB = 10

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
        fields = ['phone', 'license_number', 'license_doc']
        widgets = {
            'phone': forms.TextInput(attrs={'class': 'form-control'}),
            'license_number': forms.TextInput(attrs={'class': 'form-control'}),
            'license_doc': forms.FileInput(attrs={'class': 'form-control'}),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['phone'].required = True
        self.fields['license_number'].required = True
        self.fields['license_doc'].required = True
        
        # Reorder fields
        self.order_fields([
            'username', 'email', 'phone', 'id_number', 'license_number',
            'license_doc', 'kra_pin', 'practicing_certificate',
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
        help_text="Price per acre (auto-calculated)"
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
    
    fencing = forms.ChoiceField(
        choices=Plot.FENCING_CHOICES,
        required=False,
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    
    class Meta:
        model = Plot
        fields = [
            'title', 'county', 'subcounty', 'location', 'area', 'listing_type', 'land_type',
            'land_use_description', 'nearest_town',
            'ownership_type', 'tenure_details', 'encumbrances', 'encumbrance_details',
            'sale_price', 'price_per_acre',
            'lease_price_monthly', 'lease_price_yearly', 'lease_duration', 'lease_terms',
            'price_basis', 'valuation_report', 'price_notes', 'is_price_negotiable', 'lease_basis', 'government_price_proof',
            'has_water', 'water_source', 'has_electricity', 'electricity_meter',
            'has_road_access', 'road_type', 'road_distance_km',
            'has_buildings', 'building_description', 'fencing',
            'title_deed', 'official_search',
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
            'title_deed': forms.ClearableFileInput(attrs={
                'class': 'form-control',
                'accept': '.pdf,.jpg,.jpeg,.png'
            }),
            'official_search': forms.ClearableFileInput(attrs={
                'class': 'form-control',
                'accept': '.pdf,.jpg,.jpeg,.png'
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
        
        # Set required fields for creation vs edit
        if not self.is_edit:
            # For new plots, all documents are required except soil_report
            required_docs = ['title_deed', 'official_search', 'landowner_id_doc', 'kra_pin']
            for doc_field in required_docs:
                if doc_field in self.fields:
                    self.fields[doc_field].required = True
            
            # Listing type is required
            self.fields['listing_type'].required = True
            self.fields['land_type'].required = True
        else:
            # For editing, documents are optional (allow updates)
            pass
        
        # Add help texts
        self.fields['title'].help_text = "Give your plot a descriptive title"
        self.fields['county'].help_text = "Select the county where your plot is located"
        self.fields['subcounty'].help_text = "Select the specific sub-county"
        self.fields['area'].help_text = "Size in acres"
        self.fields['price_basis'].help_text = "How was the selling price determined?"
        self.fields['lease_basis'].help_text = "How was the lease price determined?"
        self.fields['valuation_report'].help_text = "Optional valuation report (PDF/Image)"
        self.fields['price_notes'].help_text = "Optional notes about market demand or negotiations"
        self.fields['ownership_type'].help_text = "Legal tenure status"
        self.fields['encumbrance_details'].help_text = "Specify any caveats, loans, or disputes"
        self.fields['title_deed'].help_text = "Upload title deed document (PDF/Image, max 10MB)"
        if 'soil_report' in self.fields:
            self.fields['soil_report'].help_text = "Upload soil test report (PDF/Image, max 10MB, optional)"
        self.fields['official_search'].help_text = "Official land search certificate (PDF/Image, max 10MB)"
        self.fields['landowner_id_doc'].help_text = "Landowner's national ID (PDF/Image, max 10MB)"
        self.fields['kra_pin'].help_text = "Landowner's KRA PIN certificate (PDF/Image, max 10MB)"
    
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
        if county and subcounty:
            cleaned_data['location'] = f"{county} - {subcounty}"
            logger.debug(f"Generated location: {cleaned_data['location']}")
        
        # =========================================================================
        # OWNER VALIDATION
        # =========================================================================
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
        land_type = cleaned_data.get('land_type')
        area = cleaned_data.get('area')
        
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

        # Market band validation (guardrails)
        from .models import MarketPriceBand
        if sale_price and area and county and land_type:
            band = MarketPriceBand.objects.filter(
                county=county,
                land_type=land_type,
                listing_type='sale',
                effective_to__isnull=True
            ).first()
            if band:
                price_per_acre = sale_price / area
                if price_per_acre < band.min_price_per_acre or price_per_acre > band.max_price_per_acre:
                    if price_basis != 'valuation_report':
                        self.add_error(
                            'sale_price',
                            f"Sale price per acre is outside market band ({band.min_price_per_acre}-{band.max_price_per_acre}). Upload valuation report or adjust price."
                        )

        if lease_price_yearly and area and county and land_type:
            band = MarketPriceBand.objects.filter(
                county=county,
                land_type=land_type,
                listing_type='lease',
                effective_to__isnull=True
            ).first()
            if band:
                price_per_acre = lease_price_yearly / area
                if price_per_acre < band.min_price_per_acre or price_per_acre > band.max_price_per_acre:
                    if lease_basis != 'valuation_report':
                        self.add_error(
                            'lease_price_yearly',
                            f"Lease price per acre is outside market band ({band.min_price_per_acre}-{band.max_price_per_acre}). Upload valuation report or adjust price."
                        )
        
        # =========================================================================
        # DOCUMENT VALIDATION
        # =========================================================================
        document_fields = ['title_deed', 'soil_report', 'official_search', 'landowner_id_doc', 'kra_pin']
        
        for field_name in document_fields:
            document = cleaned_data.get(field_name)
            if document and hasattr(document, 'size'):
                logger.debug(f"Validating document: {field_name}, Size: {document.size} bytes")
                
                # Check file size (max 10MB)
                max_size = 10 * 1024 * 1024  # 10MB
                if document.size > max_size:
                    size_mb = document.size / (1024 * 1024)
                    error_msg = f"{field_name.replace('_', ' ').title()} must be less than 10MB (current: {size_mb:.2f}MB)"
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
                    price_per_acre = Decimal(str(sale_price)) / area_decimal
                    cleaned_data['price_per_acre'] = price_per_acre
                    cleaned_data['price'] = sale_price
                    logger.debug(f"Calculated price per acre: {price_per_acre}")
                else:
                    error_msg = 'Area must be greater than 0'
                    self.add_error('area', error_msg)
                    validation_errors.append(f"area: {error_msg}")
            except (InvalidOperation, ZeroDivisionError, TypeError) as e:
                error_msg = f'Error calculating price per acre: {str(e)}'
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
                if area_float <= 0:
                    error_msg = 'Area must be greater than 0'
                    self.add_error('area', error_msg)
                    validation_errors.append(f"area: {error_msg}")
                elif area_float > 100000:  # Sanity check: max 100,000 acres
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
        # Ensure price is set from derived values if not explicitly provided
        if not plot.price:
            derived_price = self.cleaned_data.get('price')
            if not derived_price:
                derived_price = self.cleaned_data.get('sale_price') or self.cleaned_data.get('lease_price_yearly') or self.cleaned_data.get('lease_price_monthly')
            if derived_price:
                plot.price = derived_price
        
        # Check if documents were uploaded
        docs_uploaded = []
        for field in ['title_deed', 'official_search', 'landowner_id_doc', 'kra_pin']:
            if field in self.changed_data:
                docs_uploaded.append(field)
        
        if commit:
            plot.save()
            
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

# listings/forms.py - Add these forms

class ExtensionOfficerProfileForm(forms.ModelForm):
    """Form for creating/editing extension officer profile"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from .kenya_data import KENYA_COUNTIES
        self.fields['assigned_counties'].choices = [(c, c) for c in KENYA_COUNTIES]
        self.fields['assigned_counties'].required = True
        self.fields['assigned_counties'].help_text = "Select one or more counties you can verify."
        self.fields['max_daily_tasks'].required = True
        self.fields['years_of_experience'].required = True
        for field in self.fields.values():
            if not isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs.setdefault('class', 'form-control')
            if field.required:
                field.widget.attrs['required'] = 'required'
    
    class Meta:
        model = ExtensionOfficer
        fields = ['employee_id', 'designation', 'department', 'station',
                 'qualifications', 'specializations', 'years_of_experience',
                 'phone', 'office_address', 'assigned_counties', 'max_daily_tasks']
        widgets = {
            'assigned_counties': forms.CheckboxSelectMultiple(),
            'qualifications': forms.Textarea(attrs={'rows': 3, 'class': 'form-control'}),
            'specializations': forms.TextInput(attrs={'class': 'form-control'}),
            'office_address': forms.Textarea(attrs={'rows': 2, 'class': 'form-control'}),
            'years_of_experience': forms.NumberInput(attrs={'min': 0, 'class': 'form-control'}),
            'max_daily_tasks': forms.NumberInput(attrs={'min': 1, 'class': 'form-control'}),
        }


class LandSurveyorProfileForm(forms.ModelForm):
    """Form for requesting land surveyor role"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from .kenya_data import KENYA_COUNTIES
        self.fields['assigned_counties'].choices = [(c, c) for c in KENYA_COUNTIES]
        self.fields['assigned_counties'].required = True
        self.fields['assigned_counties'].help_text = "Select one or more counties you can verify."
        self.fields['max_daily_tasks'].required = True
        self.fields['years_of_experience'].required = True
        for field in self.fields.values():
            if not isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs.setdefault('class', 'form-control')
            if field.required:
                field.widget.attrs['required'] = 'required'

    class Meta:
        model = LandSurveyor
        fields = ['license_number', 'designation', 'station', 'qualifications', 'years_of_experience',
                 'phone', 'office_address', 'assigned_counties', 'max_daily_tasks']
        widgets = {
            'assigned_counties': forms.CheckboxSelectMultiple(),
            'qualifications': forms.Textarea(attrs={'rows': 3, 'class': 'form-control'}),
            'office_address': forms.Textarea(attrs={'rows': 2, 'class': 'form-control'}),
            'years_of_experience': forms.NumberInput(attrs={'min': 0, 'class': 'form-control'}),
            'max_daily_tasks': forms.NumberInput(attrs={'min': 1, 'class': 'form-control'}),
        }

class MultipleFileInput(forms.ClearableFileInput):
    """Custom widget that supports multiple file uploads"""
    allow_multiple_selected = True

class MultipleFileField(forms.FileField):
    """Custom field that handles multiple file uploads"""
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
    """Form for submitting extension review reports"""
    
    site_photos = MultipleFileField(
        required=False,
        help_text="Upload photos from the site visit (you can select multiple files)"
    )
    
    class Meta:
        model = ExtensionReport
        exclude = ['task', 'officer', 'plot', 'submitted_at', 'site_photos']
        widgets = {
            'visit_date': forms.DateTimeInput(attrs={'type': 'datetime-local', 'class': 'form-control'}),
            'existing_crops': forms.Textarea(attrs={'rows': 2, 'class': 'form-control'}),
            'pest_issues': forms.Textarea(attrs={'rows': 2, 'class': 'form-control'}),
            'disease_issues': forms.Textarea(attrs={'rows': 2, 'class': 'form-control'}),
            'recommended_crops': forms.Textarea(attrs={'rows': 2, 'class': 'form-control'}),
            'improvement_suggestions': forms.Textarea(attrs={'rows': 3, 'class': 'form-control'}),
            'comments': forms.Textarea(attrs={'rows': 3, 'class': 'form-control'}),
            'soil_texture': forms.Select(attrs={'class': 'form-control'}),
            'soil_drainage': forms.Select(attrs={'class': 'form-control'}),
            'crop_health': forms.Select(attrs={'class': 'form-control'}),
            'water_quality': forms.Select(attrs={'class': 'form-control'}),
            'overall_suitability': forms.Select(attrs={'class': 'form-control'}),
            'recommendation': forms.Select(attrs={'class': 'form-control'}),
        }


class SurveyorReportForm(forms.ModelForm):
    """Form for submitting land surveyor inspection reports"""
    plot_images = MultipleFileField(
        required=False,
        label="Plot Images (Survey Photos)",
        help_text="Upload clear photos of the plot (JPG/PNG).",
        widget=MultipleFileInput(attrs={
            'class': 'form-control',
            'accept': 'image/*'
        })
    )
    def clean(self):
        cleaned = super().clean()
        price_realistic = cleaned.get('price_realistic')
        suggested_sale_price = cleaned.get('suggested_sale_price')
        suggested_price_per_acre = cleaned.get('suggested_price_per_acre')
        if price_realistic is False and not (suggested_sale_price or suggested_price_per_acre):
            self.add_error('suggested_sale_price', 'Provide a suggested sale price or price per acre.')
        return cleaned

    class Meta:
        model = SurveyorReport
        exclude = ['task', 'surveyor', 'plot', 'submitted_at']
        widgets = {
            'visit_date': forms.DateTimeInput(attrs={'type': 'datetime-local', 'class': 'form-control'}),
            'gps_latitude': forms.NumberInput(attrs={'class': 'form-control'}),
            'gps_longitude': forms.NumberInput(attrs={'class': 'form-control'}),
            'encumbrance_details': forms.Textarea(attrs={'rows': 2, 'class': 'form-control'}),
            'boundary_markers': forms.Textarea(attrs={'rows': 2, 'class': 'form-control'}),
            'topography_notes': forms.Textarea(attrs={'rows': 2, 'class': 'form-control'}),
            'access_road': forms.TextInput(attrs={'class': 'form-control'}),
            'utilities_available': forms.Textarea(attrs={'rows': 2, 'class': 'form-control'}),
            'price_review_notes': forms.Textarea(attrs={'rows': 2, 'class': 'form-control'}),
            'suggested_price_per_acre': forms.NumberInput(attrs={'class': 'form-control'}),
            'suggested_sale_price': forms.NumberInput(attrs={'class': 'form-control'}),
            'notes': forms.Textarea(attrs={'rows': 3, 'class': 'form-control'}),
            'recommendation': forms.Select(attrs={'class': 'form-control'}),
        }


# Add to forms.py

class OTPVerificationForm(forms.Form):
    """Form for OTP verification"""
    otp = forms.CharField(
        max_length=6,
        min_length=6,
        required=True,
        widget=forms.TextInput(attrs={
            'class': 'form-control form-control-lg text-center',
            'placeholder': '000000',
            'autocomplete': 'off'
        }),
        help_text="Enter the 6-digit code sent to your phone"
    )
    
    def clean_otp(self):
        otp = self.cleaned_data.get('otp')
        if not otp.isdigit():
            raise forms.ValidationError("OTP must contain only numbers")
        return otp


class PhoneResendForm(forms.Form):
    """Simple form for resending OTP"""
    phone = forms.CharField(
        max_length=15,
        widget=forms.HiddenInput()
    )


class TwoFactorSetupForm(forms.Form):
    """Verify TOTP setup during enrollment."""
    code = forms.CharField(
        max_length=6,
        required=True,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': '123456'})
    )


class TwoFactorVerifyForm(forms.Form):
    """Verify 2FA during login."""
    METHOD_CHOICES = [
        ('totp', 'Authenticator App (TOTP)'),
        ('email', 'Email OTP'),
        ('sms', 'SMS OTP'),
        ('backup', 'Backup Code'),
    ]
    method = forms.ChoiceField(choices=METHOD_CHOICES, required=True)
    code = forms.CharField(
        max_length=6,
        required=True,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': '123456'})
    )
