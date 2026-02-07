import os
from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from .models import *

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
            if field_name not in ['username', 'email', 'first_name', 'last_name']:
                continue
            field.widget.attrs.update({'class': 'form-control'})


class BuyerRegistrationForm(BaseUserRegistrationForm):
    """Simple buyer registration form"""
    pass


class SellerRegistrationForm(BaseUserRegistrationForm):
    """Seller registration with document uploads"""
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


class BrokerRegistrationForm(BaseUserRegistrationForm):
    """Broker registration with professional details"""
    phone = forms.CharField(
        max_length=20,
        required=True,
        widget=forms.TextInput(attrs={'class': 'form-control'})
    )
    license_number = forms.CharField(
        max_length=100,
        required=True,
        widget=forms.TextInput(attrs={'class': 'form-control'})
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


class SellerUpgradeForm(BaseUpgradeForm):
    """Form for existing users to upgrade to seller"""
    class Meta:
        model = SellerProfile
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
    
    def save(self, user=None, commit=True):
        instance = super().save(commit=False)
        if user:
            instance.user = user
        instance.verified = False
        if commit:
            instance.save()
        return instance


class BrokerUpgradeForm(BaseUpgradeForm):
    """Form for existing users to upgrade to broker"""
    class Meta:
        model = Broker
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
    
    def save(self, user=None, commit=True):
        instance = super().save(commit=False)
        if user:
            instance.user = user
        instance.verified = False
        if commit:
            instance.save()
        return instance


# ============ PLOT FORMS ============
class PlotForm(forms.ModelForm):
    # Images field (not in model, handled separately)
    images = MultipleFileField(
        required=True,
        widget=MultipleFileInput(attrs={'class': 'form-control'}),
        help_text="Upload 1-5 images (JPEG, PNG, WEBP, max 5MB each)"
    )
    
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
    
    class Meta:
        model = Plot
        fields = [
            'title', 'location', 'price', 'area',
            'soil_type', 'ph_level', 'crop_suitability',
            'title_deed', 'soil_report',
            'official_search', 'seller_id', 'kra_pin'
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
            'price': forms.NumberInput(attrs={
                'class': 'form-control',
                'placeholder': 'e.g., 5000000',
                'min': '0',
                'step': '0.01'
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
            'seller_id': forms.ClearableFileInput(attrs={
                'class': 'form-control',
                'accept': '.pdf,.jpg,.jpeg,.png'
            }),
            'kra_pin': forms.ClearableFileInput(attrs={
                'class': 'form-control',
                'accept': '.pdf,.jpg,.jpeg,.png'
            }),
        }
    
    def __init__(self, *args, **kwargs):
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
            required_docs = ['title_deed', 'official_search', 'seller_id', 'kra_pin']
            for doc_field in required_docs:
                self.fields[doc_field].required = True
            self.fields['images'].required = True
        else:
            # For editing, documents are optional (allow updates)
            self.fields['images'].required = False
        
        # Add help texts
        self.fields['title'].help_text = "Give your plot a descriptive title"
        self.fields['location'].help_text = "County, Sub-county, Ward, and nearest town"
        self.fields['price'].help_text = "Price in Kenyan Shillings (KES)"
        self.fields['area'].help_text = "Size in acres"
        self.fields['soil_type'].help_text = "Type of soil on the plot"
        self.fields['ph_level'].help_text = "Soil pH level (0-14), optional"
        self.fields['crop_suitability'].help_text = "Crops suitable for this soil type"
        self.fields['title_deed'].help_text = "Upload title deed document (PDF/Image, max 10MB)"
        self.fields['soil_report'].help_text = "Upload soil test report (PDF/Image, max 10MB, optional)"
        self.fields['official_search'].help_text = "Official land search certificate (PDF/Image, max 10MB)"
        self.fields['seller_id'].help_text = "Seller's national ID (PDF/Image, max 10MB)"
        self.fields['kra_pin'].help_text = "KRA PIN certificate (PDF/Image, max 10MB)"
    
    def clean(self):
        cleaned_data = super().clean()
        
        # Validate document file sizes (max 10MB)
        document_fields = ['title_deed', 'soil_report', 'official_search', 'seller_id', 'kra_pin']
        
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
        
        return cleaned_data
    
    def clean_images(self):
        """Validate uploaded images"""
        images = self.files.getlist('images') if self.files else []
        
        # For new plots, require at least one image
        if not self.is_edit and not images:
            raise forms.ValidationError("Please upload at least one image.")
        
        errors = []
        
        if images:
            # Check total number of images
            if len(images) > 5:
                errors.append("You can upload a maximum of 5 images.")
            
            # Validate each image
            for image in images:
                # Check file size
                if image.size > 5 * 1024 * 1024:  # 5MB
                    errors.append(f"Image '{image.name}' ({image.size / (1024*1024):.1f}MB) exceeds 5MB size limit.")
                
                # Check file type by extension AND content type
                valid_extensions = ['.jpg', '.jpeg', '.png', '.webp']
                valid_content_types = ['image/jpeg', 'image/png', 'image/jpg', 'image/webp']
                
                # Get file extension
                import os
                file_extension = os.path.splitext(image.name)[1].lower()
                
                # Check both extension and content type
                if (file_extension not in valid_extensions or 
                    (hasattr(image, 'content_type') and image.content_type not in valid_content_types)):
                    errors.append(f"File '{image.name}' is not a valid image type. Please upload JPEG, PNG, or WEBP images only.")
        
        if errors:
            # Show only the first few errors to avoid overwhelming the user
            if len(errors) > 3:
                errors = errors[:3]
                errors.append("... and more errors. Please check all your files.")
            raise forms.ValidationError(errors)
        
        return images

    def save(self, commit=True):
        plot = super().save(commit=False)
        
        if commit:
            plot.save()
            
            # Handle multiple image uploads
            images = self.cleaned_data.get('images', [])
            for image in images[:5]:
                if image:
                    PlotImage.objects.create(plot=plot, image=image)
        
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


class TitleSearchResultForm(forms.ModelForm):
    """Form for official title search results"""
    class Meta:
        model = TitleSearchResult
        fields = ['search_platform', 'official_owner', 'parcel_number',
                 'encumbrances', 'lease_status', 'search_date', 'raw_response_file']
        widgets = {
            'search_platform': forms.Select(attrs={'class': 'form-control'}),
            'official_owner': forms.TextInput(attrs={'class': 'form-control'}),
            'parcel_number': forms.TextInput(attrs={'class': 'form-control'}),
            'encumbrances': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'lease_status': forms.TextInput(attrs={'class': 'form-control'}),
            'search_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'raw_response_file': forms.FileInput(attrs={'class': 'form-control'}),
        }


class PlotVerificationStatusForm(forms.ModelForm):
    """Form for updating plot verification status"""
    class Meta:
        model = PlotVerificationStatus
        fields = ['status', 'review_notes']
        widgets = {
            'status': forms.Select(attrs={'class': 'form-select'}),
            'review_notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }


# ============ SELLER WIZARD FORMS ============
class SellerStep1Form(BaseUserRegistrationForm):
    """Step 1: Personal information"""
    pass


class SellerStep2Form(forms.Form):
    """Step 2: Contact information"""
    phone = forms.CharField(max_length=15, widget=forms.TextInput(attrs={'class': 'form-control'}))
    region = forms.CharField(max_length=100, widget=forms.TextInput(attrs={'class': 'form-control'}))
    city = forms.CharField(max_length=100, widget=forms.TextInput(attrs={'class': 'form-control'}))


class SellerStep3Form(forms.Form):
    """Step 3: Documents"""
    title_deed = forms.FileField(
        required=True,
        widget=forms.FileInput(attrs={'class': 'form-control'})
    )
    land_photos = MultipleFileField(
        required=True,
        widget=MultipleFileInput(attrs={'class': 'form-control'}),
        help_text="Upload up to 5 images (JPEG, PNG, WEBP, max 5MB each)"
    )


class SellerStep4Form(forms.Form):
    """Step 4: Confirmation"""
    agree_terms = forms.BooleanField(
        required=True,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'})
    )