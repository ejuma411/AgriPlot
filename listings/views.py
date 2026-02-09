from datetime import date
import logging

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.views import LoginView
from django.core.files.storage import FileSystemStorage, default_storage
from django.core.files.base import ContentFile
from django.core.mail import send_mail, EmailMessage
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.db.models import Q, Count, Avg
from django.db.models.functions import TruncMonth
from django.http import Http404, JsonResponse, HttpResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.template.loader import render_to_string

# Import formtools if you're using it
try:
    from formtools.wizard.views import SessionWizardView
except ImportError:
    # Handle the case where formtools is not installed
    SessionWizardView = None
    print("Warning: formtools not installed. Install with: pip install django-formtools")

# Import all forms
from .forms import *

# Import all models
from .models import *

logger = logging.getLogger(__name__)

wizard_file_storage = FileSystemStorage(location='/tmp/agriplot_uploads')

# ============ SELLER WIZARD ============
FORMS = [
    ("personal", SellerStep1Form),
    ("verification", SellerStep2Form),
    ("documents", SellerStep3Form),
    ("confirmation", SellerStep4Form),
]

TEMPLATES = {
    "personal": "auth/seller_wizard_step.html",
    "verification": "auth/seller_wizard_step.html",
    "documents": "auth/seller_wizard_step.html",
    "confirmation": "auth/seller_wizard_step.html",
}

class SellerWizard(SessionWizardView):
    form_list = FORMS
    file_storage = wizard_file_storage

    def get_template_names(self):
        return [TEMPLATES[self.steps.current]]

    def done(self, form_list, **kwargs):
        # Save all forms
        form_data = [form.cleaned_data for form in form_list]
        # Example: create User + SellerProfile here
        return redirect('listings:seller_success')


# ============ AUTHENTICATION & REGISTRATION ============
def custom_logout(request):
    logout(request)
    return redirect('listings:home')

def register_choice(request):
    return render(request, "auth/register_choice.html")

class CustomLoginView(LoginView):
    template_name = "auth/login.html"

def register(request):
    """Legacy register view - redirects to buyer registration"""
    if request.method == "POST":
        form = UserCreationForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect('login')
    else:
        form = UserCreationForm()
    return render(request, 'auth/register_choice.html', {'form': form})

def register_buyer(request):
    """Handle buyer registration"""
    if request.method == "POST":
        form = UserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()
            messages.success(request, "Account created successfully! You can now log in.")
            return redirect('login')
    else:
        form = UserCreationForm()
    
    context = {
        'form': form,
        'role': 'Buyer'
    }
    return render(request, 'auth/register_buyer.html', context)

def register_seller(request):
    """Handle seller registration with document upload"""
    next_url = request.GET.get("next", "/")

    if request.method == "POST":
        form = SellerRegistrationForm(request.POST, request.FILES)
        if form.is_valid():
            try:
                user = form.save(commit=False)
                user.first_name = form.cleaned_data["first_name"]
                user.last_name = form.cleaned_data["last_name"]
                user.email = form.cleaned_data["email"]
                user.save()

                # Create Profile
                Profile.objects.create(user=user)

                # Create SellerProfile with uploaded files
                SellerProfile.objects.create(
                    user=user,
                    national_id=form.cleaned_data.get("national_id"),
                    kra_pin=form.cleaned_data.get("kra_pin"),
                    verified=False
                )

                # Auto login
                auth_user = authenticate(
                    username=form.cleaned_data["username"],
                    password=form.cleaned_data["password1"]
                )
                if auth_user:
                    login(request, auth_user)
                    messages.success(request, "Seller account created successfully!")
                    return redirect(next_url)
                else:
                    messages.error(request, "Authentication failed. Please try logging in.")
                    return redirect('login')
                    
            except Exception as e:
                messages.error(request, f"Error creating account: {str(e)}")
    else:
        form = SellerRegistrationForm()

    return render(request, "auth/register_seller.html", {"form": form})

def register_broker(request):
    """Handle broker registration"""
    next_url = request.GET.get("next", "/")

    if request.method == "POST":
        form = BrokerRegistrationForm(request.POST)
        if form.is_valid():
            try:
                user = form.save(commit=False)
                user.first_name = form.cleaned_data["first_name"]
                user.last_name = form.cleaned_data["last_name"]
                user.email = form.cleaned_data["email"]
                user.save()

                # Create Profile
                Profile.objects.create(user=user)

                # Create Broker
                Broker.objects.create(
                    user=user,
                    phone=form.cleaned_data["phone"],
                    license_number=form.cleaned_data["license_number"],
                    verified=False
                )

                # Auto login
                auth_user = authenticate(
                    username=form.cleaned_data["username"],
                    password=form.cleaned_data["password1"]
                )
                if auth_user:
                    login(request, auth_user)
                    messages.success(request, "Broker account created successfully!")
                    return redirect(next_url)
                else:
                    messages.error(request, "Authentication failed. Please try logging in.")
                    return redirect('listings:login')
                    
            except Exception as e:
                messages.error(request, f"Error creating account: {str(e)}")
    else:
        form = BrokerRegistrationForm()

    return render(request, "auth/register_broker.html", {"form": form})


# ============ ROLE UPGRADES ============
@login_required
def upgrade_role(request):
    """Display role upgrade choices"""
    is_seller = hasattr(request.user, 'sellerprofile')
    is_broker = hasattr(request.user, 'broker')
    
    if request.method == "POST":
        role = request.POST.get("role")
        if role == "seller" and not is_seller:
            return redirect("listings:upgrade_seller")
        elif role == "broker" and not is_broker:
            return redirect("listings:upgrade_broker")
        else:
            messages.warning(request, "You already have this role or selected an invalid option.")
    
    return render(request, "listings/upgrade_role.html", {
        'is_seller': is_seller,
        'is_broker': is_broker,
    })

@login_required
def upgrade_seller(request):
    """Upgrade existing user to seller"""
    if hasattr(request.user, 'sellerprofile'):
        messages.info(request, "You already have a seller profile.")
        return redirect('listings:dashboard')
    
    if request.method == "POST":
        form = SellerUpgradeForm(request.POST, request.FILES)
        if form.is_valid():
            try:
                form.save(user=request.user)
                messages.success(request, "Seller profile submitted for verification!")
                return redirect('listings:dashboard')
            except Exception as e:
                messages.error(request, f"Error saving seller profile: {str(e)}")
    else:
        form = SellerUpgradeForm(initial={
            'username': request.user.username,
            'email': request.user.email
        })
    
    return render(request, "upgrade_seller.html", {"form": form, "user": request.user})

@login_required
def upgrade_broker(request):
    """Upgrade existing user to broker"""
    if hasattr(request.user, 'broker'):
        messages.info(request, "You already have a broker profile.")
        return redirect('listings:dashboard')
    
    if request.method == "POST":
        form = BrokerUpgradeForm(request.POST, request.FILES)
        if form.is_valid():
            try:
                form.save(user=request.user)
                messages.success(request, "Broker profile submitted for verification!")
                return redirect('listings:dashboard')
            except Exception as e:
                messages.error(request, f"Error saving broker profile: {str(e)}")
    else:
        form = BrokerUpgradeForm(initial={
            'username': request.user.username,
            'email': request.user.email
        })
    
    return render(request, "upgrade_broker.html", {"form": form, "user": request.user})


# ============ PUBLIC PAGES ============
def home(request):
    """Homepage with plot listings"""
    # Add ordering to the queryset - choose an appropriate field
    verified_plots = Plot.objects.filter(
        verification_status__status="verified"
    ).prefetch_related('images_list').select_related('broker', 'verification_status')
    
    # Apply ordering (most recent first is usually best)
    verified_plots = verified_plots.order_by('-created_at')
    
    # Filters
    soil_type = request.GET.get('soil_type')
    crop = request.GET.get('crop')
    crop_preset_param = request.GET.get('crop_preset')
    if crop_preset_param:
        crop = crop_preset_param
    ph_min = request.GET.get('ph_min')
    ph_max = request.GET.get('ph_max')
    om_min = request.GET.get('om_min')
    n_min = request.GET.get('n_min')
    p_min = request.GET.get('p_min')
    k_min = request.GET.get('k_min')
    ec_max = request.GET.get('ec_max')
    texture = request.GET.get('texture')

    if soil_type:
        verified_plots = verified_plots.filter(soil_type__icontains=soil_type)
    if crop:
        # If crop matches a preset, apply preset thresholds (overridden by explicit params)
        verified_plots = verified_plots.filter(crop_suitability__icontains=crop)

    # Crop-presets: basic example thresholds (extend in docs/SOIL_RULES.md)
    crop_presets = {
        'Maize': {'ph_min': 5.8, 'ph_max': 7.0, 'om_min': 2.0},
        'Wheat': {'ph_min': 6.0, 'ph_max': 7.5, 'om_min': 1.5},
        'Rice': {'ph_min': 5.5, 'ph_max': 6.5, 'om_min': 1.0},
        'Coffee': {'ph_min': 5.0, 'ph_max': 6.5, 'om_min': 3.0},
    }

    # Apply soil metric filters via SoilReport related model when parameters provided
    soil_filters = {}
    try:
        if ph_min:
            soil_filters['soil_reports__pH__gte'] = float(ph_min)
        if ph_max:
            soil_filters['soil_reports__pH__lte'] = float(ph_max)
        if om_min:
            soil_filters['soil_reports__organic_matter_pct__gte'] = float(om_min)
        if n_min:
            soil_filters['soil_reports__nitrogen_mgkg__gte'] = float(n_min)
        if p_min:
            soil_filters['soil_reports__phosphorus_mgkg__gte'] = float(p_min)
        if k_min:
            soil_filters['soil_reports__potassium_mgkg__gte'] = float(k_min)
        if ec_max:
            soil_filters['soil_reports__ec_salinity__lte'] = float(ec_max)
        if texture:
            # texture expected as "sand,silt,clay" or a class name
            if ',' in texture:
                parts = [float(x) for x in texture.split(',') if x.strip()]
                if len(parts) == 3:
                    soil_filters['soil_reports__sand_pct__gte'] = parts[0]
                    soil_filters['soil_reports__silt_pct__gte'] = parts[1]
                    soil_filters['soil_reports__clay_pct__gte'] = parts[2]
            else:
                soil_filters['soil_reports__report_file__icontains'] = texture
    except ValueError:
        # Ignore invalid numeric filters
        soil_filters = {}

    # If a crop preset is selected and explicit numeric filters are not provided, apply preset
    if crop and crop in crop_presets and not any([ph_min, ph_max, om_min, n_min, p_min, k_min, ec_max, texture]):
        preset = crop_presets[crop]
        soil_filters['soil_reports__pH__gte'] = preset.get('ph_min')
        soil_filters['soil_reports__pH__lte'] = preset.get('ph_max')
        if preset.get('om_min'):
            soil_filters['soil_reports__organic_matter_pct__gte'] = preset.get('om_min')

    if soil_filters:
        verified_plots = verified_plots.filter(**soil_filters).distinct()
    
    # Stats
    total_plots = Plot.objects.count()
    verified_count = Plot.objects.filter(verification_status__status="verified").count()
    total_brokers = Broker.objects.filter(verified=True).count()
    soil_types = Plot.objects.values_list('soil_type', flat=True).distinct()
    common_crops = ['Maize', 'Wheat', 'Coffee', 'Tea', 'Beans', 'Potatoes', 'Sugarcane', 'Rice', 'Vegetables']
    
    # Pagination
    paginator = Paginator(verified_plots, 15)
    page_number = request.GET.get('page')
    featured_plots = paginator.get_page(page_number)
    
    return render(request, 'listings/home.html', {
        'featured_plots': featured_plots,
        'total_plots': total_plots,
        'verified_count': verified_count,
        'total_brokers': total_brokers,
        'soil_types': soil_types,
        'common_crops': common_crops,
        'filter_soil_type': soil_type,
        'filter_crop': crop,
        'crop_presets': crop_presets,
        'active_soil_filters': {
            'ph_min': ph_min, 'ph_max': ph_max, 'om_min': om_min,
            'n_min': n_min, 'p_min': p_min, 'k_min': k_min, 'ec_max': ec_max, 'texture': texture
        },
    })


def ajax_search(request):
    """Return rendered market grid fragment for AJAX search requests."""
    verified_plots = Plot.objects.filter(
        verification_status__status="verified"
    ).prefetch_related('images_list').select_related('broker', 'verification_status')
    verified_plots = verified_plots.order_by('-created_at')

    # Filters (same as home)
    soil_type = request.GET.get('soil_type')
    crop = request.GET.get('crop') or request.GET.get('crop_preset')
    ph_min = request.GET.get('ph_min')
    ph_max = request.GET.get('ph_max')
    om_min = request.GET.get('om_min')
    n_min = request.GET.get('n_min')
    p_min = request.GET.get('p_min')
    k_min = request.GET.get('k_min')
    ec_max = request.GET.get('ec_max')
    texture = request.GET.get('texture')

    if soil_type:
        verified_plots = verified_plots.filter(soil_type__icontains=soil_type)
    if crop:
        verified_plots = verified_plots.filter(crop_suitability__icontains=crop)

    crop_presets = {
        'Maize': {'ph_min': 5.8, 'ph_max': 7.0, 'om_min': 2.0},
        'Wheat': {'ph_min': 6.0, 'ph_max': 7.5, 'om_min': 1.5},
        'Rice': {'ph_min': 5.5, 'ph_max': 6.5, 'om_min': 1.0},
        'Coffee': {'ph_min': 5.0, 'ph_max': 6.5, 'om_min': 3.0},
    }

    soil_filters = {}
    try:
        if ph_min:
            soil_filters['soil_reports__pH__gte'] = float(ph_min)
        if ph_max:
            soil_filters['soil_reports__pH__lte'] = float(ph_max)
        if om_min:
            soil_filters['soil_reports__organic_matter_pct__gte'] = float(om_min)
        if n_min:
            soil_filters['soil_reports__nitrogen_mgkg__gte'] = float(n_min)
        if p_min:
            soil_filters['soil_reports__phosphorus_mgkg__gte'] = float(p_min)
        if k_min:
            soil_filters['soil_reports__potassium_mgkg__gte'] = float(k_min)
        if ec_max:
            soil_filters['soil_reports__ec_salinity__lte'] = float(ec_max)
        if texture:
            if ',' in texture:
                parts = [float(x) for x in texture.split(',') if x.strip()]
                if len(parts) == 3:
                    soil_filters['soil_reports__sand_pct__gte'] = parts[0]
                    soil_filters['soil_reports__silt_pct__gte'] = parts[1]
                    soil_filters['soil_reports__clay_pct__gte'] = parts[2]
            else:
                soil_filters['soil_reports__report_file__icontains'] = texture
    except ValueError:
        soil_filters = {}

    if crop and crop in crop_presets and not any([ph_min, ph_max, om_min, n_min, p_min, k_min, ec_max, texture]):
        preset = crop_presets[crop]
        soil_filters['soil_reports__pH__gte'] = preset.get('ph_min')
        soil_filters['soil_reports__pH__lte'] = preset.get('ph_max')
        if preset.get('om_min'):
            soil_filters['soil_reports__organic_matter_pct__gte'] = preset.get('om_min')

    if soil_filters:
        verified_plots = verified_plots.filter(**soil_filters).distinct()

    # Pagination
    paginator = Paginator(verified_plots, 15)
    page_number = request.GET.get('page')
    featured_plots = paginator.get_page(page_number)

    html = render_to_string('listings/_market_grid.html', {
        'featured_plots': featured_plots,
        'request': request,
    })

    return JsonResponse({'html': html})

from decimal import Decimal

def plot_detail(request, id):
    """View individual plot details"""
    plot = get_object_or_404(
        Plot.objects.select_related('broker__user', 'verification_status')
                     .prefetch_related('images_list'),
        id=id
    )
    
    # Check if user is the broker (for edit permissions)
    is_owner = False
    if request.user.is_authenticated and hasattr(request.user, 'broker'):
        is_owner = plot.broker == request.user.broker
    
    # Get similar plots
    similar_plots = Plot.objects.filter(
        Q(location__icontains=plot.location.split(',')[0]) |  # Same area
        Q(soil_type=plot.soil_type) |  # Same soil type
        Q(price__range=(plot.price * Decimal('0.7'), plot.price * Decimal('1.3')))  # Fixed: use Decimal
    ).exclude(id=plot.id).filter(
        verification_status__status='verified'
    )[:4]
    
    context = {
        'plot': plot,
        'is_owner': is_owner,
        'similar_plots': similar_plots,
        'today': date.today().strftime('%Y-%m-%d'),
    }
    
    return render(request, 'listings/details.html', context)


# ============ PLOT MANAGEMENT ============
@login_required
def add_plot(request):
    """Create new plot with ALL required documents upfront"""
    try:
        broker_profile = request.user.broker
        if not broker_profile.verified:
            messages.error(request, "Your broker account needs to be verified before you can list plots.")
            return redirect("listings:upgrade_broker")
    except Broker.DoesNotExist:
        messages.error(request, "You must be a verified broker to list land.")
        return redirect("listings:upgrade_role")

    if request.method == "POST":
        # Debug: Check what data is being received
        print("\n=== DEBUG: FORM DATA RECEIVED ===")
        print("POST keys:", list(request.POST.keys()))
        print("FILES keys:", list(request.FILES.keys()))
        
        for key in request.FILES.keys():
            files = request.FILES.getlist(key)
            print(f"{key}: {len(files)} files")
            for f in files:
                print(f"  - {f.name} ({f.size} bytes)")
        print("================================\n")
        
        # Create form with POST data and FILES
        plot_form = PlotForm(request.POST, request.FILES)
        
        if plot_form.is_valid():
            try:
                # Save plot with broker info
                plot = plot_form.save(commit=False)
                plot.broker = broker_profile
                plot.save()  # This saves all fields including documents
                
                # IMPORTANT: The form's save() method handles images
                # But let's double-check by handling them here too
                images = request.FILES.getlist('images')
                if images:
                    for image in images[:5]:
                        PlotImage.objects.create(plot=plot, image=image)
                else:
                    # If no images were uploaded through the images field,
                    # check if they came as part of the form
                    if 'images' not in request.FILES and plot_form.cleaned_data.get('images'):
                        for image in plot_form.cleaned_data['images'][:5]:
                            PlotImage.objects.create(plot=plot, image=image)
                
                # Debug: Check what was saved
                print("\n=== DEBUG: SAVED DATA ===")
                print(f"Plot saved with ID: {plot.id}")
                print(f"Title: {plot.title}")
                print(f"Location: {plot.location}")
                print(f"Price: {plot.price}")
                print(f"Area: {plot.area}")
                print(f"Soil Type: {plot.soil_type}")
                print(f"pH Level: {plot.ph_level}")
                print(f"Crop Suitability: {plot.crop_suitability}")
                print(f"Title Deed: {plot.title_deed.name if plot.title_deed else 'None'}")
                print(f"Soil Report: {plot.soil_report.name if plot.soil_report else 'None'}")
                print(f"Official Search: {plot.official_search.name if plot.official_search else 'None'}")
                print(f"Seller ID: {plot.seller_id.name if plot.seller_id else 'None'}")
                print(f"KRA PIN: {plot.kra_pin.name if plot.kra_pin else 'None'}")
                print(f"Images count: {plot.images_list.count()}")
                print("===========================\n")
                
                # Create verification status
                PlotVerificationStatus.objects.create(plot=plot, status='pending')
                
                messages.success(request, 
                    "✅ Plot submitted successfully! Your listing is now under verification review."
                )
                return redirect("listings:plot_detail", id=plot.id)

            except Exception as e:
                messages.error(request, f"❌ Error creating plot: {str(e)}")
                # Log the error for debugging
                logger = logging.getLogger(__name__)
                logger.error(f"Error creating plot: {str(e)}", exc_info=True)
                print(f"ERROR: {str(e)}")  # Debug print
        else:
            # Show form errors in a user-friendly way
            print("\n=== DEBUG: FORM ERRORS ===")  # Debug
            print(f"Form errors: {plot_form.errors}")  # Debug
            
            error_messages = []
            
            # Handle general form errors
            if plot_form.non_field_errors():
                for error in plot_form.non_field_errors():
                    error_messages.append(f"Form error: {error}")
            
            # Handle field-specific errors
            for field, errors in plot_form.errors.items():
                field_label = plot_form.fields[field].label if field in plot_form.fields else field
                for error in errors:
                    error_messages.append(f"{field_label}: {error}")
            
            # Display all errors
            for error_msg in error_messages:
                messages.error(request, error_msg)
            
            # Also log for debugging
            logger = logging.getLogger(__name__)
            logger.error(f"Form validation errors: {plot_form.errors}")
    else:
        # Pre-fill form with broker info if available
        initial_data = {}
        if hasattr(request.user, 'broker'):
            broker = request.user.broker
            # You could pre-fill location based on broker's common areas
            initial_data['crop_suitability'] = 'Maize, Beans, Vegetables'
        
        plot_form = PlotForm(initial=initial_data)

    return render(request, "listings/add_plot.html", {
        "form": plot_form,
        "broker": request.user.broker if hasattr(request.user, 'broker') else None,
    })

@login_required
def edit_plot(request, id):
    """Edit existing plot - documents optional, can update existing"""
    try:
        plot = Plot.objects.get(id=id, broker=request.user.broker)
    except Plot.DoesNotExist:
        messages.error(request, "Plot not found or you don't have permission to edit it.")
        return redirect('listings:home')
    
    if request.method == 'POST':
        form = PlotForm(request.POST, request.FILES, instance=plot)
        if form.is_valid():
            plot = form.save(commit=False)
            plot.save()
            
            # Handle new images
            images = request.FILES.getlist('images')
            for image in images[:5]:
                if image:
                    PlotImage.objects.create(plot=plot, image=image)
            
            messages.success(request, "✅ Plot updated successfully!")
            return redirect('listings:plot_detail', id=plot.id)
        else:
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f"{field}: {error}")
    else:
        form = PlotForm(instance=plot)
    
    # Get existing images to display in template
    existing_images = plot.images_list.all()
    
    return render(request, 'listings/edit_plot.html', {
        'form': form,
        'plot': plot,
        'existing_images': existing_images,
    })

@login_required
def delete_image(request, id):
    """Delete plot image"""
    try:
        image = PlotImage.objects.get(id=id, plot__broker=request.user.broker)
        plot_id = image.plot.id
        image.delete()
        messages.success(request, "Image deleted successfully.")
        return redirect('listings:edit_plot', id=plot_id)
    except PlotImage.DoesNotExist:
        messages.error(request, "Image not found or you don't have permission to delete it.")
        return redirect('listings:home')


# ============ DOCUMENT MANAGEMENT ============
REQUIRED_DOC_TYPES = [
    'title_deed',
    'official_search',
    'seller_id',
    'kra_pin',
]

@login_required
def upload_checklist(request, plot_id):
    """Legacy checklist view - redirects to edit page with message"""
    try:
        plot = Plot.objects.get(id=plot_id, broker=request.user.broker)
    except Plot.DoesNotExist:
        messages.error(request, "Plot not found or you don't have permission to access it.")
        return redirect('listings:my_plots')
    
    # Get missing docs
    missing_docs = []
    for doc_type in REQUIRED_DOC_TYPES:
        if doc_type == 'title_deed':
            if not plot.title_deed:
                missing_docs.append(doc_type)
        else:
            if not plot.verification_docs.filter(doc_type=doc_type).exists():
                missing_docs.append(doc_type)
    
    if request.method == 'POST':
        form = VerificationDocumentForm(request.POST, request.FILES)
        if form.is_valid():
            doc = form.save(commit=False)
            doc.plot = plot
            doc_type = request.POST.get('doc_type')
            if doc_type:
                doc.doc_type = doc_type
            doc.save()
            
            messages.success(request, f"Document uploaded successfully!")
            return redirect('listings:upload_checklist', plot_id=plot.id)
    else:
        form = VerificationDocumentForm()
    
    messages.info(request, "Note: All documents should be uploaded during plot creation. Use edit page for updates.")
    return render(request, 'listings/upload_checklist.html', {
        'plot': plot,
        'missing_docs': missing_docs,
        'form': form,
        'required_docs': REQUIRED_DOC_TYPES,
    })

@login_required
def upload_verification_doc(request, plot_id):
    """Upload verification document for existing plot"""
    plot = get_object_or_404(Plot, id=plot_id)

    if not hasattr(request.user, 'profile') or not request.user.profile.is_broker:
        return redirect('listings:home')

    if request.method == 'POST':
        form = VerificationDocumentForm(request.POST, request.FILES)
        if form.is_valid():
            doc = form.save(commit=False)
            doc.plot = plot
            doc.uploaded_by = request.user
            doc.save()
            return redirect('listings:plot_detail', id=plot.id)
    else:
        form = VerificationDocumentForm()

    return render(request, 'listings/dashboard/upload_verification.html', {'form': form, 'plot': plot})


# ============ DASHBOARD VIEWS ============
@login_required
def staff_dashboard(request):
    """Main dashboard for sellers and brokers"""
    context = {}
    
    # Check user type
    is_seller = hasattr(request.user, 'sellerprofile')
    is_broker = hasattr(request.user, 'broker')
    
    if not (is_seller or is_broker):
        messages.error(request, "You need to be a seller or broker to access this dashboard.")
        return redirect('listings:home')
    
    # Get user's plots
    plots = Plot.objects.none()
    if is_broker:
        plots = Plot.objects.filter(broker=request.user.broker)
    elif is_seller:
        plots = Plot.objects.filter(broker__user=request.user)
    
    # Plot statistics - all status options
    total_plots = plots.count()
    verified_plots = plots.filter(verification_status__status='verified').count()
    in_review_plots = plots.filter(verification_status__status='in_review').count()
    pending_plots = plots.filter(verification_status__status='pending').count()
    rejected_plots = plots.filter(verification_status__status='rejected').count()
    
    # Calculate percentages
    if total_plots > 0:
        verified_percentage = (verified_plots / total_plots) * 100
        in_review_percentage = (in_review_plots / total_plots) * 100
        pending_percentage = (pending_plots / total_plots) * 100
        rejected_percentage = (rejected_plots / total_plots) * 100
    else:
        verified_percentage = 0
        in_review_percentage = 0
        pending_percentage = 0
        rejected_percentage = 0
    
    # Recent activities
    recent_interests = UserInterest.objects.filter(plot__in=plots).order_by('-created_at')[:5]
    
    # Calculate buyer interest percentage
    if total_plots > 0:
        buyer_interest_percentage = (recent_interests.count() / total_plots) * 100
    else:
        buyer_interest_percentage = 0
    
    # Plot status breakdown
    plot_status_data = {
        'Verified': verified_plots,
        'In Review': in_review_plots,
        'Pending': pending_plots,
        'Rejected': rejected_plots,
    }
    
    context.update({
        'is_seller': is_seller,
        'is_broker': is_broker,
        'total_plots': total_plots,
        'verified_plots': verified_plots,
        'in_review_plots': in_review_plots,
        'pending_plots': pending_plots,
        'rejected_plots': rejected_plots,
        'verified_percentage': verified_percentage,
        'in_review_percentage': in_review_percentage,
        'pending_percentage': pending_percentage,
        'rejected_percentage': rejected_percentage,
        'buyer_interest_percentage': buyer_interest_percentage,
        'recent_interests': recent_interests,
        'plot_status_data': plot_status_data,
        'plots': plots.order_by('-id')[:5],
    })
    
    # Add profile info
    if is_seller:
        context['profile'] = request.user.sellerprofile
        context['profile_type'] = 'Seller'
    elif is_broker:
        context['profile'] = request.user.broker
        context['profile_type'] = 'Broker'
    
    return render(request, 'listings/dashboard/staff_dashboard.html', context)

@login_required
def my_plots(request):
    """View all plots with verification status"""
    is_broker = hasattr(request.user, 'broker')
    
    if not is_broker:
        messages.error(request, "Only brokers can list plots.")
        return redirect('listings:home')
    
    plots = Plot.objects.filter(broker=request.user.broker)
    
    # Filtering
    status_filter = request.GET.get('status', 'all')
    if status_filter != 'all':
        plots = plots.filter(verification_status__status=status_filter)
    
    # Search
    search_query = request.GET.get('search', '')
    if search_query:
        plots = plots.filter(
            Q(title__icontains=search_query) |
            Q(location__icontains=search_query)
        )
    
    # Pagination
    paginator = Paginator(plots.order_by('-id'), 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    # Status counts for filters
    status_counts = {
        'all': plots.count(),
        'verified': plots.filter(verification_status__status='verified').count(),
        'in_review': plots.filter(verification_status__status='in_review').count(),
        'pending': plots.filter(verification_status__status='pending').count(),
        'rejected': plots.filter(verification_status__status='rejected').count(),
    }
    
    context = {
        'page_obj': page_obj,
        'status_filter': status_filter,
        'search_query': search_query,
        'status_counts': status_counts,
        'total_plots': plots.count(),
    }
    
    return render(request, 'listings/dashboard/my_plots.html', context)

@login_required
def plot_verification_detail(request, plot_id):
    """Detailed view of plot verification status"""
    plot = get_object_or_404(Plot, id=plot_id)
    
    # Check permission
    if not (hasattr(request.user, 'broker') and plot.broker == request.user.broker):
        messages.error(request, "You don't have permission to view this plot.")
        return redirect('listings:home')
    
    # Get verification status
    verification_status = getattr(plot, 'verification_status', None)
    
    # Get required documents status
    has_title_deed = bool(plot.title_deed)
    has_soil_report = bool(plot.soil_report)
    
    # Get verification documents
    verification_docs = plot.verification_docs.all()
    
    context = {
        'plot': plot,
        'verification_status': verification_status,
        'has_title_deed': has_title_deed,
        'has_soil_report': has_soil_report,
        'verification_docs': verification_docs,
        'documents_complete': has_title_deed,
    }
    
    return render(request, 'listings/dashboard/plot_verification_detail.html', context)

@login_required
def buyer_interests(request):
    """Manage buyer interests for plots"""
    is_broker = hasattr(request.user, 'broker')
    
    if not is_broker:
        messages.error(request, "Only brokers can view buyer interests.")
        return redirect('listings:home')
    
    interests = UserInterest.objects.filter(plot__broker=request.user.broker)
    
    # Filter by status
    status_filter = request.GET.get('status', 'all')
    if status_filter != 'all':
        interests = interests.filter(status=status_filter)
    
    # Search
    search_query = request.GET.get('search', '')
    if search_query:
        interests = interests.filter(
            Q(user__username__icontains=search_query) |
            Q(plot__title__icontains=search_query) |
            Q(message__icontains=search_query)
        )
    
    # Pagination
    paginator = Paginator(interests.order_by('-created_at'), 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    # Status counts
    status_counts = {
        'all': interests.count(),
        'pending': interests.filter(status='pending').count(),
        'contacted': interests.filter(status='contacted').count(),
        'scheduled': interests.filter(status='scheduled').count(),
        'rejected': interests.filter(status='rejected').count(),
    }
    
    context = {
        'page_obj': page_obj,
        'status_filter': status_filter,
        'search_query': search_query,
        'status_counts': status_counts,
    }
    
    return render(request, 'listings/dashboard/buyer_interests.html', context)

@login_required
def update_interest_status(request, interest_id):
    """Update buyer interest status"""
    interest = get_object_or_404(UserInterest, id=interest_id)
    
    # Check permission
    if not (hasattr(request.user, 'broker') and interest.plot.broker == request.user.broker):
        messages.error(request, "You don't have permission to update this interest.")
        return redirect('listings:home')
    
    if request.method == 'POST':
        new_status = request.POST.get('status')
        notes = request.POST.get('notes', '')
        
        if new_status in ['pending', 'contacted', 'scheduled', 'rejected']:
            interest.status = new_status
            if notes:
                interest.notes = notes
            interest.save()
            
            messages.success(request, f"Interest status updated to {new_status}.")
        else:
            messages.error(request, "Invalid status.")
    
    return redirect('listings:buyer_interests')

@login_required
def profile_management(request):
    """Manage seller/broker profile"""
    is_seller = hasattr(request.user, 'sellerprofile')
    is_broker = hasattr(request.user, 'broker')
    
    if not (is_seller or is_broker):
        messages.error(request, "You need to be a seller or broker.")
        return redirect('listings:home')
    
    if request.method == 'POST':
        # Handle profile updates
        phone = request.POST.get('phone', '')
        
        if is_broker:
            broker = request.user.broker
            broker.phone = phone
            broker.save()
            messages.success(request, "Profile updated successfully.")
        elif is_seller:
            # Handle seller profile updates if needed
            pass
    
    context = {
        'is_seller': is_seller,
        'is_broker': is_broker,
    }
    
    if is_seller:
        context['profile'] = request.user.sellerprofile
    elif is_broker:
        context['profile'] = request.user.broker
    
    return render(request, 'listings/dashboard/profile_management.html', context)

@login_required
def dashboard_analytics(request):
    """Analytics dashboard for brokers/sellers"""
    is_broker = hasattr(request.user, 'broker')
    
    if not is_broker:
        messages.error(request, "Only brokers can view analytics.")
        return redirect('listings:home')
    
    plots = Plot.objects.filter(broker=request.user.broker)
    
    # Monthly plot additions
    monthly_stats = plots.annotate(
        month=TruncMonth('created_at')
    ).values('month').annotate(
        count=Count('id')
    ).order_by('month')
    
    # Price distribution
    price_ranges = {
        'Under 1M': plots.filter(price__lt=1000000).count(),
        '1M - 5M': plots.filter(price__gte=1000000, price__lt=5000000).count(),
        '5M - 10M': plots.filter(price__gte=5000000, price__lt=10000000).count(),
        '10M+': plots.filter(price__gte=10000000).count(),
    }
    
    # Location distribution
    location_stats = plots.values('location').annotate(
        count=Count('id')
    ).order_by('-count')[:10]
    
    context = {
        'monthly_stats': list(monthly_stats),
        'price_ranges': price_ranges,
        'location_stats': list(location_stats),
        'total_interests': UserInterest.objects.filter(plot__broker=request.user.broker).count(),
        'avg_price': plots.aggregate(avg=Avg('price'))['avg'] or 0,
    }
    
    return render(request, 'listings/dashboard/analytics.html', context)  # Fixed template path


# ============ VERIFICATION ADMIN ============
@login_required
def verification_dashboard(request):
    """Admin verification dashboard"""
    if not request.user.is_staff:
        return redirect('listings:home')

    pending = PlotVerificationStatus.objects.filter(status='pending')
    return render(request, 'listings/verification_dashboard.html', {'pending': pending})

@login_required
def review_plot(request, plot_id):
    """Admin plot review"""
    if not request.user.is_staff:
        return redirect('listings:home')

    plot = get_object_or_404(Plot, id=plot_id)
    status_obj, _ = PlotVerificationStatus.objects.get_or_create(plot=plot)

    if request.method == 'POST':
        vform = PlotVerificationStatusForm(request.POST, instance=status_obj)
        sform = TitleSearchResultForm(request.POST, request.FILES,
                                     instance=getattr(plot, 'search_result', None))
        if vform.is_valid() and sform.is_valid():
            sform.save()
            vform.save()
            return redirect('listings:verification_dashboard')
    else:
        vform = PlotVerificationStatusForm(instance=status_obj)
        sform = TitleSearchResultForm(instance=getattr(plot, 'search_result', None))

    docs = plot.verification_docs.all()
    return render(request, 'listings/review_plot.html', {
        'plot': plot,
        'docs': docs,
        'vform': vform,
        'sform': sform,
    })

# MESSAGING
@login_required
def contact_broker(request, plot_id):
    """Handle broker contact form submission"""
    plot = get_object_or_404(Plot, id=plot_id)
    
    if request.method == 'POST':
        message = request.POST.get('message', '')
        
        # Send email to broker
        subject = f"New Inquiry about your plot: {plot.title}"
        body = f"""
        Hi {plot.broker.user.get_full_name()},
        
        You have a new inquiry about your plot listing:
        
        Plot: {plot.title} (ID: #{plot.id})
        Location: {plot.location}
        Price: KES {plot.price}
        
        Message from {request.user.get_full_name()} ({request.user.email}):
        {message}
        
        Please respond to this inquiry within 24 hours.
        
        Best regards,
        AgriPlot Connect Team
        """
        
        try:
            send_mail(
                subject=subject,
                message=body,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[plot.broker.user.email],
                fail_silently=False,
            )
            
            # Also send confirmation to the buyer
            send_mail(
                subject=f"Message sent to broker regarding: {plot.title}",
                message=f"Your message has been sent to {plot.broker.user.get_full_name()}. They will contact you soon.",
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[request.user.email],
                fail_silently=False,
            )
            
            # Log the contact request
            ContactRequest.objects.create(
                user=request.user,
                plot=plot,
                broker=plot.broker,
                request_type='message',
                message=message
            )
            
            messages.success(request, "Message sent successfully! The broker will contact you soon.")
            
        except Exception as e:
            messages.error(request, f"Failed to send message. Error: {str(e)}")
        
        return redirect('listings:plot_detail', id=plot_id)
    
    messages.error(request, "Invalid request method.")
    return redirect('listings:plot_detail', id=plot_id)


@login_required
def request_contact_details(request, plot_id):
    """API endpoint to request broker contact details"""
    if request.method != 'POST':
        return JsonResponse({'error': 'Invalid request method'}, status=400)
    
    plot = get_object_or_404(Plot, id=plot_id)
    
    try:
        # Log the request
        ContactRequest.objects.create(
            user=request.user,
            plot=plot,
            broker=plot.broker,
            request_type='phone_request'
        )
        
        # Notify broker via email
        subject = f"Contact Request for your plot: {plot.title}"
        message = f"""
        User {request.user.get_full_name()} ({request.user.email}) 
        has requested your contact details for plot: {plot.title}
        
        Plot Details:
        - Title: {plot.title}
        - Location: {plot.location}
        - Price: KES {plot.price}
        
        Please contact the user at your earliest convenience.
        
        Best regards,
        AgriPlot Connect Team
        """
        
        send_mail(
            subject=subject,
            message=message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[plot.broker.user.email],
            fail_silently=False,
        )
        
        return JsonResponse({
            'success': True,
            'message': 'Contact request sent. The broker will contact you shortly.'
        })
        
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': f'Failed to send request: {str(e)}'
        }, status=500)


@login_required
def log_phone_view(request, plot_id):
    """Log when user views phone number"""
    if request.method != 'POST':
        return JsonResponse({'error': 'Invalid request method'}, status=400)
    
    plot = get_object_or_404(Plot, id=plot_id)
    
    try:
        ContactRequest.objects.create(
            user=request.user,
            plot=plot,
            broker=plot.broker,
            request_type='phone_view'
        )
        
        return JsonResponse({'success': True})
        
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)
    

@login_required
def request_contact_details(request, plot_id):
    """API endpoint to request broker contact details"""
    plot = get_object_or_404(Plot, id=plot_id)
    
    # Log the request
    ContactRequest.objects.create(
        user=request.user,
        plot=plot,
        broker=plot.broker,
        request_type='phone_request'
    )
    
    # Notify broker via email
    send_mail(
        subject=f"Contact Request for your plot: {plot.title}",
        message=f"User {request.user.email} has requested your contact details for plot {plot.title}.",
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[plot.broker.user.email],
    )
    
    return JsonResponse({
        'success': True,
        'message': 'Contact request sent. The broker will contact you shortly.'
    })

@login_required
def log_phone_view(request, plot_id):
    """Log when user views phone number"""
    plot = get_object_or_404(Plot, id=plot_id)
    
    ContactRequest.objects.create(
        user=request.user,
        plot=plot,
        broker=plot.broker,
        request_type='phone_view'
    )


# ============ PLOT REACTIONS ============
@login_required
def toggle_plot_reaction(request, plot_id):
    """Toggle a reaction on a plot (love, like, or potential)"""
    if request.method != 'POST':
        return JsonResponse({'error': 'Invalid request method'}, status=400)
    
    plot = get_object_or_404(Plot, id=plot_id)
    reaction_type = request.POST.get('reaction_type', '').lower()
    
    # Validate reaction type
    valid_reactions = ['love', 'like', 'potential']
    if reaction_type not in valid_reactions:
        return JsonResponse({'error': 'Invalid reaction type'}, status=400)
    
    # Toggle reaction: if exists, delete; if not exists, create
    reaction, created = PlotReaction.objects.get_or_create(
        user=request.user,
        plot=plot,
        reaction_type=reaction_type
    )
    
    if not created:
        # Reaction already exists, so delete it (toggle off)
        reaction.delete()
        user_has_reaction = False
    else:
        # Reaction was created
        user_has_reaction = True
    
    # Get updated counts
    reaction_counts = plot.get_reaction_counts()
    
    return JsonResponse({
        'success': True,
        'user_has_reaction': user_has_reaction,
        'reaction_type': reaction_type,
        'counts': reaction_counts,
        'total_reactions': plot.total_reaction_count()
    })


@login_required
def get_plot_reactions(request, plot_id):
    """Get all reaction data for a plot"""
    plot = get_object_or_404(Plot, id=plot_id)
    
    user_reactions = plot.get_user_reactions(request.user)
    reaction_counts = plot.get_reaction_counts()
    
    return JsonResponse({
        'plot_id': plot_id,
        'user_reactions': user_reactions,
        'counts': reaction_counts,
        'total_reactions': plot.total_reaction_count()
    })
    return JsonResponse({'success': True})