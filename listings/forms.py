from django import forms
from django.contrib.auth.forms import UserCreationForm
from .models import *

# forms.py - Update PlotForm with custom widget
from django import forms
from .models import Plot, PlotImage

class MultipleFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True

class MultipleImageField(forms.ImageField):
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

class PlotForm(forms.ModelForm):
    images = MultipleImageField(
        required=False,
        help_text="Upload images of the plot (JPEG, PNG, max 5MB each). You can select multiple images."
    )
    
    class Meta:
        model = Plot
        fields = [
            "title",
            "location", 
            "price",
            "area",
            "soil_type",
            "ph_level",
            "crop_suitability",
            "title_deed",
            "soil_report",
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
            'soil_type': forms.Select(attrs={'class': 'form-control'}),
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
            'title_deed': forms.FileInput(attrs={'class': 'form-control'}),
            'soil_report': forms.FileInput(attrs={'class': 'form-control'}),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        # Add help text
        self.fields['title'].help_text = "Give your plot a descriptive title"
        self.fields['location'].help_text = "County, Sub-county, Ward, and nearest town"
        self.fields['price'].help_text = "Price in Kenyan Shillings (KES)"
        self.fields['area'].help_text = "Size in acres"
        self.fields['soil_type'].help_text = "Type of soil on the plot"
        self.fields['ph_level'].help_text = "Soil pH level (0-14), optional"
        self.fields['crop_suitability'].help_text = "Crops suitable for this soil type"
        self.fields['title_deed'].help_text = "Upload title deed document (PDF, JPG, PNG)"
        self.fields['soil_report'].help_text = "Upload soil test report (optional)"
        
        # Add choices for soil_type
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
        self.fields['soil_type'].widget = forms.Select(
            choices=SOIL_TYPE_CHOICES,
            attrs={'class': 'form-control'}
        )
        
        # Make certain fields required
        self.fields['title_deed'].required = True
        
    def clean_images(self):
        images = self.files.getlist('images')
        if images:
            if len(images) > 5:
                raise forms.ValidationError("You can upload a maximum of 5 images.")
            
            for image in images:
                if image.size > 5 * 1024 * 1024:  # 5MB
                    raise forms.ValidationError(f"Image {image.name} exceeds 5MB size limit.")
                
                valid_types = ['image/jpeg', 'image/png', 'image/jpg', 'image/gif']
                if image.content_type not in valid_types:
                    raise forms.ValidationError(f"Image {image.name} is not a valid image type (JPEG, PNG, GIF only).")
        
        return images
    
    def save(self, commit=True):
        plot = super().save(commit=False)
        if commit:
            plot.save()
            # Save images after plot is saved
            images = self.cleaned_data.get('images')
            if images:
                for image in images:
                    PlotImage.objects.create(plot=plot, image=image)
        return plot
    
class VerificationDocumentForm(forms.ModelForm):
    class Meta:
        model = VerificationDocument
        fields = ['doc_type', 'file']
        widgets = {
            'doc_type': forms.Select(attrs={'class': 'form-select'}),
            'file': forms.FileInput(attrs={'class': 'form-control'}),
        }

class TitleSearchResultForm(forms.ModelForm):
    class Meta:
        model = TitleSearchResult
        fields = ['search_platform', 'official_owner', 'parcel_number',
                  'encumbrances', 'lease_status', 'search_date', 'raw_response_file']
        widgets = {
            'search_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
        }

class PlotVerificationStatusForm(forms.ModelForm):
    class Meta:
        model = PlotVerificationStatus
        fields = ['status', 'review_notes']
        widgets = {
            'status': forms.Select(attrs={'class': 'form-select'}),
            'review_notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }

# FORMS.PY
class SellerRegistrationForm(UserCreationForm):
    email = forms.EmailField(required=True)
    first_name = forms.CharField(max_length=50, required=True)
    last_name = forms.CharField(max_length=50, required=True)
    
    # Change these from CharField to FileField
    national_id = forms.FileField(
        required=True,
        help_text="Upload a copy of your national ID"
    )
    kra_pin = forms.FileField(
        required=True,
        help_text="Upload a copy of your KRA PIN"
    )

    class Meta(UserCreationForm.Meta):
        model = User
        fields = [
            "username",
            "email",
            "first_name",
            "last_name",
            "password1",
            "password2",
        ]

class BrokerRegistrationForm(UserCreationForm):
    email = forms.EmailField(required=True)
    first_name = forms.CharField(max_length=50, required=True)
    last_name = forms.CharField(max_length=50, required=True)
    license_number = forms.CharField(max_length=100, required=True)
    phone = forms.CharField(max_length=20, required=True)

    class Meta(UserCreationForm.Meta):
        model = User
        fields = [
            "username",
            "email",
            "first_name",
            "last_name",
            "password1",
            "password2",
        ]

# UPGRADE
class SellerUpgradeForm(forms.ModelForm):
    # Display-only fields
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
    
    class Meta:
        model = SellerProfile
        fields = [
            "national_id",
            "kra_pin",
            "title_deed", 
            "land_search",
            "lcb_consent",
        ]
        widgets = {
            'national_id': forms.FileInput(attrs={'class': 'form-control'}),
            'kra_pin': forms.FileInput(attrs={'class': 'form-control'}),
            'title_deed': forms.FileInput(attrs={'class': 'form-control'}),
            'land_search': forms.FileInput(attrs={'class': 'form-control'}),
            'lcb_consent': forms.FileInput(attrs={'class': 'form-control'}),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Set required fields
        self.fields['national_id'].required = True
        self.fields['kra_pin'].required = True
        # Optional fields are already optional due to model changes
    
    def save(self, user=None, commit=True):
        instance = super().save(commit=False)
        if user:
            instance.user = user
        instance.verified = False
        
        if commit:
            instance.save()
        return instance


class BrokerUpgradeForm(forms.ModelForm):
    # Display-only fields
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
    
    class Meta:
        model = Broker
        fields = [
            "phone",
            "license_number",
            "license_doc",
        ]
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
    # Display fields
    username = forms.CharField(required=False, disabled=True)
    email = forms.EmailField(required=False, disabled=True)
    
    # Data fields
    phone = forms.CharField(required=True, max_length=20)
    license_number = forms.CharField(required=True, max_length=100)
    license_doc = forms.FileField(required=False)
    
    def save(self, user):
        return Broker.objects.create(
            user=user,
            phone=self.cleaned_data['phone'],
            license_number=self.cleaned_data['license_number'],
            license_doc=self.cleaned_data.get('license_doc'),
            verified=False
        )
    # Display-only fields
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
    
    class Meta:
        model = Broker
        fields = [
            "phone",
            "license_number",
            "license_doc",
        ]
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
    # Display fields (not saved to model)
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
    
    class Meta:
        model = Broker
        fields = [
            "phone",
            "license_number",
            "license_doc",
        ]
        widgets = {
            'phone': forms.TextInput(attrs={'class': 'form-control'}),
            'license_number': forms.TextInput(attrs={'class': 'form-control'}),
            'license_doc': forms.FileInput(attrs={'class': 'form-control'}),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Set proper required fields
        self.fields['phone'].required = True
        self.fields['license_number'].required = True  # Changed to True
        self.fields['license_doc'].required = False    # Optional
        
        # Add help text
        self.fields['phone'].help_text = "Required: Your contact phone number"
        self.fields['license_number'].help_text = "Required: Your professional license number"
        self.fields['license_doc'].help_text = "Optional: Upload license certificate"
    # These are display-only fields, not saved to SellerProfile model
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
    
    class Meta:
        model = SellerProfile
        fields = [
            "national_id",
            "kra_pin",
            "title_deed",
            "land_search",
            "lcb_consent",
        ]
        widgets = {
            'national_id': forms.FileInput(attrs={'class': 'form-control'}),
            'kra_pin': forms.FileInput(attrs={'class': 'form-control'}),
            'title_deed': forms.FileInput(attrs={'class': 'form-control'}),
            'land_search': forms.FileInput(attrs={'class': 'form-control'}),
            'lcb_consent': forms.FileInput(attrs={'class': 'form-control'}),
        }