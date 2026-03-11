from datetime import date, timedelta
import logging

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.contrib.auth.views import LoginView
from django.contrib.admin.views.decorators import staff_member_required
from django.core.files.storage import FileSystemStorage, default_storage
from django.core.mail import send_mail
from django.core.paginator import Paginator
from django.db.models import Q, Count, Avg
from django.db.models.functions import TruncMonth
from django.http import Http404, JsonResponse, HttpResponse
from django.shortcuts import render, redirect, get_object_or_404, resolve_url
from django.template.loader import render_to_string
from django.core.exceptions import DisallowedHost, ValidationError
from decimal import Decimal
from django.contrib.contenttypes.models import ContentType
from django.utils import timezone
from .models import SitePage
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
import json
import os
import uuid
from .kenya_data import KENYA_COUNTIES, KENYA_SUB_COUNTIES
from .utils import log_audit
from django.contrib.contenttypes.models import ContentType
from registry_mock.services import verify_with_registry
from notifications.notification_service import NotificationService

logger = logging.getLogger(__name__)

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
from accounts.views_dashboard import (  # noqa: E402
    buyer_interests,
    dashboard_analytics,
    dashboard_router,
    my_plots,
    plot_verification_detail,
    staff_dashboard,
    update_interest_status,
)
from accounts.views_profile import (  # noqa: E402
    account_settings,
    profile_edit,
    profile_management,
)
from accounts.views_registration import (  # noqa: E402
    _safe_next_url,
    register_agent,
    register_buyer,
    register_choice,
    register_landowner,
    register_landowner_simple,
)
from accounts.views_wizard import FORMS, LandownerWizard  # noqa: E402
from notifications.views import notifications_inbox  # noqa: E402


@login_required
def request_extension_officer(request):
    from verification.views import request_extension_officer as verification_view

    return verification_view(request)


@login_required
def request_land_surveyor(request):
    from verification.views import request_land_surveyor as verification_view

    return verification_view(request)



# ============ PUBLIC PAGES ============
def home(request):
    """Homepage with plot listings"""
    # Get verified plots - removed verification from select_related
    verified_plots = Plot.objects.filter(
        verification__current_stage="approved"
    ).select_related('agent__user')
    
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

    # Wizard resume banner flag
    show_wizard_resume = any(
        key.startswith("landownerwizard") or key.startswith("wizard_")
        for key in request.session.keys()
    )
    
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
        'show_wizard_resume': show_wizard_resume,
        'active_soil_filters': {
            'ph_min': ph_min, 'ph_max': ph_max, 'om_min': om_min,
            'n_min': n_min, 'p_min': p_min, 'k_min': k_min, 
            'ec_max': ec_max, 'texture': texture
        },
    })
# In your view, add these context variables
def get_context_data(self, **kwargs):
    context = super().get_context_data(**kwargs)
    
    # Count active filters
    active_filters = []
    request = self.request
    
    # Check each filter and build active filters list
    if request.GET.get('soil_type'):
        active_filters.append({
            'label': 'Soil',
            'value': request.GET.get('soil_type'),
            'remove_url': self.build_remove_url('soil_type')
        })
    
    if request.GET.get('crop_preset'):
        active_filters.append({
            'label': 'Crop',
            'value': request.GET.get('crop_preset'),
            'remove_url': self.build_remove_url('crop_preset')
        })
    
    if request.GET.get('listing_type'):
        listing_type = request.GET.get('listing_type')
        active_filters.append({
            'label': 'Type',
            'value': 'For Sale' if listing_type == 'sale' else 'For Lease',
            'remove_url': self.build_remove_url('listing_type')
        })
    
    if request.GET.get('min_price') or request.GET.get('max_price'):
        price_str = []
        if request.GET.get('min_price'):
            price_str.append(f"Min: {request.GET.get('min_price')}")
        if request.GET.get('max_price'):
            price_str.append(f"Max: {request.GET.get('max_price')}")
        active_filters.append({
            'label': 'Price',
            'value': ' '.join(price_str),
            'remove_url': self.build_remove_url(['min_price', 'max_price'])
        })
    
    context['active_filters'] = active_filters
    context['has_active_filters'] = len(active_filters) > 0
    context['active_filters_count'] = len(active_filters)
    context['plots_count'] = self.get_queryset().count()
    
    return context

def build_remove_url(self, params_to_remove):
    """Build URL with specified parameters removed"""
    if not isinstance(params_to_remove, list):
        params_to_remove = [params_to_remove]
    
    new_params = self.request.GET.copy()
    for param in params_to_remove:
        if param in new_params:
            del new_params[param]
    
    return f"?{new_params.urlencode()}"

def ajax_search(request):
    """Return rendered market grid fragment for AJAX search requests."""
    verified_plots = Plot.objects.filter(
        verification__current_stage="approved"
    ).select_related('agent__user')
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
        ).prefetch_related('verification_docs'),
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

    # Non-owners can only view approved listings
    if not is_owner and not (request.user.is_staff or request.user.is_superuser):
        if not verification or verification.current_stage != 'approved':
            raise Http404
    
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
    
    # Bbox for OpenStreetMap embed (min_lon, min_lat, max_lon, max_lat)
    map_bbox = ''
    if plot.latitude is not None and plot.longitude is not None:
        delta = 0.02
        map_bbox = f"{float(plot.longitude) - delta},{float(plot.latitude) - delta},{float(plot.longitude) + delta},{float(plot.latitude) + delta}"
    
    # Restrict document access - only owner or staff can view/download
    can_view_documents = is_owner or (
        request.user.is_authenticated and (request.user.is_staff or request.user.is_superuser)
    )
    
    context = {
        'plot': plot,
        'verification': verification,
        'is_owner': is_owner,
        'can_view_documents': can_view_documents,
        'similar_plots': similar_plots,
        'map_bbox': map_bbox,
        'today': date.today().strftime('%Y-%m-%d'),
    }
    
    return render(request, 'listings/details.html', context)
# ============ PLOT MANAGEMENT ============

import json
import logging
import traceback
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from django.utils import timezone
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import IntegrityError, DatabaseError
from .forms import PlotForm
from .models import Plot, VerificationStatus, Agent, LandownerProfile
from registry_mock.models import RegistryMismatchAttempt
from .kenya_data import KENYA_COUNTIES, KENYA_SUB_COUNTIES
from .utils import log_audit

# Get loggers
logger = logging.getLogger(__name__)
validation_logger = logging.getLogger('listings.validation')
error_logger = logging.getLogger('listings.errors')
audit_logger = logging.getLogger('listings.audit')

@login_required
def add_plot(request):
    """Create new plot with ALL required documents upfront"""
    # Start timing for performance monitoring
    import time
    start_time = time.time()
    
    # Log entry with user context
    logger.info(f"=== PLOT CREATION STARTED ===")
    logger.info(f"User: {request.user.username} (ID: {request.user.id})")
    logger.info(f"IP Address: {request.META.get('REMOTE_ADDR')}")
    logger.info(f"User Agent: {request.META.get('HTTP_USER_AGENT')}")
    
    # Check if user is agent or landowner
    is_agent = hasattr(request.user, 'agent')
    is_landowner = hasattr(request.user, 'landownerprofile')
    is_superuser = request.user.is_superuser
    
    logger.info(f"User type - Agent: {is_agent}, Landowner: {is_landowner}")
    
    if not (is_agent or is_landowner or is_superuser):
        logger.warning(f"User {request.user.username} attempted to add plot without proper profile")
        messages.error(request, "You must be a verified agent or landowner to list land.")
        return redirect("listings:register_choice")
    
    # Check verification status
    if not is_superuser:
        try:
            if is_agent and not request.user.agent.verified:
                logger.warning(f"Unverified agent {request.user.username} attempted to add plot")
                messages.error(request, "Your agent account needs to be verified before you can list plots.")
                return redirect("listings:register_agent")
            
            if is_landowner and not request.user.landownerprofile.verified:
                logger.warning(f"Unverified landowner {request.user.username} attempted to add plot")
                messages.error(request, "Your landowner account needs to be verified before you can list plots.")
                return redirect("listings:register_landowner")
        except (Agent.DoesNotExist, LandownerProfile.DoesNotExist) as e:
            logger.error(f"Profile access error for user {request.user.username}: {str(e)}")
            messages.error(request, "Error accessing your profile. Please contact support.")
            return redirect("listings:home")

    # Q7/Q8: Contact verification and 2FA enforcement (feature-flagged)
    profile = getattr(request.user, 'profile', None)
    if settings.REQUIRE_CONTACT_VERIFICATION and not is_superuser:
        phone_verified = bool(getattr(profile, 'phone_verified', False))
        email_verified = bool(getattr(profile, 'email_verified', False))
        contact_verification = getattr(request.user, 'contact_verification', None)
        if contact_verification:
            phone_verified = phone_verified or contact_verification.phone_verified
            email_verified = email_verified or contact_verification.email_verified
        otp_provider = getattr(settings, "OTP_PROVIDER", "email")
        if otp_provider == "email" and not email_verified:
            messages.error(request, "Verify your email before listing a plot.")
            return redirect("listings:profile_management")
        if otp_provider in ("sms", "both") and not (phone_verified and email_verified):
            messages.error(request, "Verify your phone and email before listing a plot.")
            return redirect("listings:profile_management")

    if settings.REQUIRE_2FA_FOR_LISTING and not is_superuser:
        if not profile or not getattr(profile, 'has_2fa_enabled', False):
            messages.error(request, "Enable 2FA before listing a plot.")
            return redirect("listings:profile_management")

    if settings.REQUIRE_DOCUMENT_VERIFICATION and not is_superuser:
        from .models import DocumentVerification
        required_docs = {'national_id', 'kra_pin', 'title_deed'}
        approved_docs = set(
            DocumentVerification.objects.filter(
                user=request.user,
                approved=True
            ).values_list('document_type', flat=True)
        )
        if not required_docs.issubset(approved_docs):
            messages.error(request, "Your identity documents must be verified before listing.")
            return redirect("listings:verification_progress")

    # Q8: rate limit plot creation (per-hour)
    if request.method == "POST" and settings.PLOT_CREATE_RATE_LIMIT and not is_superuser:
        from django.core.cache import cache
        from django.utils import timezone as _tz
        bucket = _tz.now().strftime("%Y%m%d%H")
        key = f"plot_create:{request.user.id}:{bucket}"
        current = cache.get(key, 0)
        if current >= settings.PLOT_CREATE_RATE_LIMIT:
            messages.error(request, "Rate limit exceeded. Try again later.")
            return redirect("listings:add_plot")
        cache.set(key, current + 1, timeout=60 * 60)

    # Initialize selected values for county/subcounty
    selected_county = None
    selected_subcounty = None
    sub_counties = []
    mismatch_count = None

    if request.method == "POST":
        logger.info(f"Processing POST request for plot creation")
        logger.debug(f"POST data: { {k: v for k, v in request.POST.items() if 'csrf' not in k} }")
        logger.debug(f"FILES uploaded: {list(request.FILES.keys())}")
        
        # Validate county and subcounty early
        selected_county = request.POST.get('county')
        selected_subcounty = request.POST.get('subcounty')
        parcel_for_mismatch = (request.POST.get('parcel_number') or '').strip()
        if request.user.is_staff and parcel_for_mismatch:
            mismatch_count = RegistryMismatchAttempt.objects.filter(
                parcel_number__iexact=parcel_for_mismatch
            ).count()
        
        logger.info(f"Selected County: {selected_county}")
        logger.info(f"Selected Sub-county: {selected_subcounty}")
        
        # Validate county exists in our data
        if selected_county and selected_county not in KENYA_COUNTIES:
            error_msg = f"Invalid county selected: {selected_county}"
            logger.error(error_msg)
            messages.error(request, error_msg)
            # Get subcounties for this county if it exists in our data
            if selected_county in KENYA_SUB_COUNTIES:
                sub_counties = KENYA_SUB_COUNTIES[selected_county]
        
        # Determine the owner based on user type
        owner = None
        try:
            if is_agent:
                owner = request.user.agent
                logger.info(f"Owner set as Agent: {owner.id}")
            elif is_landowner:
                owner = request.user.landownerprofile
                logger.info(f"Owner set as Landowner: {owner.id}")
            elif is_superuser:
                owner_type = request.POST.get("owner_type")
                owner_id = request.POST.get("owner_id")
                if owner_type == "agent":
                    owner = Agent.objects.get(id=owner_id)
                elif owner_type == "landowner":
                    owner = LandownerProfile.objects.get(id=owner_id)
                else:
                    owner = None
        except Exception as e:
            logger.error(f"Error getting owner profile: {str(e)}", exc_info=True)
            messages.error(request, "Error accessing your profile. Please try again.")
            plot_form = PlotForm()
            if is_superuser:
                messages.error(request, "Select a valid owner (agent or landowner).")
        else:
            # Create form with POST data, FILES, and the owner
            try:
                if is_superuser and owner is None:
                    messages.error(request, "Select a valid owner (agent or landowner) to create this plot.")
                    plot_form = PlotForm(request.POST, request.FILES, user=request.user)
                else:
                    plot_form = PlotForm(request.POST, request.FILES, owner=owner, user=request.user)
                logger.info("PlotForm initialized successfully")
            except Exception as e:
                logger.error(f"Error initializing PlotForm: {str(e)}", exc_info=True)
                messages.error(request, "Error processing form. Please try again.")
                plot_form = PlotForm()
        
        if plot_form.is_valid():
            logger.info("Form validation successful")
            
            # Log cleaned data (excluding sensitive info)
            safe_cleaned = {k: v for k, v in plot_form.cleaned_data.items() 
                           if k not in ['csrfmiddlewaretoken', 'title_deed', 'official_search', 
                                       'survey_map', 'spousal_consent_doc', 'rates_clearance', 'rent_clearance',
                                       'landowner_id_doc', 'kra_pin', 'soil_report']}
            logger.debug(f"Cleaned data: {safe_cleaned}")
            
            try:
                # Save the plot - owner is handled in form.save()
                plot = plot_form.save()
                
                # Calculate processing time
                processing_time = time.time() - start_time
                
                logger.info(f"✅ Plot saved successfully! ID: {plot.id}")
                logger.info(f"Plot Title: {plot.title}")
                logger.info(f"County: {plot.county}, Subcounty: {plot.subcounty}")
                logger.info(f"Location: {plot.location}")
                logger.info(f"Area: {plot.area} acres")
                logger.info(f"Listing Type: {plot.listing_type}")
                logger.info(f"Processing time: {processing_time:.2f} seconds")
                
                # Log document uploads
                uploaded_docs = []
                if plot.title_deed:
                    uploaded_docs.append('title_deed')
                if plot.survey_map:
                    uploaded_docs.append('survey_map')
                if plot.spousal_consent_doc:
                    uploaded_docs.append('spousal_consent_doc')
                if plot.official_search:
                    uploaded_docs.append('official_search')
                if plot.rates_clearance:
                    uploaded_docs.append('rates_clearance')
                if plot.rent_clearance:
                    uploaded_docs.append('rent_clearance')
                if plot.landowner_id_doc:
                    uploaded_docs.append('landowner_id_doc')
                if plot.kra_pin:
                    uploaded_docs.append('kra_pin')
                if plot.soil_report:
                    uploaded_docs.append('soil_report')
                
                logger.info(f"Uploaded documents: {uploaded_docs}")
                
                # Audit log
                audit_logger.info(f"User {request.user.username} created plot ID {plot.id}")
                log_audit(request, 'create_plot', object_type='Plot', object_id=plot.id)

                # Create verification status using VerificationStatus model
                try:
                    content_type = ContentType.objects.get_for_model(Plot)
                    verification, created = VerificationStatus.objects.get_or_create(
                        content_type=content_type,
                        object_id=plot.id,
                        defaults={
                            'current_stage': 'document_uploaded',
                            'document_uploaded_at': timezone.now(),
                            'stage_details': {
                                'created_by': request.user.username,
                                'created_by_id': request.user.id,
                                'created_at': timezone.now().isoformat(),
                                'plot_title': plot.title,
                                'plot_id': plot.id,
                                'county': plot.county,
                                'subcounty': plot.subcounty,
                                'documents_uploaded': uploaded_docs,
                                'registry_check': getattr(plot_form, "registry_result", None) or {}
                            }
                        }
                    )
                    
                    if created:
                        logger.info(f"✅ Verification status created for plot {plot.id}")
                        logger.info(f"Verification ID: {verification.id}")
                        logger.info(f"Current stage: {verification.current_stage}")
                        # Q5: Create verification tasks (document review, extension, surveyor) at submission
                        try:
                            from verification.verification_service import VerificationService
                            tasks_created = VerificationService.create_verification_tasks(
                                plot, initiated_by=request.user
                            )
                            logger.info(f"Created verification tasks for plot {plot.id}: {tasks_created}")
                            from notifications.notification_service import NotificationService
                            NotificationService.notify_plot_submitted(plot)
                            # Trigger mock Ardhisasa verification for title search
                            try:
                                VerificationService.initiate_ardhisasa_verification(plot.id)
                            except Exception as api_err:
                                logger.warning(f"Ardhisasa verification failed for plot {plot.id}: {api_err}")
                        except Exception as task_err:
                            logger.warning(f"Verification task creation failed for plot {plot.id}: {task_err}")
                    else:
                        logger.info(f"ℹ️ Verification status already exists for plot {plot.id}")
                        logger.info(f"Existing verification stage: {verification.current_stage}")

                    # Q6: Generate a pricing suggestion for sale listings
                    if plot.listing_type in ['sale', 'both']:
                        try:
                            from .utils import suggest_price
                            suggest_price(plot)
                        except Exception as price_err:
                            logger.warning(f"Pricing suggestion failed for plot {plot.id}: {price_err}")

                except Exception as e:
                    logger.error(f"Error creating verification status: {str(e)}", exc_info=True)
                    # Don't fail the whole request, just log the error
                    messages.warning(request, "Plot saved but verification status creation failed. Please contact support.")
                
                messages.success(request, 
                    "✅ Plot submitted successfully! Your listing is now under verification review."
                )
                
                logger.info(f"=== PLOT CREATION COMPLETED SUCCESSFULLY (ID: {plot.id}) ===\n")
                return redirect("listings:plot_detail", id=plot.id)

            except ValidationError as e:
                error_msg = f"Validation error while saving plot: {str(e)}"
                logger.error(error_msg, exc_info=True)
                messages.error(request, "Please correct the errors and try again.")
                
            except IntegrityError as e:
                error_msg = f"Database integrity error: {str(e)}"
                logger.error(error_msg, exc_info=True)
                messages.error(request, "A database error occurred. Please try again.")
                
            except DatabaseError as e:
                error_msg = f"Database error: {str(e)}"
                logger.error(error_msg, exc_info=True)
                messages.error(request, "A database error occurred. Please try again.")
                
            except Exception as e:
                error_msg = f"Unexpected error creating plot: {str(e)}"
                logger.error(error_msg, exc_info=True)
                logger.error(f"Traceback: {traceback.format_exc()}")
                
                # Log additional context for debugging
                logger.error(f"User: {request.user.username}")
                logger.error(f"Request method: {request.method}")
                logger.error(f"POST keys: {list(request.POST.keys())}")
                logger.error(f"FILES keys: {list(request.FILES.keys())}")
                
                messages.error(request, f"❌ Error creating plot: {str(e)}")
                
                # If plot was created but verification failed, try to clean up
                if 'plot' in locals() and plot.id:
                    try:
                        plot.delete()
                        logger.info(f"Cleaned up plot {plot.id} due to error")
                    except Exception as cleanup_error:
                        logger.error(f"Error cleaning up plot {plot.id}: {cleanup_error}")
        
        else:
            # Form validation failed
            error_count = len(plot_form.errors)
            logger.warning(f"Form validation failed with {error_count} error(s)")
            
            # Log all form errors in detail
            error_messages = []
            for field, errors in plot_form.errors.items():
                field_value = request.POST.get(field, 'Not provided')
                for error in errors:
                    error_msg = f"{field}: {error}"
                    error_messages.append(error_msg)
                    
                    # Log each validation error with context
                    validation_logger.error(f"Validation error - {error_msg}")
                    validation_logger.error(f"Field value: {field_value}")
                    
                    # Special logging for county/subcounty errors
                    if field in ['county', 'subcounty']:
                        logger.error(f"Location validation error - {field}: {error}")
                        logger.error(f"County selected: {selected_county}")
                        logger.error(f"Subcounty selected: {selected_subcounty}")
                    
                    # Display error to user
                    messages.error(request, error_msg)
            
            # Log all validation errors together
            logger.error(f"Form validation errors summary: {error_messages}")
            logger.error(f"POST data summary: County={selected_county}, Subcounty={selected_subcounty}")
            
            # If county is selected, get its subcounties for the dropdown
            if selected_county and selected_county in KENYA_SUB_COUNTIES:
                sub_counties = KENYA_SUB_COUNTIES[selected_county]
                logger.info(f"Loaded {len(sub_counties)} subcounties for {selected_county}")
            else:
                logger.warning(f"Selected county '{selected_county}' not found in subcounties data")
    else:
        # GET request - initialize empty form
        logger.info("Processing GET request for plot creation form")
        
        # Pre-fill form with initial data based on user type
        initial_data = {
            'crop_suitability': 'Maize, Beans, Vegetables'
        }
        
        # Add user-specific initial data if available
        try:
            if is_landowner and request.user.landownerprofile:
                # Could add landowner-specific defaults here
                logger.info("Landowner-specific initial data added")
        except Exception as e:
            logger.error(f"Error adding user-specific initial data: {str(e)}")
        
        plot_form = PlotForm(initial=initial_data)
        logger.info("Empty form initialized for GET request")

    # Prepare subcounties data for JavaScript
    try:
        sub_counties_json = json.dumps(KENYA_SUB_COUNTIES)
        logger.info(f"Prepared subcounties data for {len(KENYA_SUB_COUNTIES)} counties")
    except Exception as e:
        logger.error(f"Error serializing subcounties data: {str(e)}")
        sub_counties_json = '{}'

    # Calculate total processing time
    total_time = time.time() - start_time
    logger.info(f"Total request processing time: {total_time:.2f} seconds")
    logger.info("=== PLOT CREATION ENDED ===\n")

    agents = Agent.objects.select_related("user").all() if is_superuser else []
    landowners = LandownerProfile.objects.select_related("user").all() if is_superuser else []
    return render(request, "listings/dashboard/add_plot.html", {
        "form": plot_form,
        "is_agent": is_agent,
        "is_landowner": is_landowner,
        "profile_type": "Administrator" if is_superuser else ("Agent" if is_agent else "Landowner"),
        "counties": KENYA_COUNTIES,
        "sub_counties_json": sub_counties_json,
        "selected_county": selected_county,
        "selected_subcounty": selected_subcounty,
        "sub_counties": sub_counties,
        "is_superuser": is_superuser,
        "agents": agents,
        "landowners": landowners,
        "mismatch_count": mismatch_count,
    })

from django.http import JsonResponse

def get_subcounties(request):
    county = request.GET.get('county')
    if county and county in KENYA_SUB_COUNTIES:
        return JsonResponse({
            'subcounties': KENYA_SUB_COUNTIES[county]
        })
    return JsonResponse({'subcounties': []})

@login_required
def registry_lookup(request):
    parcel_number = (request.GET.get('parcel_number') or '').strip()
    if not parcel_number:
        return JsonResponse({'verified': False, 'message': 'Parcel number is required.'}, status=400)
    result = verify_with_registry(parcel_number)
    if not result.get('verified'):
        return JsonResponse({'verified': False, 'message': result.get('message') or 'Registry lookup failed.'})
    record = result.get('record')
    data = {
        'verified': True,
        'message': result.get('message'),
        'record': {
            'parcel_number': record.parcel_number,
            'registered_owner_name': record.registered_owner_name,
            'owner_id_number': record.owner_id_number,
            'owner_kra_pin': record.owner_kra_pin,
            'county': record.county,
            'subcounty': record.subcounty,
            'registration_section': record.registration_section,
            'search_reference_number': record.search_reference_number,
            'search_certificate_date': record.search_certificate_date.isoformat() if record.search_certificate_date else None,
            'acreage_ha': float(record.acreage_ha) if record.acreage_ha is not None else None,
            'land_type': record.land_type,
            'is_charged': bool(record.is_charged),
            'has_caution': bool(record.has_caution),
        },
        'has_encumbrances': bool(record.is_charged or record.has_caution),
    }
    return JsonResponse(data)

import json
import logging
import traceback
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, DatabaseError
from django.utils import timezone
from django.contrib.contenttypes.models import ContentType
from .forms import PlotForm
from .models import Plot, Agent, LandownerProfile, VerificationTask, VerificationStatus, VerificationLog
from .kenya_data import KENYA_COUNTIES, KENYA_SUB_COUNTIES
from .utils import log_audit
from verification.verification_service import VerificationService

# Get loggers
logger = logging.getLogger(__name__)
validation_logger = logging.getLogger('listings.validation')
error_logger = logging.getLogger('listings.errors')
audit_logger = logging.getLogger('listings.audit')

@login_required
def edit_plot(request, id):
    """Edit existing plot with comprehensive logging and validation"""
    # Start timing for performance monitoring
    import time
    start_time = time.time()
    
    # Log entry with user context
    logger.info(f"=== PLOT EDIT STARTED ===")
    logger.info(f"User: {request.user.username} (ID: {request.user.id})")
    logger.info(f"Plot ID: {id}")
    logger.info(f"IP Address: {request.META.get('REMOTE_ADDR')}")
    logger.info(f"User Agent: {request.META.get('HTTP_USER_AGENT')}")
    
    # Get the plot
    try:
        plot = Plot.objects.get(id=id)
        logger.info(f"Plot found: '{plot.title}' (Current county: {plot.county}, subcounty: {plot.subcounty})")
    except Plot.DoesNotExist:
        logger.error(f"Plot with ID {id} not found")
        messages.error(request, "Plot not found.")
        return redirect('listings:home')
    
    # Check permission
    is_agent = hasattr(request.user, 'agent') and plot.agent == request.user.agent
    is_landowner = hasattr(request.user, 'landownerprofile') and plot.landowner == request.user.landownerprofile
    
    logger.info(f"User type - Agent: {is_agent}, Landowner: {is_landowner}")
    
    if not (is_agent or is_landowner):
        logger.warning(f"User {request.user.username} attempted to edit plot {id} without permission")
        messages.error(request, "You don't have permission to edit this plot.")
        return redirect('listings:plot_detail', id=id)
    
    # Check if verification tasks exist, create if missing (for backwards compatibility)
    try:
        existing_tasks = VerificationTask.objects.filter(plot=plot).count()
        if existing_tasks == 0:
            logger.info(f"No verification tasks found for plot {plot.id}, creating them...")
            tasks_created = VerificationService.create_verification_tasks(
                plot,
                initiated_by=request.user
            )
            logger.info(f"Created missing verification tasks for plot {plot.id}: {tasks_created}")
    except Exception as e:
        logger.error(f"Error checking/creating tasks for edit: {str(e)}", exc_info=True)
        # Don't block the edit, just log the error
    
    # Initialize subcounties for the plot's county
    selected_county = plot.county
    selected_subcounty = plot.subcounty
    sub_counties = []
    
    if selected_county and selected_county in KENYA_SUB_COUNTIES:
        sub_counties = KENYA_SUB_COUNTIES[selected_county]
        logger.debug(f"Loaded {len(sub_counties)} subcounties for county '{selected_county}'")
    
    if request.method == 'POST':
        logger.info(f"Processing POST request for plot edit (ID: {id})")
        logger.debug(f"POST data: { {k: v for k, v in request.POST.items() if 'csrf' not in k} }")
        logger.debug(f"FILES uploaded: {list(request.FILES.keys())}")
        
        # Get county and subcounty from POST data for logging
        selected_county = request.POST.get('county')
        selected_subcounty = request.POST.get('subcounty')
        logger.info(f"Selected County: {selected_county}")
        logger.info(f"Selected Sub-county: {selected_subcounty}")
        
        # Validate county exists in our data
        if selected_county and selected_county not in KENYA_COUNTIES:
            error_msg = f"Invalid county selected: {selected_county}"
            logger.error(error_msg)
            messages.error(request, error_msg)
        
        # Update subcounties for dropdown if county changed
        if selected_county and selected_county in KENYA_SUB_COUNTIES:
            sub_counties = KENYA_SUB_COUNTIES[selected_county]
        
        # Create form with POST data and instance
        try:
            form = PlotForm(request.POST, request.FILES, instance=plot)
            logger.info("PlotForm initialized successfully for edit")
        except Exception as e:
            logger.error(f"Error initializing PlotForm: {str(e)}", exc_info=True)
            messages.error(request, "Error processing form. Please try again.")
            form = PlotForm(instance=plot)
        
        if form.is_valid():
            logger.info("Form validation successful")
            
            # Log cleaned data (excluding sensitive info)
            safe_cleaned = {k: v for k, v in form.cleaned_data.items() 
                           if k not in ['csrfmiddlewaretoken', 'title_deed', 'official_search', 
                                       'survey_map', 'spousal_consent_doc', 'rates_clearance', 'rent_clearance',
                                       'landowner_id_doc', 'kra_pin', 'soil_report']}
            logger.debug(f"Cleaned data: {safe_cleaned}")
            
            try:
                # Check if critical fields changed that might affect verification
                original_plot = Plot.objects.get(id=id)
                critical_changes = []
                
                if original_plot.title != form.cleaned_data.get('title'):
                    critical_changes.append('title')
                if original_plot.county != form.cleaned_data.get('county'):
                    critical_changes.append('county')
                if original_plot.subcounty != form.cleaned_data.get('subcounty'):
                    critical_changes.append('subcounty')
                if original_plot.area != form.cleaned_data.get('area'):
                    critical_changes.append('area')
                if original_plot.area_unit != form.cleaned_data.get('area_unit'):
                    critical_changes.append('area_unit')
                if original_plot.parcel_number != form.cleaned_data.get('parcel_number'):
                    critical_changes.append('parcel_number')
                if original_plot.registration_section != form.cleaned_data.get('registration_section'):
                    critical_changes.append('registration_section')
                if original_plot.price != form.cleaned_data.get('price'):
                    critical_changes.append('price')
                
                # Save the plot
                plot = form.save()
                
                # If critical changes were made, reset verification status
                if critical_changes:
                    logger.info(f"Critical changes detected: {critical_changes}. Resetting verification status.")
                    
                    # Get or create verification status
                    content_type = ContentType.objects.get_for_model(Plot)
                    verification, created = VerificationStatus.objects.get_or_create(
                        content_type=content_type,
                        object_id=plot.id
                    )
                    
                    # Reset to document_uploaded stage
                    verification.current_stage = 'document_uploaded'
                    verification.approved_at = None
                    verification.rejected_at = None
                    verification.stage_details['last_edit'] = {
                        'edited_by': request.user.username,
                        'edited_at': timezone.now().isoformat(),
                        'changes': critical_changes,
                        'previous_stage': verification.current_stage
                    }
                    verification.save()
                    
                    # Reset all tasks to pending
                    VerificationTask.objects.filter(plot=plot).update(
                        status='pending',
                        assigned_to=None,
                        completed_at=None,
                        approved=None
                    )
                    
                    # Log the reset
                    VerificationLog.objects.create(
                        plot=plot,
                        verified_by=request.user,
                        verification_type='system',
                        comment=f"Verification reset due to changes: {', '.join(critical_changes)}"
                    )
                    
                    messages.warning(request, 
                        "⚠️ Critical changes detected. The plot has been moved back to pending verification."
                    )
                
                # Calculate processing time
                processing_time = time.time() - start_time
                
                logger.info(f"✅ Plot updated successfully! ID: {plot.id}")
                logger.info(f"Plot Title: {plot.title}")
                logger.info(f"County: {plot.county}, Subcounty: {plot.subcounty}")
                logger.info(f"Location: {plot.location}")
                logger.info(f"Area: {plot.area} acres")
                logger.info(f"Listing Type: {plot.listing_type}")
                logger.info(f"Critical changes: {critical_changes}")
                logger.info(f"Processing time: {processing_time:.2f} seconds")
                
                # Log document uploads (if any)
                uploaded_docs = []
                for doc_field in ['title_deed', 'official_search', 'landowner_id_doc', 'kra_pin', 'soil_report']:
                    if doc_field in request.FILES:
                        uploaded_docs.append(doc_field)
                
                if uploaded_docs:
                    logger.info(f"New documents uploaded: {uploaded_docs}")
                    
                    # Log document uploads in verification log
                    VerificationLog.objects.create(
                        plot=plot,
                        verified_by=request.user,
                        verification_type='document_update',
                        comment=f"New documents uploaded: {', '.join(uploaded_docs)}"
                    )
                
                # Audit log
                audit_logger.info(f"User {request.user.username} edited plot ID {plot.id}")
                log_audit(request, 'edit_plot', object_type='Plot', object_id=plot.id, 
                         extra={'plot_id': plot.id, 'changes': critical_changes})

                messages.success(request, "✅ Plot updated successfully!")
                logger.info(f"=== PLOT EDIT COMPLETED SUCCESSFULLY (ID: {plot.id}) ===\n")
                return redirect('listings:plot_detail', id=plot.id)

            except ValidationError as e:
                error_msg = f"Validation error while saving plot: {str(e)}"
                logger.error(error_msg, exc_info=True)
                messages.error(request, "Please correct the errors and try again.")
                
            except IntegrityError as e:
                error_msg = f"Database integrity error: {str(e)}"
                logger.error(error_msg, exc_info=True)
                messages.error(request, "A database error occurred. Please try again.")
                
            except DatabaseError as e:
                error_msg = f"Database error: {str(e)}"
                logger.error(error_msg, exc_info=True)
                messages.error(request, "A database error occurred. Please try again.")
                
            except Exception as e:
                error_msg = f"Unexpected error updating plot: {str(e)}"
                logger.error(error_msg, exc_info=True)
                logger.error(f"Traceback: {traceback.format_exc()}")
                
                # Log additional context for debugging
                logger.error(f"User: {request.user.username}")
                logger.error(f"Plot ID: {id}")
                logger.error(f"Request method: {request.method}")
                logger.error(f"POST keys: {list(request.POST.keys())}")
                logger.error(f"FILES keys: {list(request.FILES.keys())}")
                
                messages.error(request, f"❌ Error updating plot: {str(e)}")
        else:
            # Form validation failed
            error_count = len(form.errors)
            logger.warning(f"Form validation failed with {error_count} error(s)")
            
            # Log all form errors in detail
            error_messages = []
            for field, errors in form.errors.items():
                field_value = request.POST.get(field, 'Not provided')
                for error in errors:
                    error_msg = f"{field}: {error}"
                    error_messages.append(error_msg)
                    
                    # Log each validation error with context
                    validation_logger.error(f"Validation error - {error_msg}")
                    validation_logger.error(f"Field value: {field_value}")
                    
                    # Special logging for county/subcounty errors
                    if field in ['county', 'subcounty']:
                        logger.error(f"Location validation error - {field}: {error}")
                        logger.error(f"County selected: {selected_county}")
                        logger.error(f"Subcounty selected: {selected_subcounty}")
                    
                    # Display error to user
                    messages.error(request, error_msg)
            
            # Log all validation errors together
            logger.error(f"Form validation errors summary: {error_messages}")
            logger.error(f"POST data summary: County={selected_county}, Subcounty={selected_subcounty}")
            
            # Update subcounties for dropdown if county was provided
            if selected_county and selected_county in KENYA_SUB_COUNTIES:
                sub_counties = KENYA_SUB_COUNTIES[selected_county]
                logger.info(f"Loaded {len(sub_counties)} subcounties for {selected_county}")
    else:
        # GET request - display form with existing data
        logger.info(f"Processing GET request for plot edit form (ID: {id})")
        form = PlotForm(instance=plot)
        
        # Get subcounties for the plot's county for the dropdown
        if plot.county and plot.county in KENYA_SUB_COUNTIES:
            sub_counties = KENYA_SUB_COUNTIES[plot.county]
            logger.debug(f"Loaded {len(sub_counties)} subcounties for existing county '{plot.county}'")
    
    # Get current verification status for display
    verification_status = None
    pending_tasks = 0
    try:
        content_type = ContentType.objects.get_for_model(Plot)
        verification_status = VerificationStatus.objects.filter(
            content_type=content_type,
            object_id=plot.id
        ).first()
        
        pending_tasks = VerificationTask.objects.filter(
            plot=plot,
            status__in=['pending', 'in_progress']
        ).count()
        
        logger.debug(f"Plot verification status: {verification_status.current_stage if verification_status else 'None'}")
        logger.debug(f"Pending tasks: {pending_tasks}")
    except Exception as e:
        logger.error(f"Error fetching verification data: {str(e)}")
    
    # Prepare subcounties data for JavaScript
    try:
        sub_counties_json = json.dumps(KENYA_SUB_COUNTIES)
        logger.info(f"Prepared subcounties data for {len(KENYA_SUB_COUNTIES)} counties")
    except Exception as e:
        logger.error(f"Error serializing subcounties data: {str(e)}")
        sub_counties_json = '{}'
    
    # Calculate total processing time
    total_time = time.time() - start_time
    logger.info(f"Total request processing time: {total_time:.2f} seconds")
    logger.info("=== PLOT EDIT ENDED ===\n")
    
    # Determine user type for template
    is_agent = hasattr(request.user, 'agent') and plot.agent == request.user.agent
    is_landowner = hasattr(request.user, 'landownerprofile') and plot.landowner == request.user.landownerprofile
    
    return render(request, 'listings/edit_plot.html', {
        'form': form,
        'plot': plot,
        'is_agent': is_agent,
        'is_landowner': is_landowner,
        'profile_type': "Agent" if is_agent else "Landowner",
        'counties': KENYA_COUNTIES,
        'sub_counties_json': sub_counties_json,
        'sub_counties': sub_counties,
        'selected_county': plot.county,
        'selected_subcounty': plot.subcounty,
        'verification_status': verification_status,
        'pending_tasks': pending_tasks,
    })


# ============ DOCUMENT MANAGEMENT ============
REQUIRED_DOC_TYPES = [
    'title_deed',
    'official_search',
    'landowner_id',
    'kra_pin',
]


@login_required
def serve_plot_document(request, plot_id, doc_type):
    """Serve plot document only to owner or staff (Q7/Q8 confidentiality)."""
    from django.http import FileResponse
    from django.views.static import was_modified_since
    import mimetypes

    plot = get_object_or_404(Plot, id=plot_id)
    is_owner = (
        (hasattr(request.user, 'agent') and plot.agent == request.user.agent) or
        (hasattr(request.user, 'landownerprofile') and plot.landowner == request.user.landownerprofile)
    )
    if not (is_owner or request.user.is_staff or request.user.is_superuser):
        from django.http import HttpResponseForbidden
        return HttpResponseForbidden("You don't have permission to view this document.")

    doc_field_map = {
        'title_deed': 'title_deed',
        'soil_report': 'soil_report',
        'official_search': 'official_search',
        'landowner_id_doc': 'landowner_id_doc',
        'kra_pin': 'kra_pin',
    }
    if doc_type not in doc_field_map:
        raise Http404("Invalid document type")
    field_name = doc_field_map[doc_type]
    doc_file = getattr(plot, field_name, None)
    if not doc_file:
        raise Http404("Document not found")

    try:
        response = FileResponse(doc_file.open('rb'), as_attachment=False)
        fn = doc_file.name.split('/')[-1] if doc_file.name else 'document'
        content_type, _ = mimetypes.guess_type(fn)
        response['Content-Type'] = content_type or 'application/octet-stream'
        response['Cache-Control'] = 'no-store, no-cache, must-revalidate, private'
        return response
    except (ValueError, OSError):
        raise Http404("File not found")


@login_required
def upload_verification_doc(request, plot_id):
    """Upload verification document for existing plot"""
    plot = get_object_or_404(Plot, id=plot_id)
    
    # Check permission
    is_agent = hasattr(request.user, 'agent') and plot.agent == request.user.agent
    is_landowner = hasattr(request.user, 'landownerprofile') and plot.landowner == request.user.landownerprofile
    
    if not (is_agent or is_landowner or request.user.is_superuser):
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
# Moved to accounts/ + notifications/ apps.


# ============ VERIFICATION ADMIN ============
@login_required
def verification_dashboard(request):
    """Legacy entrypoint; canonical dashboard lives in views_admin."""
    if not (request.user.is_staff or request.user.is_superuser):
        return redirect('listings:home')
    return redirect('verification:verification_dashboard')


@login_required
def review_plot(request, plot_id):
    """Admin plot review with notifications"""
    if not (request.user.is_staff or request.user.is_superuser):
        messages.error(request, "You don't have permission to access this page.")
        return redirect('listings:home')

    plot = get_object_or_404(Plot.objects.select_related(
        'agent__user', 
        'landowner__user'
    ), id=plot_id)
    
    # Get or create verification status using VerificationStatus model
    content_type = ContentType.objects.get_for_model(Plot)
    verification, created = VerificationStatus.objects.get_or_create(
        content_type=content_type,
        object_id=plot.id,
        defaults={
            'current_stage': 'document_uploaded', 
            'document_uploaded_at': timezone.now()
        }
    )

    # Get pending tasks for this plot
    pending_tasks = VerificationTask.objects.filter(
        plot=plot,
        status__in=['pending', 'in_progress']
    ).count()

    if request.method == 'POST':
        action = request.POST.get('action')
        
        # Handle different review actions
        if action in ['approve', 'reject', 'request_changes']:
            notes = request.POST.get('notes', '')
            
            if action == 'approve':
                from verification.verification_service import VerificationService
                missing_reports = VerificationService.has_required_reports(plot)
                required_types = set(VerificationService.required_task_types(plot))
                existing_types = set(
                    VerificationTask.objects.filter(plot=plot).values_list('verification_type', flat=True)
                )
                missing_types = list(required_types - existing_types)
                if missing_types or missing_reports:
                    messages.error(
                        request,
                        f"Cannot approve. Missing tasks: {missing_types} | Missing reports: {missing_reports}"
                    )
                    return redirect('verification:review_plot', plot_id=plot.id)
                verification.current_stage = 'approved'
                verification.approved_at = timezone.now()
                verification.stage_details['approved_by'] = request.user.username
                verification.stage_details['approval_notes'] = notes
                
                # Log audit
                log_audit(request, 'verify_plot', object_type='Plot', object_id=plot.id, 
                         extra={'plot_id': plot.id, 'action': 'approve'})
                
                # Notify plot owner
                try:
                    from notifications.notification_service import NotificationService
                    plot_owner = plot.agent.user if plot.agent else plot.landowner.user
                    NotificationService.create_notification(
                        user=plot_owner,
                        notification_type='plot_approved',
                        title=f"Plot Approved: {plot.title}",
                        message=f"Your plot '{plot.title}' has been approved and is now live.",
                        plot=plot
                    )
                except Exception as e:
                    logger.error(f"Error sending approval notification: {str(e)}")
                
                messages.success(request, f"✅ Plot '{plot.title}' has been approved!")
                
            elif action == 'reject':
                if not notes:
                    messages.error(request, "Please provide a reason for rejection.")
                    return redirect('verification:review_plot', plot_id=plot.id)
                
                verification.current_stage = 'rejected'
                verification.rejected_at = timezone.now()
                verification.stage_details['rejected_by'] = request.user.username
                verification.stage_details['rejection_reason'] = notes
                
                # Log audit
                log_audit(request, 'reject_plot', object_type='Plot', object_id=plot.id,
                         extra={'plot_id': plot.id, 'action': 'reject', 'reason': notes})
                
                # Notify plot owner
                try:
                    from notifications.notification_service import NotificationService
                    plot_owner = plot.agent.user if plot.agent else plot.landowner.user
                    NotificationService.create_notification(
                        user=plot_owner,
                        notification_type='plot_rejected',
                        title=f"Plot Update: {plot.title}",
                        message=f"Your plot '{plot.title}' has been reviewed. Reason: {notes}",
                        plot=plot
                    )
                except Exception as e:
                    logger.error(f"Error sending rejection notification: {str(e)}")
                
                messages.warning(request, f"❌ Plot '{plot.title}' has been rejected.")
                
            elif action == 'request_changes':
                if not notes:
                    messages.error(request, "Please specify what changes are needed.")
                    return redirect('verification:review_plot', plot_id=plot.id)
                
                verification.current_stage = 'document_uploaded'  # Back to pending
                verification.stage_details['change_requests'] = notes
                verification.stage_details['requested_by'] = request.user.username
                
                # Log audit
                log_audit(request, 'request_changes', object_type='Plot', object_id=plot.id,
                         extra={'plot_id': plot.id, 'action': 'request_changes'})
                
                # Notify plot owner
                try:
                    from notifications.notification_service import NotificationService
                    NotificationService.notify_changes_requested(plot, request.user, notes)
                except Exception as e:
                    logger.error(f"Error sending change request notification: {str(e)}")
                
                messages.info(request, f"✏️ Changes requested for '{plot.title}'")
            
            verification.save()
            
            # Create verification log entry
            VerificationLog.objects.create(
                plot=plot,
                verified_by=request.user,
                verification_type=action,
                comment=notes
            )
            
            return redirect('verification:verification_queue')
        
        # Handle form submissions for detailed verification
        vform = PlotVerificationStatusForm(request.POST, instance=verification)
        sform = TitleSearchResultForm(request.POST, request.FILES,
                                     instance=getattr(plot, 'search_result', None))
        
        if vform.is_valid() and sform.is_valid():
            if sform.instance:
                sform.save()
            vform.save()
            
            verification.refresh_from_db()
            
            # Log status changes
            if verification.current_stage == 'approved':
                log_audit(request, 'verify_plot', object_type='Plot', object_id=plot.id, 
                         extra={'plot_id': plot.id})
            elif verification.current_stage == 'rejected':
                log_audit(request, 'reject_plot', object_type='Plot', object_id=plot.id, 
                         extra={'plot_id': plot.id})
            
            messages.success(request, f"Plot verification status updated to {verification.get_current_stage_display()}.")
            return redirect('verification:verification_queue')
        else:
            messages.error(request, "Please correct the errors below.")
    else:
        vform = PlotVerificationStatusForm(instance=verification)
        sform = TitleSearchResultForm(instance=getattr(plot, 'search_result', None))

    docs = plot.verification_docs.all()
    
    # Get verification history
    verification_logs = VerificationLog.objects.filter(
        plot=plot
    ).select_related('verified_by').order_by('-created_at')[:10]
    
    # Get task summary
    task_stats = {
        'total': VerificationTask.objects.filter(plot=plot).count(),
        'pending': VerificationTask.objects.filter(plot=plot, status='pending').count(),
        'in_progress': VerificationTask.objects.filter(plot=plot, status='in_progress').count(),
        'completed': VerificationTask.objects.filter(plot=plot, status='completed').count(),
    }
    
    return render(request, 'listings/admin/review_plot.html', {
        'plot': plot,
        'docs': docs,
        'vform': vform,
        'sform': sform,
        'verification': verification,
        'verification_logs': verification_logs,
        'task_stats': task_stats,
        'pending_tasks': pending_tasks,
        'page_title': f'Review Plot: {plot.title}'
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


@csrf_exempt
@require_POST
def track_ux_event(request):
    """Lightweight UX analytics endpoint (privacy-respecting)."""
    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    event = payload.get("event")
    allowed_events = {"page_view", "form_submit", "cta_click", "toast_shown"}
    if event not in allowed_events:
        return JsonResponse({"error": "Invalid event"}, status=400)

    user = request.user if getattr(request, "user", None) and request.user.is_authenticated else None
    analytics_logger = logging.getLogger("listings.analytics")
    analytics_logger.info(
        "ux_event=%s user_id=%s path=%s data=%s",
        event,
        getattr(user, "id", None),
        payload.get("path"),
        {k: v for k, v in payload.items() if k not in {"event", "path"}},
    )

    return HttpResponse(status=204)


# ============ LANDOWNER SUCCESS ============
@login_required
def landowner_success(request):
    """Success page after landowner registration wizard"""
    return render(request, 'listings/landowner_success.html')


# ============ STATIC INFO PAGES ============
def info_page(request, slug, template_name):
    page, _ = SitePage.objects.get_or_create(
        slug=slug,
        defaults={"title": slug.replace("_", " ").title()}
    )
    return render(request, template_name, {"page": page})


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
    plot_filter = Q()
    if hasattr(request.user, 'agent'):
        plot_filter |= Q(agent=request.user.agent)
    if hasattr(request.user, 'landownerprofile'):
        plot_filter |= Q(landowner=request.user.landownerprofile)

    if plot_filter:
        plots = Plot.objects.filter(plot_filter).distinct()
        plot_ids = list(plots.values_list('id', flat=True))
        plot_verification_map = {}

        if plot_ids:
            plot_content_type = ContentType.objects.get_for_model(Plot)
            statuses = VerificationStatus.objects.filter(
                content_type=plot_content_type,
                object_id__in=plot_ids
            )
            plot_verification_map = {status.object_id: status for status in statuses}

        for plot in plots:
            verification = plot_verification_map.get(plot.id)
            if verification:
                context['plot_verifications'].append({
                    'plot': plot,
                    'stage': verification.get_current_stage_display(),
                    'progress': verification.progress_percentage,
                    'submitted_at': verification.document_uploaded_at
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


# Phone verification and support flows moved out of listings.
