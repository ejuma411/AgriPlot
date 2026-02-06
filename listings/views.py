from django.http import Http404
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib.auth import authenticate, login
from django.db.models import Q, Count
from django.core.paginator import Paginator
from django.contrib import messages
from .models import *
from .forms import *
from django.contrib.auth.forms import UserCreationForm
from django.db.models import Prefetch


def home(request):
    # Get all verified plots and prefetch related images
    verified_plots = Plot.objects.filter(
        verification_status__status="verified"
    ).prefetch_related(
        'images_list'  # Simple prefetch without Prefetch object
    ).select_related('broker', 'verification_status')

    soil_type = request.GET.get('soil_type')
    crop = request.GET.get('crop')
    
    # Apply filters if present
    if soil_type:
        verified_plots = verified_plots.filter(soil_type__icontains=soil_type)
    if crop:
        verified_plots = verified_plots.filter(crop_suitability__icontains=crop)

    # Limit to a reasonable number for homepage (e.g., 6-12)
    featured_plots = verified_plots[:12]

    # Also get some stats for the homepage
    total_plots = Plot.objects.count()
    verified_count = Plot.objects.filter(verification_status__status="verified").count()
    total_brokers = Broker.objects.filter(verified=True).count()

    # Get unique soil types for filter dropdown
    soil_types = Plot.objects.values_list('soil_type', flat=True).distinct()
    
    # Get common crops for suggestions
    common_crops = ['Maize', 'Wheat', 'Coffee', 'Tea', 'Beans', 
                   'Potatoes', 'Sugarcane', 'Rice', 'Vegetables']

    return render(request, 'listings/home.html', {
        'featured_plots': featured_plots,
        'total_plots': total_plots,
        'verified_count': verified_count,
        'total_brokers': total_brokers,
        'soil_types': soil_types,
        'common_crops': common_crops,
        'filter_soil_type': soil_type,
        'filter_crop': crop,
    })
@login_required
def staff_dashboard(request):
    """Main dashboard for sellers and brokers."""
    context = {}
    
    # Check user type
    is_seller = hasattr(request.user, 'sellerprofile')
    is_broker = hasattr(request.user, 'broker')
    
    if not (is_seller or is_broker):
        messages.error(request, "You need to be a seller or broker to access this dashboard.")
        return redirect('listings:home')
    
    # Get user's plots (seller or broker)
    plots = Plot.objects.none()
    if is_broker:
        plots = Plot.objects.filter(broker=request.user.broker)
    elif is_seller:
        # Sellers might have plots through some other relationship
        # Adjust this based on your model relationships
        plots = Plot.objects.filter(broker__user=request.user)
    
    # Plot statistics
    total_plots = plots.count()
    verified_plots = plots.filter(verification_status__status='verified').count()
    pending_plots = plots.filter(verification_status__status='pending').count()
    rejected_plots = plots.filter(verification_status__status='rejected').count()
    
    # Recent activities
    recent_interests = UserInterest.objects.filter(plot__in=plots).order_by('-created_at')[:5]
    
    # Plot status breakdown
    plot_status_data = {
        'Verified': verified_plots,
        'Pending': pending_plots,
        'Rejected': rejected_plots,
        'Other': total_plots - (verified_plots + pending_plots + rejected_plots)
    }
    
    context.update({
        'is_seller': is_seller,
        'is_broker': is_broker,
        'total_plots': total_plots,
        'verified_plots': verified_plots,
        'pending_plots': pending_plots,
        'rejected_plots': rejected_plots,
        'recent_interests': recent_interests,
        'plot_status_data': plot_status_data,
        'plots': plots.order_by('-id')[:5],  # Recent 5 plots
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
    """View all plots with verification status."""
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
        'pending': plots.filter(verification_status__status='pending').count(),
        'rejected': plots.filter(verification_status__status='rejected').count(),
        'needs_review': plots.filter(verification_status__status='needs_review').count(),
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
    """Detailed view of plot verification status."""
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
        'documents_complete': has_title_deed,  # Title deed is required
    }
    
    return render(request, 'listings/dashboard/plot_verification_detail.html', context)


@login_required
def buyer_interests(request):
    """Manage buyer interests for plots."""
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
    """Update buyer interest status."""
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
    """Manage seller/broker profile."""
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
    """Analytics dashboard for brokers/sellers."""
    is_broker = hasattr(request.user, 'broker')
    
    if not is_broker:
        messages.error(request, "Only brokers can view analytics.")
        return redirect('listings:home')
    
    plots = Plot.objects.filter(broker=request.user.broker)
    
    # Monthly plot additions
    from django.db.models.functions import TruncMonth
    from django.db.models import Count
    from django.utils import timezone
    from datetime import timedelta
    
    monthly_stats = plots.annotate(
        month=TruncMonth('created')
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
        'avg_price': plots.aggregate(avg=models.Avg('price'))['avg__avg'] or 0,
    }
    
    return render(request, 'dashboard/analytics.html', context)

def plot_detail(request, id):
    try:
        plot = Plot.objects.select_related(
            'broker', 
            'verification_status'
        ).prefetch_related(
            'images_list'
        ).get(id=id)
        
        return render(request, 'listings/details.html', {
            'plot': plot,
        })
    except Plot.DoesNotExist:
        raise Http404("Plot does not exist")

@login_required
def edit_plot(request, id):
    try:
        plot = Plot.objects.get(id=id, broker=request.user.broker)
    except Plot.DoesNotExist:
        messages.error(request, "Plot not found or you don't have permission to edit it.")
        return redirect('listings:home')
    
    if request.method == 'POST':
        form = PlotForm(request.POST, request.FILES, instance=plot)
        if form.is_valid():
            # Save the plot first
            plot = form.save(commit=False)
            plot.save()
            
            # Handle multiple image uploads - add new images
            images = request.FILES.getlist('images')
            for image in images[:5]:  # Limit to 5 new images
                if image:
                    PlotImage.objects.create(plot=plot, image=image)
            
            # Handle image deletions if needed (you'd need a form field for this)
            # Example: delete_images = request.POST.getlist('delete_images')
            # for image_id in delete_images:
            #     PlotImage.objects.filter(id=image_id, plot=plot).delete()
            
            messages.success(request, "Plot updated successfully!")
            return redirect('listings:plot_detail', id=plot.id)
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
def add_plot(request):
    # Only verified brokers can add plots
    try:
        broker_profile = request.user.broker
        if not broker_profile.verified:
            messages.error(request, "Your broker account needs to be verified before you can list plots.")
            return redirect("listings:upgrade_broker")
    except Broker.DoesNotExist:
        messages.error(request, "You must be a verified broker to list land.")
        return redirect("listings:upgrade_role")

    if request.method == "POST":
        plot_form = PlotForm(request.POST, request.FILES)
        
        if plot_form.is_valid():
            try:
                # Save plot
                plot = plot_form.save(commit=False)
                plot.broker = broker_profile
                plot.save()
                
                # Handle multiple image uploads
                images = request.FILES.getlist('images')
                for image in images[:5]:  # Limit to 5 images
                    if image:  # Check if file was uploaded
                        PlotImage.objects.create(plot=plot, image=image)
                
                # After saving plot, check if required docs are uploaded
                missing = []
                for doc_type in REQUIRED_DOC_TYPES:
                    if not plot.verification_docs.filter(doc_type=doc_type).exists():
                        missing.append(doc_type)

                if missing:
                    # Store missing doc types in session
                    request.session["missing_docs_for_plot"] = missing
                    request.session["pending_plot_id"] = plot.id

                    messages.warning(request, (
                        "✅ Your listing was saved successfully!\n"
                        "⚠️ However, some required verification documents are missing. "
                        "Please upload them below to complete the listing."
                    ))
                    return redirect("listings:upload_checklist", plot_id=plot.id)

                # All required docs are present — proceed
                messages.success(request, "🎉 Plot listed successfully! It will be reviewed before publication.")
                return redirect("listings:plot_detail", id=plot.id)

            except Exception as e:
                messages.error(request, f"❌ Error creating plot: {str(e)}")
        else:
            # Collect form errors for better user feedback
            error_messages = []
            for field, errors in plot_form.errors.items():
                field_name = plot_form.fields[field].label if plot_form.fields[field].label else field
                for error in errors:
                    error_messages.append(f"{field_name}: {error}")
            
            if error_messages:
                messages.error(request, "Please fix the following errors:")
                for error_msg in error_messages[:3]:  # Show first 3 errors
                    messages.error(request, f"• {error_msg}")
                if len(error_messages) > 3:
                    messages.error(request, f"... and {len(error_messages) - 3} more errors")

    else:
        plot_form = PlotForm()
        # Pre-fill broker info if available
        initial_data = {}
        if hasattr(request.user, 'broker'):
            broker = request.user.broker
            # You could pre-fill location based on broker's common areas
            initial_data['crop_suitability'] = 'Maize, Beans, Vegetables'  # Default suggestion
        plot_form = PlotForm(initial=initial_data)

    upload_form = VerificationDocumentForm()

    return render(request, "listings/add_plot.html", {
        "form": plot_form,
        "upload_form": upload_form,
        "required_docs": REQUIRED_DOC_TYPES,
        "broker": request.user.broker if hasattr(request.user, 'broker') else None,
    })

@login_required
def delete_image(request, id):
    try:
        image = PlotImage.objects.get(id=id, plot__broker=request.user.broker)
        plot_id = image.plot.id
        image.delete()
        messages.success(request, "Image deleted successfully.")
    except PlotImage.DoesNotExist:
        messages.error(request, "Image not found or you don't have permission to delete it.")
        return redirect('listings:home')
    
    return redirect('listings:edit_plot', id=plot_id)


REQUIRED_DOC_TYPES = [
    'title_deed',
    'official_search',
    'seller_id',
    'kra_pin',
]


@login_required
def upload_checklist(request, plot_id):
    # Get the plot
    try:
        plot = Plot.objects.get(id=plot_id, broker=request.user.broker)
    except Plot.DoesNotExist:
        messages.error(request, "Plot not found or you don't have permission to access it.")
        return redirect('listings:my_plots')
    
    # Get missing docs from session or calculate
    missing_docs = request.session.get("missing_docs_for_plot", [])
    
    # If no missing docs in session, check what's actually missing
    if not missing_docs:
        for doc_type in REQUIRED_DOC_TYPES:
            if not plot.verification_docs.filter(doc_type=doc_type).exists():
                missing_docs.append(doc_type)
    
    if request.method == 'POST':
        # Handle document uploads
        form = VerificationDocumentForm(request.POST, request.FILES)
        if form.is_valid():
            doc = form.save(commit=False)
            doc.plot = plot
            # Get doc_type from hidden input
            doc_type = request.POST.get('doc_type')
            if doc_type:
                doc.doc_type = doc_type
            doc.save()
            
            # Remove from missing list
            if doc.doc_type in missing_docs:
                missing_docs.remove(doc.doc_type)
                request.session["missing_docs_for_plot"] = missing_docs
            
            messages.success(request, f"Document uploaded successfully!")
            
            # Check if all docs are now uploaded
            if not missing_docs:
                messages.success(request, "✅ All required documents uploaded! Your plot is now complete.")
                # Clear session data
                if "pending_plot_id" in request.session:
                    del request.session["pending_plot_id"]
                if "missing_docs_for_plot" in request.session:
                    del request.session["missing_docs_for_plot"]
                return redirect('listings:plot_detail', id=plot.id)
            
            return redirect('listings:upload_checklist', plot_id=plot.id)
    else:
        form = VerificationDocumentForm()
    
    return render(request, 'listings/upload_checklist.html', {
        'plot': plot,
        'missing_docs': missing_docs,
        'form': form,
        'required_docs': REQUIRED_DOC_TYPES,
    })
def register(request):
    if request.method == "POST":
        form = UserCreationForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect('login')
    else:
        form = UserCreationForm()
    return render(request, 'listings/auth/register.html', {'form': form})

# SELLER & BROKER REGISTRATION
def register_seller(request):
    next_url = request.GET.get("next", "/")

    if request.method == "POST":
        # Add request.FILES to handle file uploads
        form = SellerRegistrationForm(request.POST, request.FILES)
        if form.is_valid():
            try:
                # Get the user instance but don't save yet
                user = form.save(commit=False)

                # Set additional User fields
                user.first_name = form.cleaned_data["first_name"]
                user.last_name = form.cleaned_data["last_name"]
                user.email = form.cleaned_data["email"]
                user.save()  # now user has been saved in the DB

                # Create Profile for the user
                Profile.objects.create(user=user)

                # Get uploaded files
                national_id_file = form.cleaned_data.get("national_id")
                kra_pin_file = form.cleaned_data.get("kra_pin")

                # Now save seller profile with uploaded files
                SellerProfile.objects.create(
                    user=user,
                    national_id=national_id_file,
                    kra_pin=kra_pin_file,
                    verified=False
                )

                # Log the user in
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
            messages.error(request, "Please fix the errors below.")

    else:
        form = SellerRegistrationForm()

    return render(request, "auth/register_seller.html", {"form": form})

def register_broker(request):
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

                # Create Profile for the user
                Profile.objects.create(user=user)

                Broker.objects.create(
                    user=user,
                    phone=form.cleaned_data["phone"],
                    license_number=form.cleaned_data["license_number"],
                    verified=False
                )

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
            messages.error(request, "Please fix the errors below.")

    else:
        form = BrokerRegistrationForm()

    return render(request, "auth/register_broker.html", {"form": form})


@login_required
def upgrade_role(request):
    # Check if user already has these profiles
    is_seller = hasattr(request.user, 'sellerprofile')
    is_broker = hasattr(request.user, 'broker')
    
    if request.method == "POST":
        role = request.POST.get("role")

        # Redirect to the appropriate upgrade form
        if role == "seller" and not is_seller:
            return redirect("upgrade_seller")  # Changed from "listings:register_seller"
        elif role == "broker" and not is_broker:
            return redirect("upgrade_broker")  # Changed from "listings:register_broker"
        else:
            messages.warning(request, "You already have this role or selected an invalid option.")
            return redirect("upgrade_role")
    
    context = {
        'is_seller': is_seller,
        'is_broker': is_broker,
    }
    return render(request, "listings/upgrade_role.html", context)


# views.py - FINAL WORKING VERSION
@login_required
def upgrade_seller(request):
    # Check if user already has a seller profile
    if hasattr(request.user, 'sellerprofile'):
        messages.info(request, "You already have a seller profile.")
        return redirect('dashboard')
    
    if request.method == "POST":
        form = SellerUpgradeForm(request.POST, request.FILES)
        
        if form.is_valid():
            try:
                # Save using form's save method
                seller_profile = form.save(user=request.user)
                messages.success(request, "Seller profile submitted for verification!")
                return redirect('dashboard')
            except Exception as e:
                messages.error(request, f"Error saving seller profile: {str(e)}")
        else:
            messages.error(request, "Please fix the errors below.")
    
    else:
        # Pre-populate the form with user's username and email
        initial_data = {
            'username': request.user.username,
            'email': request.user.email
        }
        form = SellerUpgradeForm(initial=initial_data)
    
    return render(request, "upgrade_seller.html", {
        "form": form,
        "user": request.user
    })


@login_required
def upgrade_broker(request):
    # Check if user already has a broker profile
    if hasattr(request.user, 'broker'):
        messages.info(request, "You already have a broker profile.")
        return redirect('dashboard')
    
    if request.method == "POST":
        form = BrokerUpgradeForm(request.POST, request.FILES)
        
        if form.is_valid():
            try:
                # Save using form's save method
                broker_profile = form.save(user=request.user)
                messages.success(request, "Broker profile submitted for verification!")
                return redirect('dashboard')
            except Exception as e:
                messages.error(request, f"Error saving broker profile: {str(e)}")
        else:
            messages.error(request, "Please fix the errors below.")
    
    else:
        # Pre-populate the form with user's username and email
        initial_data = {
            'username': request.user.username,
            'email': request.user.email
        }
        form = BrokerUpgradeForm(initial=initial_data)
    
    return render(request, "upgrade_broker.html", {
        "form": form,
        "user": request.user
    })
# VERIFICATION
@login_required
def upload_verification_doc(request, plot_id):
    plot = get_object_or_404(Plot, id=plot_id)

    if not request.user.profile.is_broker:
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

@login_required
def verification_dashboard(request):
    if not request.user.is_staff:
        return redirect('listings:home')

    pending = PlotVerificationStatus.objects.filter(status='pending')
    return render(request, 'listings/verification_dashboard.html', {'pending': pending})

@login_required
def review_plot(request, plot_id):
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

