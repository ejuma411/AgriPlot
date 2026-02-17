from datetime import date
import logging

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.views import LoginView
from django.contrib.admin.views.decorators import staff_member_required
from django.core.files.storage import FileSystemStorage, default_storage
from django.core.files.base import ContentFile
from django.core.mail import send_mail, EmailMessage
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.db.models import Q, Count, Avg
from django.db.models.functions import TruncMonth
from django.http import Http404, JsonResponse, HttpResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.template.loader import render_to_string
from django.core.exceptions import ValidationError
from decimal import Decimal
from django.contrib.contenttypes.models import ContentType
from django.utils import timezone

# Import formtools if you're using it
try:
    from formtools.wizard.views import SessionWizardView
except ImportError:
    SessionWizardView = None
    print("Warning: formtools not installed. Install with: pip install django-formtools")

# Import all forms
from .forms import *

# Import all models
from .models import *

# FYP Q8: audit logging
from .utils import log_audit

logger = logging.getLogger(__name__)

wizard_file_storage = FileSystemStorage(location='/tmp/agriplot_uploads')


# ============ LANDOWNER WIZARD ============
FORMS = [
    ("personal", LandownerStep1Form),
    ("verification", LandownerStep2Form),
    ("documents", LandownerStep3Form),
    ("confirmation", LandownerStep4Form),
]

TEMPLATES = {
    "personal": "auth/landowner_wizard_step.html",
    "verification": "auth/landowner_wizard_step.html",
    "documents": "auth/landowner_wizard_step.html",
    "confirmation": "auth/landowner_wizard_step.html",
}


class LandownerWizard(SessionWizardView):
    form_list = FORMS
    file_storage = wizard_file_storage

    def get_template_names(self):
        return [TEMPLATES[self.steps.current]]

    def done(self, form_list, **kwargs):
        """Process all wizard forms and create landowner"""
        form_data = {form.prefix: form.cleaned_data for form in form_list}
        
        try:
            # Extract data from forms
            personal_data = form_data.get('personal', {})
            documents_data = form_data.get('documents', {})
            
            # Create user
            user = User.objects.create_user(
                username=personal_data.get('username'),
                email=personal_data.get('email'),
                password=personal_data.get('password1'),
                first_name=personal_data.get('first_name'),
                last_name=personal_data.get('last_name')
            )
            
            # Create profile
            Profile.objects.create(
                user=user,
                role='landowner'
            )
            
            # Create landowner profile
            LandownerProfile.objects.create(
                user=user,
                national_id=documents_data.get('national_id'),
                kra_pin=documents_data.get('kra_pin'),
                verified=False
            )
            
            # Auto login
            auth_user = authenticate(
                username=personal_data.get('username'),
                password=personal_data.get('password1')
            )
            if auth_user:
                login(self.request, auth_user)
                messages.success(self.request, "Landowner account created successfully! Please wait for verification.")
                return redirect('listings:dashboard')
            
        except Exception as e:
            messages.error(self.request, f"Error creating account: {str(e)}")
            return redirect('listings:register_choice')
        
        return redirect('listings:home')


# ============ AUTHENTICATION & REGISTRATION ============
def custom_logout(request):
    logout(request)
    return redirect('listings:home')


def register_choice(request):
    """Display registration choice page"""
    return render(request, "auth/register_choice.html")


class CustomLoginView(LoginView):
    template_name = "auth/login.html"


def register_buyer(request):
    """Handle buyer registration"""
    if request.method == "POST":
        form = UserCreationForm(request.POST)
        if form.is_valid():
            try:
                user = form.save()
                
                # Check if profile already exists
                profile, created = Profile.objects.get_or_create(
                    user=user,
                    defaults={
                        'role': 'buyer',
                        'phone': '',
                        'address': ''
                    }
                )
                
                if created:
                    logger.info(f"✅ New buyer profile created for {user.username}")
                else:
                    logger.info(f"ℹ️ Existing profile updated for {user.username}")
                    profile.role = 'buyer'
                    profile.save()
                
                messages.success(request, "Account created successfully! You can now log in.")
                return redirect('login')
                
            except Exception as e:
                messages.error(request, f"Error creating account: {str(e)}")
                logger.error(f"Buyer registration error: {str(e)}")
    else:
        form = UserCreationForm()
    
    context = {
        'form': form,
        'role': 'Buyer'
    }
    return render(request, 'auth/register_buyer.html', context)


def register_landowner(request):
    """Handle landowner registration with document upload"""
    next_url = request.GET.get("next", "/")

    if request.method == "POST":
        form = LandownerRegistrationForm(request.POST, request.FILES)
        if form.is_valid():
            try:
                # Create user
                user = form.save(commit=False)
                user.first_name = form.cleaned_data["first_name"]
                user.last_name = form.cleaned_data["last_name"]
                user.email = form.cleaned_data["email"]
                user.save()

                # Get phone from form
                phone = form.cleaned_data.get("phone", "")

                # Create or update Profile with role and contact info
                profile, created = Profile.objects.get_or_create(
                    user=user,
                    defaults={
                        'role': 'landowner',
                        'phone': phone
                    }
                )
                
                if not created:
                    profile.role = 'landowner'
                    profile.phone = phone
                    profile.save()

                # Create or update LandownerProfile with uploaded files
                landowner_profile, created = LandownerProfile.objects.get_or_create(
                    user=user,
                    defaults={
                        'national_id': form.cleaned_data.get("national_id"),
                        'kra_pin': form.cleaned_data.get("kra_pin"),
                        'verified': False
                    }
                )
                
                if not created:
                    landowner_profile.national_id = form.cleaned_data.get("national_id")
                    landowner_profile.kra_pin = form.cleaned_data.get("kra_pin")
                    landowner_profile.verified = False
                    landowner_profile.save()

                logger.info(f"✅ Landowner registered/updated: {user.username}")

                # Auto login
                auth_user = authenticate(
                    username=form.cleaned_data["username"],
                    password=form.cleaned_data["password1"]
                )
                if auth_user:
                    login(request, auth_user)
                    messages.success(request, "Landowner account created successfully! Please wait for verification.")
                    return redirect(next_url)
                else:
                    messages.error(request, "Authentication failed. Please try logging in.")
                    return redirect('login')
                    
            except Exception as e:
                messages.error(request, f"Error creating account: {str(e)}")
                logger.error(f"Landowner registration error: {str(e)}")
    else:
        form = LandownerRegistrationForm()

    return render(request, "auth/register_landowner.html", {"form": form})


def register_agent(request):
    """Handle agent registration with professional documents"""
    next_url = request.GET.get("next", "/")

    if request.method == "POST":
        form = AgentRegistrationForm(request.POST, request.FILES)
        if form.is_valid():
            try:
                # Create user
                user = form.save(commit=False)
                user.first_name = form.cleaned_data["first_name"]
                user.last_name = form.cleaned_data["last_name"]
                user.email = form.cleaned_data["email"]
                user.save()

                # Get phone from form
                phone = form.cleaned_data["phone"]

                # Create or update Profile with role and contact info
                profile, created = Profile.objects.get_or_create(
                    user=user,
                    defaults={
                        'role': 'agent',
                        'phone': phone
                    }
                )
                
                if not created:
                    profile.role = 'agent'
                    profile.phone = phone
                    profile.save()

                # Create or update Agent with all professional fields
                agent, created = Agent.objects.get_or_create(
                    user=user,
                    defaults={
                        'phone': phone,
                        'id_number': form.cleaned_data["id_number"],
                        'license_number': form.cleaned_data["license_number"],
                        'license_doc': form.cleaned_data.get("license_doc"),
                        'kra_pin': form.cleaned_data.get("kra_pin"),
                        'practicing_certificate': form.cleaned_data.get("practicing_certificate"),
                        'good_conduct': form.cleaned_data.get("good_conduct"),
                        'professional_indemnity': form.cleaned_data.get("professional_indemnity"),
                        'verified': False
                    }
                )
                
                if not created:
                    agent.phone = phone
                    agent.id_number = form.cleaned_data["id_number"]
                    agent.license_number = form.cleaned_data["license_number"]
                    if form.cleaned_data.get("license_doc"):
                        agent.license_doc = form.cleaned_data["license_doc"]
                    if form.cleaned_data.get("kra_pin"):
                        agent.kra_pin = form.cleaned_data["kra_pin"]
                    agent.save()

                logger.info(f"✅ Agent registered/updated: {user.username}")

                # Auto login
                auth_user = authenticate(
                    username=form.cleaned_data["username"],
                    password=form.cleaned_data["password1"]
                )
                if auth_user:
                    login(request, auth_user)
                    messages.success(request, "Agent account created successfully! Please wait for verification.")
                    return redirect(next_url)
                else:
                    messages.error(request, "Authentication failed. Please try logging in.")
                    return redirect('listings:login')
                    
            except Exception as e:
                messages.error(request, f"Error creating account: {str(e)}")
                logger.error(f"Agent registration error: {str(e)}")
    else:
        form = AgentRegistrationForm()

    return render(request, "auth/register_agent.html", {"form": form})

# ============ PUBLIC PAGES ============
def home(request):
    """Homepage with plot listings"""
    # Get verified plots - removed verification from select_related
    verified_plots = Plot.objects.filter(
        verification__current_stage="approved"
    ).prefetch_related('images').select_related('agent__user')  # ✅ Removed 'verification'
    
    # Apply ordering (most recent first)
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
    listing_type = request.GET.get('listing_type')
    land_type = request.GET.get('land_type')
    min_price = request.GET.get('min_price')
    max_price = request.GET.get('max_price')
    min_area = request.GET.get('min_area')
    max_area = request.GET.get('max_area')

    if soil_type:
        verified_plots = verified_plots.filter(soil_type__icontains=soil_type)
    if crop:
        verified_plots = verified_plots.filter(crop_suitability__icontains=crop)
    if listing_type:
        verified_plots = verified_plots.filter(listing_type=listing_type)
    if land_type:
        verified_plots = verified_plots.filter(land_type=land_type)
    if min_price:
        verified_plots = verified_plots.filter(price__gte=min_price)
    if max_price:
        verified_plots = verified_plots.filter(price__lte=max_price)
    if min_area:
        verified_plots = verified_plots.filter(area__gte=min_area)
    if max_area:
        verified_plots = verified_plots.filter(area__lte=max_area)

    # Crop-presets
    crop_presets = {
        'Maize': {'ph_min': 5.8, 'ph_max': 7.0, 'om_min': 2.0},
        'Wheat': {'ph_min': 6.0, 'ph_max': 7.5, 'om_min': 1.5},
        'Rice': {'ph_min': 5.5, 'ph_max': 6.5, 'om_min': 1.0},
        'Coffee': {'ph_min': 5.0, 'ph_max': 6.5, 'om_min': 3.0},
    }

    # Apply soil metric filters via SoilReport
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

    # Apply crop preset if no explicit filters
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
    verified_count = Plot.objects.filter(verification__current_stage="approved").count()
    total_agents = Agent.objects.filter(verified=True).count()
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
        'total_agents': total_agents,
        'soil_types': soil_types,
        'common_crops': common_crops,
        'filter_soil_type': soil_type,
        'filter_crop': crop,
        'filter_listing_type': listing_type,
        'filter_land_type': land_type,
        'crop_presets': crop_presets,
        'active_soil_filters': {
            'ph_min': ph_min, 'ph_max': ph_max, 'om_min': om_min,
            'n_min': n_min, 'p_min': p_min, 'k_min': k_min, 
            'ec_max': ec_max, 'texture': texture
        },
    })

def ajax_search(request):
    """Return rendered market grid fragment for AJAX search requests."""
    verified_plots = Plot.objects.filter(
        verification__current_stage="approved"
    ).prefetch_related('images').select_related('agent__user')  # ✅ Removed 'verification'
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
    listing_type = request.GET.get('listing_type')
    land_type = request.GET.get('land_type')

    if soil_type:
        verified_plots = verified_plots.filter(soil_type__icontains=soil_type)
    if crop:
        verified_plots = verified_plots.filter(crop_suitability__icontains=crop)
    if listing_type:
        verified_plots = verified_plots.filter(listing_type=listing_type)
    if land_type:
        verified_plots = verified_plots.filter(land_type=land_type)

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

def plot_detail(request, id):
    """View individual plot details"""
    plot = get_object_or_404(
        Plot.objects.select_related(
            'agent__user', 
            'landowner__user'
        ).prefetch_related(
            'images', 
            'verification_docs'
        ),
        id=id
    )
    
    # Get verification status separately
    from django.contrib.contenttypes.models import ContentType
    content_type = ContentType.objects.get_for_model(Plot)
    try:
        verification = VerificationStatus.objects.get(
            content_type=content_type,
            object_id=plot.id
        )
    except VerificationStatus.DoesNotExist:
        verification = None
    
    # Check if user is the agent or landowner (for edit permissions)
    is_owner = False
    if request.user.is_authenticated:
        if hasattr(request.user, 'agent') and plot.agent == request.user.agent:
            is_owner = True
        elif hasattr(request.user, 'landownerprofile') and plot.landowner == request.user.landownerprofile:
            is_owner = True
    
    # Get similar plots based on location, soil type, and price
    similar_plots = Plot.objects.filter(
        verification__current_stage='approved'
    ).exclude(id=plot.id)
    
    # Build Q objects for similarity
    similarity_q = Q()
    if plot.location:
        location_parts = plot.location.split(',')[0]
        similarity_q |= Q(location__icontains=location_parts)
    if plot.soil_type:
        similarity_q |= Q(soil_type=plot.soil_type)
    if plot.price:
        similarity_q |= Q(price__range=(plot.price * Decimal('0.7'), plot.price * Decimal('1.3')))
    
    similar_plots = similar_plots.filter(similarity_q)[:4]
    
    context = {
        'plot': plot,
        'verification': verification,  # Pass verification to template
        'is_owner': is_owner,
        'similar_plots': similar_plots,
        'today': date.today().strftime('%Y-%m-%d'),
    }
    
    return render(request, 'listings/details.html', context)
# ============ PLOT MANAGEMENT ============
@login_required
def add_plot(request):
    """Create new plot with ALL required documents upfront"""
    # Check if user is agent or landowner
    is_agent = hasattr(request.user, 'agent')
    is_landowner = hasattr(request.user, 'landownerprofile')
    
    if not (is_agent or is_landowner):
        messages.error(request, "You must be a verified agent or landowner to list land.")
        return redirect("listings:register_choice")
    
    # Check verification status
    if is_agent and not request.user.agent.verified:
        messages.error(request, "Your agent account needs to be verified before you can list plots.")
        return redirect("listings:register_agent")
    
    if is_landowner and not request.user.landownerprofile.verified:
        messages.error(request, "Your landowner account needs to be verified before you can list plots.")
        return redirect("listings:register_landowner")

    if request.method == "POST":
        # Determine the owner based on user type
        owner = None
        if is_agent:
            owner = request.user.agent
        elif is_landowner:
            owner = request.user.landownerprofile
        
        # Create form with POST data, FILES, and the owner
        plot_form = PlotForm(request.POST, request.FILES, owner=owner)
        
        # Debug: Print form data
        logger.info(f"User {request.user.username} attempting to add plot")
        logger.info(f"Is Agent: {is_agent}, Is Landowner: {is_landowner}")
        logger.info(f"Owner object: {owner}")
        logger.info(f"POST keys: {list(request.POST.keys())}")
        logger.info(f"FILES keys: {list(request.FILES.keys())}")
        
        if plot_form.is_valid():
            try:
                # Save the plot - owner is handled in form.save()
                plot = plot_form.save()
                
                logger.info(f"Plot saved successfully! ID: {plot.id}")
                logger.info(f"Agent: {plot.agent}, Landowner: {plot.landowner}")
                
                log_audit(request, 'create_plot', object_type='Plot', object_id=plot.id)

                # ✅ FIX: Create verification status using VerificationStatus model
                content_type = ContentType.objects.get_for_model(Plot)
                verification, created = VerificationStatus.objects.get_or_create(
                    content_type=content_type,
                    object_id=plot.id,
                    defaults={
                        'current_stage': 'document_uploaded',
                        'document_uploaded_at': timezone.now(),
                        'stage_details': {
                            'created_by': request.user.username,
                            'created_at': timezone.now().isoformat(),
                            'plot_title': plot.title
                        }
                    }
                )
                
                if created:
                    logger.info(f"✅ Verification status created for plot {plot.id}")
                else:
                    logger.info(f"ℹ️ Verification status already exists for plot {plot.id}")
                
                # Handle image uploads
                images = request.FILES.getlist('images')
                if images:
                    for image in images[:5]:
                        PlotImage.objects.create(plot=plot, image=image)
                    logger.info(f"✅ {len(images[:5])} images uploaded for plot {plot.id}")
                else:
                    logger.warning(f"⚠️ No images uploaded for plot {plot.id}")
                
                messages.success(request, 
                    "✅ Plot submitted successfully! Your listing is now under verification review."
                )
                return redirect("listings:plot_detail", id=plot.id)

            except Exception as e:
                messages.error(request, f"❌ Error creating plot: {str(e)}")
                logger.error(f"Error creating plot: {str(e)}", exc_info=True)
                
                # If plot was created but verification failed, try to clean up
                if 'plot' in locals() and plot.id:
                    try:
                        plot.delete()
                        logger.info(f"Cleaned up plot {plot.id} due to verification error")
                    except:
                        pass
        else:
            # Show form errors
            error_messages = []
            for field, errors in plot_form.errors.items():
                for error in errors:
                    error_msg = f"{field}: {error}"
                    error_messages.append(error_msg)
                    messages.error(request, error_msg)
            
            logger.error(f"Form validation errors: {error_messages}")
    else:
        # Pre-fill form with initial data based on user type
        initial_data = {
            'crop_suitability': 'Maize, Beans, Vegetables'
        }
        
        # If user is landowner, pre-fill with their details if available
        if is_landowner and request.user.landownerprofile:
            # You could add more pre-filled data here
            pass
        
        plot_form = PlotForm(initial=initial_data)

    return render(request, "listings/add_plot.html", {
        "form": plot_form,
        "is_agent": is_agent,
        "is_landowner": is_landowner,
        "profile_type": "Agent" if is_agent else "Landowner",
    })


@login_required
def edit_plot(request, id):
    """Edit existing plot"""
    try:
        plot = Plot.objects.get(id=id)
        # Check permission
        is_agent = hasattr(request.user, 'agent') and plot.agent == request.user.agent
        is_landowner = hasattr(request.user, 'landownerprofile') and plot.landowner == request.user.landownerprofile
        
        if not (is_agent or is_landowner):
            messages.error(request, "You don't have permission to edit this plot.")
            return redirect('listings:plot_detail', id=id)
            
    except Plot.DoesNotExist:
        messages.error(request, "Plot not found.")
        return redirect('listings:home')
    
    if request.method == 'POST':
        form = PlotForm(request.POST, request.FILES, instance=plot)
        if form.is_valid():
            plot = form.save()
            log_audit(request, 'edit_plot', object_type='Plot', object_id=plot.id, extra={'plot_id': plot.id})

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
    existing_images = plot.images.all()
    
    return render(request, 'listings/edit_plot.html', {
        'form': form,
        'plot': plot,
        'existing_images': existing_images,
    })


@login_required
def delete_image(request, id):
    """Delete plot image"""
    try:
        image = PlotImage.objects.get(id=id)
        plot = image.plot
        
        # Check permission
        is_agent = hasattr(request.user, 'agent') and plot.agent == request.user.agent
        is_landowner = hasattr(request.user, 'landownerprofile') and plot.landowner == request.user.landownerprofile
        
        if not (is_agent or is_landowner):
            messages.error(request, "You don't have permission to delete this image.")
            return redirect('listings:home')
        
        plot_id = image.plot.id
        image.delete()
        messages.success(request, "Image deleted successfully.")
        return redirect('listings:edit_plot', id=plot_id)
        
    except PlotImage.DoesNotExist:
        messages.error(request, "Image not found.")
        return redirect('listings:home')


# ============ DOCUMENT MANAGEMENT ============
REQUIRED_DOC_TYPES = [
    'title_deed',
    'official_search',
    'landowner_id',
    'kra_pin',
]


@login_required
def upload_verification_doc(request, plot_id):
    """Upload verification document for existing plot"""
    plot = get_object_or_404(Plot, id=plot_id)
    
    # Check permission
    is_agent = hasattr(request.user, 'agent') and plot.agent == request.user.agent
    is_landowner = hasattr(request.user, 'landownerprofile') and plot.landowner == request.user.landownerprofile
    
    if not (is_agent or is_landowner):
        messages.error(request, "You don't have permission to upload documents for this plot.")
        return redirect('listings:home')

    if request.method == 'POST':
        form = VerificationDocumentForm(request.POST, request.FILES)
        if form.is_valid():
            doc = form.save(commit=False)
            doc.plot = plot
            doc.uploaded_by = request.user
            doc.save()
            messages.success(request, "Document uploaded successfully!")
            return redirect('listings:plot_detail', id=plot.id)
    else:
        form = VerificationDocumentForm()

    return render(request, 'listings/dashboard/upload_verification.html', {
        'form': form, 
        'plot': plot
    })


# ============ DASHBOARD VIEWS ============
@login_required
def staff_dashboard(request):
    """Main dashboard for landowners and agents"""
    context = {}
    
    # Check user type
    is_landowner = hasattr(request.user, 'landownerprofile')
    is_agent = hasattr(request.user, 'agent')
    
    if not (is_landowner or is_agent):
        messages.error(request, "You need to be a landowner or agent to access this dashboard.")
        return redirect('listings:home')
    
    # Get user's plots
    plots = Plot.objects.none()
    if is_agent:
        plots = Plot.objects.filter(agent=request.user.agent)
        logger.info(f"Agent {request.user.username} has {plots.count()} plots")
    elif is_landowner:
        plots = Plot.objects.filter(landowner=request.user.landownerprofile)
        logger.info(f"Landowner {request.user.username} has {plots.count()} plots")
    
    # Debug: Print all plots and their verification status
    for plot in plots:
        if hasattr(plot, 'verification') and plot.verification:
            logger.info(f"Plot {plot.id}: {plot.title} - Status: {plot.verification.current_stage}")
        else:
            logger.warning(f"Plot {plot.id}: {plot.title} - No verification status found")
    
    # Plot statistics using VerificationStatus
    total_plots = plots.count()
    
    # Count by verification stage
    verified_plots = 0
    in_review_plots = 0
    pending_plots = 0
    rejected_plots = 0
    other_plots = 0
    
    for plot in plots:
        if hasattr(plot, 'verification') and plot.verification:
            stage = plot.verification.current_stage
            if stage == 'approved':
                verified_plots += 1
            elif stage == 'admin_review':
                in_review_plots += 1
            elif stage == 'pending':
                pending_plots += 1
            elif stage == 'rejected':
                rejected_plots += 1
            else:
                other_plots += 1
                logger.info(f"Plot {plot.id} has other stage: {stage}")
        else:
            # Create verification status for plots that don't have it
            content_type = ContentType.objects.get_for_model(Plot)
            verification, created = VerificationStatus.objects.get_or_create(
                content_type=content_type,
                object_id=plot.id,
                defaults={
                    'current_stage': 'pending',
                    'document_uploaded_at': timezone.now()
                }
            )
            if created:
                logger.info(f"Created missing verification status for plot {plot.id}")
                pending_plots += 1
            else:
                # If it exists but wasn't in the queryset, count it
                stage = verification.current_stage
                if stage == 'approved':
                    verified_plots += 1
                elif stage == 'admin_review':
                    in_review_plots += 1
                elif stage == 'pending':
                    pending_plots += 1
                elif stage == 'rejected':
                    rejected_plots += 1
    
    # Calculate percentages
    if total_plots > 0:
        verified_percentage = (verified_plots / total_plots) * 100
        in_review_percentage = (in_review_plots / total_plots) * 100
        pending_percentage = (pending_plots / total_plots) * 100
        rejected_percentage = (rejected_plots / total_plots) * 100
    else:
        verified_percentage = in_review_percentage = pending_percentage = rejected_percentage = 0
    
    # Log the counts for debugging
    logger.info(f"Dashboard counts - Total: {total_plots}, Verified: {verified_plots}, "
                f"In Review: {in_review_plots}, Pending: {pending_plots}, Rejected: {rejected_plots}")
    
    # Recent activities
    recent_interests = UserInterest.objects.filter(plot__in=plots).order_by('-created_at')[:5]
    
    # Calculate buyer interest percentage
    buyer_interest_percentage = (recent_interests.count() / total_plots * 100) if total_plots > 0 else 0
    
    # Plot status breakdown
    plot_status_data = {
        'Verified': verified_plots,
        'In Review': in_review_plots,
        'Pending': pending_plots,
        'Rejected': rejected_plots,
    }
    
    # Get user's verification status
    verification_data = None
    if is_landowner:
        content_type = ContentType.objects.get_for_model(LandownerProfile)
        verification = VerificationStatus.objects.filter(
            content_type=content_type,
            object_id=request.user.landownerprofile.id
        ).first()
    elif is_agent:
        content_type = ContentType.objects.get_for_model(Agent)
        verification = VerificationStatus.objects.filter(
            content_type=content_type,
            object_id=request.user.agent.id
        ).first()
    
    if verification:
        verification_data = {
            'current_stage': verification.current_stage,
            'stage_display': verification.get_current_stage_display(),
            'document_uploaded_at': verification.document_uploaded_at,
            'admin_review_at': verification.admin_review_at,
            'approved_at': verification.approved_at,
            'search_reference': verification.search_reference,
            'progress': verification.progress_percentage,
            'estimated_completion': verification.estimated_completion
        }
    
    context.update({
        'is_landowner': is_landowner,
        'is_agent': is_agent,
        'total_plots': total_plots,
        'verified_plots': verified_plots,
        'in_review_plots': in_review_plots,
        'pending_plots': pending_plots,
        'rejected_plots': rejected_plots,
        'other_plots': other_plots,
        'verified_percentage': verified_percentage,
        'in_review_percentage': in_review_percentage,
        'pending_percentage': pending_percentage,
        'rejected_percentage': rejected_percentage,
        'buyer_interest_percentage': buyer_interest_percentage,
        'recent_interests': recent_interests,
        'plot_status_data': plot_status_data,
        'plots': plots.order_by('-created_at')[:5],
        'verification': verification_data
    })
    
    # Add profile info
    if is_landowner:
        context['profile'] = request.user.landownerprofile
        context['profile_type'] = 'Landowner'
    elif is_agent:
        context['profile'] = request.user.agent
        context['profile_type'] = 'Agent'
    
    return render(request, 'listings/dashboard/staff_dashboard.html', context)

@login_required
def my_plots(request):
    """View all plots with verification status"""
    is_agent = hasattr(request.user, 'agent')
    is_landowner = hasattr(request.user, 'landownerprofile')
    
    if not (is_agent or is_landowner):
        messages.error(request, "You need to be a landowner or agent to view plots.")
        return redirect('listings:home')
    
    if is_agent:
        plots = Plot.objects.filter(agent=request.user.agent)
    else:
        plots = Plot.objects.filter(landowner=request.user.landownerprofile)
    
    # Filtering
    status_filter = request.GET.get('status', 'all')
    if status_filter != 'all':
        plots = plots.filter(verification__current_stage=status_filter)
    
    # Search
    search_query = request.GET.get('search', '')
    if search_query:
        plots = plots.filter(
            Q(title__icontains=search_query) |
            Q(location__icontains=search_query)
        )
    
    # Pagination
    paginator = Paginator(plots.order_by('-created_at'), 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    # Status counts for filters
    status_counts = {
        'all': plots.count(),
        'approved': plots.filter(verification__current_stage='approved').count(),
        'admin_review': plots.filter(verification__current_stage='admin_review').count(),
        'pending': plots.filter(verification__current_stage='pending').count(),
        'rejected': plots.filter(verification__current_stage='rejected').count(),
    }
    
    context = {
        'page_obj': page_obj,
        'status_filter': status_filter,
        'search_query': search_query,
        'status_counts': status_counts,
        'total_plots': plots.count(),
        'is_agent': is_agent,
        'is_landowner': is_landowner,
    }
    
    return render(request, 'listings/dashboard/my_plots.html', context)


@login_required
def plot_verification_detail(request, plot_id):
    """Detailed view of plot verification status"""
    plot = get_object_or_404(Plot, id=plot_id)
    
    # Check permission
    is_agent = hasattr(request.user, 'agent') and plot.agent == request.user.agent
    is_landowner = hasattr(request.user, 'landownerprofile') and plot.landowner == request.user.landownerprofile
    
    if not (is_agent or is_landowner or request.user.is_staff):
        messages.error(request, "You don't have permission to view this plot.")
        return redirect('listings:home')
    
    # ✅ FIX: Get or create verification status
    verification, created = VerificationStatus.objects.get_or_create(
        content_type=ContentType.objects.get_for_model(Plot),
        object_id=plot.id,
        defaults={
            'current_stage': 'pending',
            'document_uploaded_at': timezone.now()
        }
    )
    
    if created:
        logger.info(f"Created missing verification status for plot {plot.id}")
    
    # Get required documents status
    has_title_deed = bool(plot.title_deed)
    has_official_search = bool(plot.official_search)
    has_landowner_id = bool(plot.landowner_id_doc)
    has_kra_pin = bool(plot.kra_pin)
    has_soil_report = bool(plot.soil_report)
    
    # Get verification documents
    verification_docs = plot.verification_docs.all()
    
    context = {
        'plot': plot,
        'verification': verification,  # ✅ Pass the verification object
        'has_title_deed': has_title_deed,
        'has_official_search': has_official_search,
        'has_landowner_id': has_landowner_id,
        'has_kra_pin': has_kra_pin,
        'has_soil_report': has_soil_report,
        'verification_docs': verification_docs,
        'documents_complete': all([has_title_deed, has_official_search, has_landowner_id, has_kra_pin]),
    }
    
    return render(request, 'listings/dashboard/plot_verification_detail.html', context)

@login_required
def buyer_interests(request):
    """Manage buyer interests for plots"""
    is_agent = hasattr(request.user, 'agent')
    is_landowner = hasattr(request.user, 'landownerprofile')
    
    if not (is_agent or is_landowner):
        messages.error(request, "Only agents and landowners can view buyer interests.")
        return redirect('listings:home')
    
    if is_agent:
        interests = UserInterest.objects.filter(plot__agent=request.user.agent)
    else:
        interests = UserInterest.objects.filter(plot__landowner=request.user.landownerprofile)
    
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
        'accepted': interests.filter(status='accepted').count(),
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
    is_agent = hasattr(request.user, 'agent') and interest.plot.agent == request.user.agent
    is_landowner = hasattr(request.user, 'landownerprofile') and interest.plot.landowner == request.user.landownerprofile
    
    if not (is_agent or is_landowner):
        messages.error(request, "You don't have permission to update this interest.")
        return redirect('listings:home')
    
    if request.method == 'POST':
        new_status = request.POST.get('status')
        notes = request.POST.get('notes', '')
        
        if new_status in dict(UserInterest.STATUS_CHOICES).keys():
            interest.status = new_status
            if notes:
                interest.notes = notes
            interest.save()
            messages.success(request, f"Interest status updated to {interest.get_status_display()}.")
        else:
            messages.error(request, "Invalid status.")
    
    return redirect('listings:buyer_interests')


@login_required
def profile_management(request):
    """Manage landowner/agent profile"""
    is_landowner = hasattr(request.user, 'landownerprofile')
    is_agent = hasattr(request.user, 'agent')
    
    if not (is_landowner or is_agent):
        messages.error(request, "You need to be a landowner or agent.")
        return redirect('listings:home')
    
    if request.method == 'POST':
        phone = request.POST.get('phone', '')
        
        if is_agent:
            agent = request.user.agent
            agent.phone = phone
            agent.save()
            messages.success(request, "Profile updated successfully.")
        elif is_landowner:
            # Landowner profile updates
            pass
    
    context = {
        'is_landowner': is_landowner,
        'is_agent': is_agent,
    }
    
    if is_landowner:
        context['profile'] = request.user.landownerprofile
    elif is_agent:
        context['profile'] = request.user.agent
    
    return render(request, 'listings/dashboard/profile_management.html', context)


@login_required
def dashboard_analytics(request):
    """Analytics dashboard for agents/landowners"""
    is_agent = hasattr(request.user, 'agent')
    is_landowner = hasattr(request.user, 'landownerprofile')
    
    if not (is_agent or is_landowner):
        messages.error(request, "Only agents and landowners can view analytics.")
        return redirect('listings:home')
    
    if is_agent:
        plots = Plot.objects.filter(agent=request.user.agent)
        total_interests = UserInterest.objects.filter(plot__agent=request.user.agent).count()
    else:
        plots = Plot.objects.filter(landowner=request.user.landownerprofile)
        total_interests = UserInterest.objects.filter(plot__landowner=request.user.landownerprofile).count()
    
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
    
    # Listing type distribution
    listing_type_stats = {
        'For Sale': plots.filter(listing_type='sale').count(),
        'For Lease': plots.filter(listing_type='lease').count(),
        'Both': plots.filter(listing_type='both').count(),
    }
    
    # Land type distribution
    land_type_stats = plots.values('land_type').annotate(
        count=Count('id')
    ).order_by('-count')
    
    # Location distribution
    location_stats = plots.values('location').annotate(
        count=Count('id')
    ).order_by('-count')[:10]
    
    context = {
        'monthly_stats': list(monthly_stats),
        'price_ranges': price_ranges,
        'listing_type_stats': listing_type_stats,
        'land_type_stats': list(land_type_stats),
        'location_stats': list(location_stats),
        'total_interests': total_interests,
        'total_plots': plots.count(),
        'avg_price': plots.aggregate(avg=Avg('price'))['avg'] or 0,
        'avg_area': plots.aggregate(avg=Avg('area'))['avg'] or 0,
    }
    
    return render(request, 'listings/dashboard/analytics.html', context)


# ============ VERIFICATION ADMIN ============
@login_required
def verification_dashboard(request):
    """Admin verification dashboard"""
    if not request.user.is_staff:
        return redirect('listings:home')

    pending = VerificationStatus.objects.filter(current_stage='pending')
    in_review = VerificationStatus.objects.filter(current_stage='admin_review')
    recent_verified = VerificationStatus.objects.filter(
        current_stage='approved', 
        approved_at__isnull=False
    ).order_by('-approved_at')[:10]
    
    stats = {
        'total_pending': pending.count(),
        'total_in_review': in_review.count(),
        'total_verified': VerificationStatus.objects.filter(current_stage='approved').count(),
        'total_rejected': VerificationStatus.objects.filter(current_stage='rejected').count(),
    }
    
    return render(request, 'listings/verification_dashboard.html', {
        'pending': pending,
        'in_review': in_review,
        'recent_verified': recent_verified,
        'stats': stats,
    })


@login_required
def review_plot(request, plot_id):
    """Admin plot review"""
    if not request.user.is_staff:
        return redirect('listings:home')

    plot = get_object_or_404(Plot, id=plot_id)
    
    # Get or create verification status using VerificationStatus model
    content_type = ContentType.objects.get_for_model(Plot)
    verification, created = VerificationStatus.objects.get_or_create(
        content_type=content_type,
        object_id=plot.id,
        defaults={'current_stage': 'document_uploaded', 'document_uploaded_at': timezone.now()}
    )

    if request.method == 'POST':
        vform = PlotVerificationStatusForm(request.POST, instance=verification)
        sform = TitleSearchResultForm(request.POST, request.FILES,
                                     instance=getattr(plot, 'search_result', None))
        if vform.is_valid() and sform.is_valid():
            if sform.instance:
                sform.save()
            vform.save()
            verification.refresh_from_db()
            if verification.current_stage == 'approved':
                log_audit(request, 'verify_plot', object_type='Plot', object_id=plot.id, extra={'plot_id': plot.id})
            elif verification.current_stage == 'rejected':
                log_audit(request, 'reject_plot', object_type='Plot', object_id=plot.id, extra={'plot_id': plot.id})
            messages.success(request, f"Plot verification status updated to {verification.get_current_stage_display()}.")
            return redirect('listings:verification_dashboard')
        else:
            messages.error(request, "Please correct the errors below.")
    else:
        vform = PlotVerificationStatusForm(instance=verification)
        sform = TitleSearchResultForm(instance=getattr(plot, 'search_result', None))

    docs = plot.verification_docs.all()
    return render(request, 'listings/review_plot.html', {
        'plot': plot,
        'docs': docs,
        'vform': vform,
        'sform': sform,
        'verification': verification,
    })


# ============ MESSAGING ============
@login_required
def contact_agent(request, plot_id):
    """Handle agent contact form submission"""
    plot = get_object_or_404(Plot, id=plot_id)
    
    if request.method == 'POST':
        message = request.POST.get('message', '')
        
        if not message:
            messages.error(request, "Please enter a message.")
            return redirect('listings:plot_detail', id=plot_id)
        
        # Determine recipient (agent or landowner)
        recipient = None
        if plot.agent:
            recipient = plot.agent.user
        elif plot.landowner:
            recipient = plot.landowner.user
        
        if not recipient:
            messages.error(request, "No contact information available for this listing.")
            return redirect('listings:plot_detail', id=plot_id)
        
        try:
            # Send email to recipient
            subject = f"New Inquiry about your plot: {plot.title}"
            body = f"""
            Hi {recipient.get_full_name() or recipient.username},
            
            You have a new inquiry about your plot listing:
            
            Plot: {plot.title} (ID: #{plot.id})
            Location: {plot.location}
            Price: KES {plot.price}
            
            Message from {request.user.get_full_name() or request.user.username} ({request.user.email}):
            {message}
            
            Please respond to this inquiry within 24 hours.
            
            Best regards,
            AgriPlot Connect Team
            """
            
            send_mail(
                subject=subject,
                message=body,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[recipient.email],
                fail_silently=False,
            )
            
            # Send confirmation to the buyer
            send_mail(
                subject=f"Message sent to agent regarding: {plot.title}",
                message=f"Your message has been sent to {recipient.get_full_name() or recipient.username}. They will contact you soon.",
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[request.user.email],
                fail_silently=False,
            )
            
            # Log the contact request
            ContactRequest.objects.create(
                user=request.user,
                plot=plot,
                agent=plot.agent,
                request_type='message',
                message=message
            )
            
            messages.success(request, "Message sent successfully! The contact will respond soon.")
            
        except Exception as e:
            logger.error(f"Failed to send message: {str(e)}")
            messages.error(request, "Failed to send message. Please try again later.")
        
        return redirect('listings:plot_detail', id=plot_id)
    
    messages.error(request, "Invalid request method.")
    return redirect('listings:plot_detail', id=plot_id)


@login_required
def request_contact_details(request, plot_id):
    """API endpoint to request contact details"""
    if request.method != 'POST':
        return JsonResponse({'error': 'Invalid request method'}, status=400)
    
    plot = get_object_or_404(Plot, id=plot_id)
    
    # Determine recipient
    recipient = None
    contact_type = None
    if plot.agent:
        recipient = plot.agent
        contact_type = 'agent'
    elif plot.landowner:
        recipient = plot.landowner
        contact_type = 'landowner'
    else:
        return JsonResponse({'error': 'No contact available for this plot'}, status=404)
    
    try:
        # Log the request
        ContactRequest.objects.create(
            user=request.user,
            plot=plot,
            agent=plot.agent,  # Will be None if landowner-only
            request_type='phone_request'
        )
        
        # Notify via email
        subject = f"Contact Request for your plot: {plot.title}"
        message = f"""
        User {request.user.get_full_name() or request.user.username} ({request.user.email}) 
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
            recipient_list=[recipient.user.email],
            fail_silently=False,
        )
        
        return JsonResponse({
            'success': True,
            'message': 'Contact request sent. The contact person will respond shortly.'
        })
        
    except Exception as e:
        logger.error(f"Failed to send contact request: {str(e)}")
        return JsonResponse({
            'success': False,
            'error': 'Failed to send request. Please try again.'
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
            agent=plot.agent,
            request_type='phone_view'
        )
        return JsonResponse({'success': True})
        
    except Exception as e:
        logger.error(f"Failed to log phone view: {str(e)}")
        return JsonResponse({
            'success': False,
            'error': 'Failed to log phone view'
        }, status=500)


# ============ LANDOWNER SUCCESS ============
@login_required
def landowner_success(request):
    """Success page after landowner registration wizard"""
    return render(request, 'listings/landowner_success.html')


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
    
    # Toggle reaction
    reaction, created = PlotReaction.objects.get_or_create(
        user=request.user,
        plot=plot,
        reaction_type=reaction_type
    )
    
    if not created:
        reaction.delete()
        user_has_reaction = False
    else:
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


# ============ VERIFICATION PROGRESS ============
@login_required
def verification_progress(request):
    """Show verification progress for landowners/agents"""
    
    context = {
        'landowner_verification': None,
        'agent_verification': None,
        'plot_verifications': []
    }
    
    # Get landowner verification if exists
    if hasattr(request.user, 'landownerprofile'):
        landowner = request.user.landownerprofile
        content_type = ContentType.objects.get_for_model(LandownerProfile)
        verification = VerificationStatus.objects.filter(
            content_type=content_type,
            object_id=landowner.id
        ).first()
        
        if verification:
            context['landowner_verification'] = {
                'current_stage': verification.get_current_stage_display(),
                'stage_progress': verification.progress_percentage,
                'details': verification.stage_details,
                'search_reference': verification.search_reference,
                'submitted_at': verification.document_uploaded_at,
                'estimated_completion': verification.estimated_completion
            }
    
    # Similar for agent
    if hasattr(request.user, 'agent'):
        agent = request.user.agent
        content_type = ContentType.objects.get_for_model(Agent)
        verification = VerificationStatus.objects.filter(
            content_type=content_type,
            object_id=agent.id
        ).first()
        
        if verification:
            context['agent_verification'] = {
                'current_stage': verification.get_current_stage_display(),
                'stage_progress': verification.progress_percentage,
                'details': verification.stage_details,
                'search_reference': verification.search_reference,
                'submitted_at': verification.document_uploaded_at,
                'estimated_completion': verification.estimated_completion
            }
    
    # Get plot verifications
    if hasattr(request.user, 'agent') or hasattr(request.user, 'landownerprofile'):
        plots = Plot.objects.filter(
            Q(agent=request.user.agent) | Q(landowner=request.user.landownerprofile)
        )
        
        for plot in plots:
            if hasattr(plot, 'verification'):
                context['plot_verifications'].append({
                    'plot': plot,
                    'stage': plot.verification.get_current_stage_display(),
                    'progress': plot.verification.progress_percentage,
                    'submitted_at': plot.verification.document_uploaded_at
                })
    
    return render(request, 'listings/verification_progress.html', context)


# ============ ADMIN VERIFICATION APPROVAL ============
@staff_member_required
def admin_approve_verification(request, verification_id):
    """
    Admin final approval after API verification
    """
    verification = get_object_or_404(VerificationStatus, id=verification_id)
    
    if request.method == 'POST':
        action = request.POST.get('action')
        
        if action == 'approve':
            # Update verification status
            verification.update_stage('approved', {
                'approved_by': request.user.username,
                'approved_at': timezone.now().isoformat(),
                'admin_notes': request.POST.get('notes', '')
            })
            
            # Update the actual profile
            obj = verification.content_object
            if hasattr(obj, 'verified'):
                obj.verified = True
                obj.save()
            
            messages.success(request, f"Verification approved for {obj}")
            
        elif action == 'reject':
            verification.update_stage('rejected', {
                'rejected_by': request.user.username,
                'reason': request.POST.get('rejection_reason', ''),
                'admin_notes': request.POST.get('notes', '')
            })
            
            messages.warning(request, f"Verification rejected for {verification.content_object}")
        
        return redirect('admin:listings_verificationstatus_changelist')
    
    # Show approval page with API results
    return render(request, 'admin/approve_verification.html', {
        'verification': verification,
        'api_responses': verification.api_responses,
        'stage_details': verification.stage_details
    })