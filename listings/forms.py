import os
from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from .models import *
from decimal import Decimal

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
    
    class Meta:
        model = User
        fields = ['username', 'email', 'first_name', 'last_name', 'password1', 'password2']
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Add Bootstrap classes to all fields
        for field_name, field in self.fields.items():
            field.widget.attrs.update({'class': 'form-control'})


class BuyerRegistrationForm(BaseUserRegistrationForm):
    """Simple buyer registration form"""
    pass


class LandownerRegistrationForm(BaseUserRegistrationForm):
    """Landowner registration with document uploads"""
    phone = forms.CharField(
        max_length=15,
        required=True,
        help_text="Phone number for contact",
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g., 0712345678'})
    )
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


class AgentRegistrationForm(BaseUserRegistrationForm):
    """Agent registration with professional details"""
    phone = forms.CharField(
        max_length=20,
        required=True,
        widget=forms.TextInput(attrs={'class': 'form-control'})
    )
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
        required=False,
        widget=forms.FileInput(attrs={'class': 'form-control'}),
        help_text="Optional: Upload license certificate"
    )


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
        self.fields['title_deed'].required = False
        self.fields['land_search'].required = False
        self.fields['lcb_consent'].required = False
        
        # Add help texts
        self.fields['national_id'].help_text = "Upload your national ID (required)"
        self.fields['kra_pin'].help_text = "Upload your KRA PIN certificate (required)"
        self.fields['title_deed'].help_text = "Optional: Land title deed for verification"
        self.fields['land_search'].help_text = "Optional: Official land search certificate (ARDHI/Ardhisasa)"
        self.fields['lcb_consent'].help_text = "Optional: Upload LCB consent if applicable"
    
    def save(self, user=None, commit=True):
        instance = super().save(commit=False)
        if user:
            instance.user = user
        instance.verified = False
        if commit:
            instance.save()
        return instance


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
        self.fields['license_doc'].required = False
        
        # Reorder fields
        self.order_fields([
            'username', 'email', 'phone', 'id_number', 'license_number',
            'license_doc', 'kra_pin', 'practicing_certificate', 
            'good_conduct', 'professional_indemnity'
        ])
    
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


# ============ PLOT FORMS ============
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
            'title', 'location', 'area', 'listing_type', 'land_type',
            'land_use_description', 'sale_price', 'price_per_acre',
            'lease_price_monthly', 'lease_price_yearly', 'lease_duration', 'lease_terms',
            'soil_type', 'ph_level', 'crop_suitability',
            'has_water', 'water_source', 'has_electricity', 'electricity_meter',
            'has_road_access', 'road_type', 'road_distance_km',
            'has_buildings', 'building_description', 'fencing',
            'latitude', 'longitude',
            'elevation_meters', 'climate_zone', 'is_protected_area', 'special_features',
            'title_deed', 'soil_report', 'official_search',
            'landowner_id_doc', 'kra_pin'
        ]
        widgets = {
            'title': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'e.g., 5-Acre Fertile Farm in Kitale'
            }),
            'location': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'e.g., Kitale, Trans-Nzoia County'
            }),
            'area': forms.NumberInput(attrs={
                'class': 'form-control',
                'placeholder': 'e.g., 5.0',
                'min': '0',
                'step': '0.1'
            }),
            'ph_level': forms.NumberInput(attrs={
                'class': 'form-control',
                'placeholder': 'e.g., 6.5',
                'min': '0',
                'max': '14',
                'step': '0.1'
            }),
            'crop_suitability': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'e.g., Maize, Wheat, Beans'
            }),
            'title_deed': forms.ClearableFileInput(attrs={
                'class': 'form-control',
                'accept': '.pdf,.jpg,.jpeg,.png'
            }),
            'soil_report': forms.ClearableFileInput(attrs={
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
        }
    
    def __init__(self, *args, **kwargs):
        # Pop owner from kwargs if provided
        self.owner = kwargs.pop('owner', None)
        self.is_edit = kwargs.get('instance', None) is not None
        super().__init__(*args, **kwargs)
        
        # Custom soil type widget
        self.fields['soil_type'].widget = forms.Select(
            choices=self.SOIL_TYPE_CHOICES,
            attrs={'class': 'form-control'}
        )
        
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
        self.fields['location'].help_text = "County, Sub-county, Ward, and nearest town"
        self.fields['area'].help_text = "Size in acres"
        self.fields['soil_type'].help_text = "Type of soil on the plot"
        self.fields['ph_level'].help_text = "Soil pH level (0-14), optional"
        self.fields['crop_suitability'].help_text = "Crops suitable for this soil type"
        self.fields['title_deed'].help_text = "Upload title deed document (PDF/Image, max 10MB)"
        self.fields['soil_report'].help_text = "Upload soil test report (PDF/Image, max 10MB, optional)"
        self.fields['official_search'].help_text = "Official land search certificate (PDF/Image, max 10MB)"
        self.fields['landowner_id_doc'].help_text = "Landowner's national ID (PDF/Image, max 10MB)"
        self.fields['kra_pin'].help_text = "Landowner's KRA PIN certificate (PDF/Image, max 10MB)"
        
        # Conditional field requirements based on listing type
        if self.data.get('listing_type') in ['sale', 'both']:
            self.fields['sale_price'].required = True
        if self.data.get('listing_type') in ['lease', 'both']:
            self.fields['lease_price_monthly'].required = False  # Either monthly or yearly
            self.fields['lease_price_yearly'].required = False
            self.fields['lease_duration'].required = True
    
    def clean(self):
        cleaned_data = super().clean()
        
        # 👇 TEMPORARILY SET OWNER FOR VALIDATION
        if self.owner and not self.is_edit:
            if isinstance(self.owner, Agent):
                self.instance.agent = self.owner
            elif isinstance(self.owner, LandownerProfile):
                self.instance.landowner = self.owner
        
        # Validate listing type and corresponding price fields
        listing_type = cleaned_data.get('listing_type')
        sale_price = cleaned_data.get('sale_price')
        lease_price_monthly = cleaned_data.get('lease_price_monthly')
        lease_price_yearly = cleaned_data.get('lease_price_yearly')
        
        if listing_type in ['sale', 'both'] and not sale_price:
            self.add_error('sale_price', 'Sale price is required for properties listed for sale')
        
        if listing_type in ['lease', 'both']:
            if not lease_price_monthly and not lease_price_yearly:
                self.add_error('lease_price_monthly', 'Either monthly or yearly lease price is required')
                self.add_error('lease_price_yearly', 'Either monthly or yearly lease price is required')
        
        # Validate document file sizes (max 10MB)
        document_fields = ['title_deed', 'soil_report', 'official_search', 'landowner_id_doc', 'kra_pin']
        
        for field_name in document_fields:
            document = cleaned_data.get(field_name)
            if document:
                # Check file size
                if document.size > 10 * 1024 * 1024:  # 10MB
                    self.add_error(field_name, f"{field_name.replace('_', ' ').title()} must be less than 10MB")
                
                # Check file type
                valid_extensions = ['.pdf', '.jpg', '.jpeg', '.png']
                file_extension = os.path.splitext(document.name)[1].lower()
                if file_extension not in valid_extensions:
                    self.add_error(field_name, f"Invalid file type for {field_name.replace('_', ' ').title()}. Allowed: PDF, JPG, PNG")
        
        # Calculate price per acre if both sale price and area are provided
        area = cleaned_data.get('area')
        if sale_price and area and area > 0:
            # Convert area to Decimal for division with Decimal
            from decimal import Decimal
            area_decimal = Decimal(str(area))
            cleaned_data['price_per_acre'] = sale_price / area_decimal
            cleaned_data['price'] = sale_price
        elif sale_price:
            cleaned_data['price'] = sale_price
        
        return cleaned_data
    
    def save(self, commit=True):
        plot = super().save(commit=False)
        
        # Set owner if provided
        if hasattr(self, 'owner') and self.owner:
            if isinstance(self.owner, Agent):
                plot.agent = self.owner
            elif isinstance(self.owner, LandownerProfile):
                plot.landowner = self.owner
        
        # Set legacy price field (required on Plot): prefer sale_price, else lease yearly, else lease monthly*12, else 0
        if self.cleaned_data.get('sale_price'):
            plot.price = self.cleaned_data['sale_price']
        elif self.cleaned_data.get('lease_price_yearly'):
            plot.price = self.cleaned_data['lease_price_yearly']
        elif self.cleaned_data.get('lease_price_monthly'):
            plot.price = self.cleaned_data['lease_price_monthly'] * 12
        else:
            plot.price = Decimal('0')
        
        if commit:
            plot.save()
        
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


# ============ LANDOWNER WIZARD FORMS ============
class LandownerStep1Form(BaseUserRegistrationForm):
    """Step 1: Personal information"""
    pass


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
    land_photos = MultipleFileField(
        required=True,
        widget=MultipleFileInput(attrs={'class': 'form-control'}),
        help_text="Upload up to 5 images (JPEG, PNG, WEBP, max 5MB each)"
    )


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