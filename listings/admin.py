from django.contrib import admin
from .models import *
from django.utils.html import format_html
from django.utils import timezone
from django.contrib.contenttypes.models import ContentType
from django.contrib.contenttypes.fields import GenericForeignKey

# ======================================================
# SIMPLIFIED ADMIN FOR AGRIPLOT - FOCUS ON WHAT MATTERS
# ======================================================

# ----------------------------------------
# USER MANAGEMENT (Consolidated)
# ----------------------------------------
class LandownerInline(admin.StackedInline):
    """Inline for landowner details in User admin"""
    model = LandownerProfile
    can_delete = False
    verbose_name_plural = 'Landowner Details'
    fields = ('national_id', 'kra_pin', 'land_search', 'verified')
    readonly_fields = ('national_id', 'kra_pin', 'land_search')

class AgentInline(admin.StackedInline):
    """Inline for agent details in User admin"""
    model = Agent
    can_delete = False
    verbose_name_plural = 'Agent Details'
    fields = ('phone', 'id_number', 'license_number', 'license_doc', 'kra_pin', 'verified')
    readonly_fields = ('phone', 'id_number', 'license_number', 'license_doc', 'kra_pin')

class PlotImageInline(admin.TabularInline):
    model = PlotImage
    extra = 1
    fields = ('image', 'preview', 'uploaded_at')
    readonly_fields = ('preview', 'uploaded_at')
    
    def preview(self, obj):
        if obj.image:
            return format_html(
                '<img src="{}" style="max-height: 100px; max-width: 150px;" />',
                obj.image.url
            )
        return "No image"
    preview.short_description = "Preview"


class VerificationDocumentInline(admin.TabularInline):
    model = VerificationDocument
    extra = 0
    readonly_fields = ("uploaded_at", "uploaded_by", "preview")
    fields = ("doc_type", "file", "preview", "uploaded_by", "uploaded_at")
    show_change_link = True
    
    def preview(self, obj):
        if obj.file:
            if obj.file.name.lower().endswith(('.jpg', '.jpeg', '.png', '.gif')):
                return format_html(
                    '<img src="{}" style="max-height: 50px; max-width: 50px;" />',
                    obj.file.url
                )
            else:
                return format_html(
                    '<a href="{}" target="_blank">📄</a>',
                    obj.file.url
                )
        return "-"
    preview.short_description = "Preview"


class TitleSearchResultInline(admin.StackedInline):
    model = TitleSearchResult
    extra = 0
    readonly_fields = ("search_date",)
    fields = (
        "search_platform",
        "official_owner",
        "parcel_number",
        "encumbrances",
        "lease_status",
        "search_date",
        "raw_response_file",
        "verified",
        "notes",
    )

# ----------------------------------------
# PROFILE ADMIN (Simple, just for reference)
# ----------------------------------------
@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'role', 'phone')
    list_filter = ('role',)
    search_fields = ('user__username', 'user__email', 'phone')
    
    def has_add_permission(self, request):
        return False  # Profiles are created automatically


# ----------------------------------------
# LANDOWNER VERIFICATION (Focused on pending verifications)
# ----------------------------------------
@admin.register(LandownerProfile)
class LandownerProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'submitted_on', 'has_id', 'has_kra', 'status')
    list_filter = ('verified',)
    search_fields = ('user__username', 'user__email')
    
    fieldsets = (
        ('User Information', {
            'fields': ('user', 'verified', 'verified_at', 'reviewed_by', 'rejection_reason')
        }),
        ('Documents', {
            'fields': ('national_id', 'kra_pin', 'title_deed', 'land_search', 'lcb_consent'),
        }),
    )
    
    def submitted_on(self, obj):
        return obj.user.date_joined.strftime("%Y-%m-%d")
    submitted_on.short_description = 'Submitted'
    
    def has_id(self, obj):
        return bool(obj.national_id)
    has_id.boolean = True
    has_id.short_description = 'ID'
    
    def has_kra(self, obj):
        return bool(obj.kra_pin)
    has_kra.boolean = True
    has_kra.short_description = 'KRA'
    
    def status(self, obj):
        if obj.verified:
            return format_html('<span style="color: green; font-weight: bold;">✓ Verified</span>')
        return format_html('<span style="color: orange; font-weight: bold;">⏳ Pending</span>')
    status.short_description = 'Status'
    
    actions = ['verify_selected']
    
    def verify_selected(self, request, queryset):
        from django.utils import timezone
        for obj in queryset:
            obj.verified = True
            obj.verified_at = timezone.now()
            obj.reviewed_by = request.user
            obj.rejection_reason = ''
            obj.save()
        self.message_user(request, f"{queryset.count()} landowner(s) verified.")
    verify_selected.short_description = "Verify selected landowners"


# ----------------------------------------
# AGENT VERIFICATION (Focused on pending verifications)
# ----------------------------------------
@admin.register(Agent)
class AgentAdmin(admin.ModelAdmin):
    list_display = ('user', 'submitted_on', 'license_number', 'has_license', 'status')
    list_filter = ('verified',)
    search_fields = ('user__username', 'user__email', 'license_number')
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('user', 'phone', 'id_number', 'verified')
        }),
        ('Professional Details', {
            'fields': ('license_number', 'license_doc', 'kra_pin'),
        }),
    )
    
    def submitted_on(self, obj):
        return obj.user.date_joined.strftime("%Y-%m-%d")
    submitted_on.short_description = 'Submitted'
    
    def has_license(self, obj):
        return bool(obj.license_doc)
    has_license.boolean = True
    has_license.short_description = 'License'
    
    def status(self, obj):
        if obj.verified:
            return format_html('<span style="color: green; font-weight: bold;">✓ Verified</span>')
        return format_html('<span style="color: orange; font-weight: bold;">⏳ Pending</span>')
    status.short_description = 'Status'
    
    actions = ['verify_selected']
    
    def verify_selected(self, request, queryset):
        updated = queryset.update(verified=True)
        self.message_user(request, f"{updated} agent(s) verified.")
    verify_selected.short_description = "Verify selected agents"

# ----------------------------------------
# PLOT MANAGEMENT (Simple but comprehensive)
# ----------------------------------------

class VerificationStatusFilter(admin.SimpleListFilter):
    """Custom filter for verification status"""
    title = 'Verification Status'
    parameter_name = 'verification_status'

    def lookups(self, request, model_admin):
        return [
            ('pending', 'Pending'),
            ('api_verification_started', 'API Started'),
            ('title_search_completed', 'Title Search Done'),
            ('owner_verified', 'Owner Verified'),
            ('encumbrance_check', 'Encumbrance Check'),
            ('physical_location_verified', 'Physical Verified'),
            ('admin_review', 'Admin Review'),
            ('approved', 'Approved'),
            ('rejected', 'Rejected'),
        ]

    def queryset(self, request, queryset):
        if self.value():
            # ✅ CORRECT: Use 'verification__current_stage' 
            return queryset.filter(
                verification__current_stage=self.value()
            )
        return queryset

# ----------------------------------------
# PLOT MANAGEMENT - COMPLETE CORRECTED VERSION
# ----------------------------------------

class VerificationStatusFilter(admin.SimpleListFilter):
    """Custom filter for verification status"""
    title = 'Verification Status'
    parameter_name = 'verification_status'

    def lookups(self, request, model_admin):
        return [
            ('pending', 'Pending'),
            ('api_verification_started', 'API Started'),
            ('title_search_completed', 'Title Search Done'),
            ('owner_verified', 'Owner Verified'),
            ('encumbrance_check', 'Encumbrance Check'),
            ('physical_location_verified', 'Physical Verified'),
            ('admin_review', 'Admin Review'),
            ('approved', 'Approved'),
            ('rejected', 'Rejected'),
        ]

    def queryset(self, request, queryset):
        if self.value():
            # ✅ CORRECT: Use 'verification__current_stage' 
            return queryset.filter(
                verification__current_stage=self.value()
            )
        return queryset

@admin.register(Plot)
class PlotAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "title",
        "owner_info",
        "location",
        "price_display",
        "area",
        "listing_type_display",
        "land_type_display",
        "image_count",
        "verification_display",
        "has_all_documents",
        "reaction_count_display",
        "contact_requests_count",
        "created_at",
    )
    
    list_filter = (
        "soil_type",
        "listing_type",
        "land_type",
        "created_at",
    )
    
    search_fields = (
        "title",
        "location",
        "agent__user__username",
        "landowner__user__username",
    )
    
    readonly_fields = (
        "agent",
        "landowner",
        "verification_info",
        "image_preview",
        "contact_requests_summary",
        "documents_summary",
        "created_at",
        "updated_at",
        "price_per_acre_display",
    )
    
    fieldsets = (
        ("Basic Information", {
            "fields": ("title", "agent", "landowner", "location", "area", "listing_type", "land_type", "land_use_description")
        }),
        ("Pricing Information", {
            "fields": ("price", "sale_price", "price_per_acre_display", 
                      "lease_price_monthly", "lease_price_yearly", "lease_duration", "lease_terms"),
        }),
        ("Agricultural Details", {
            "fields": ("soil_type", "ph_level", "crop_suitability"),
            "classes": ("collapse",),
        }),
        ("Infrastructure", {
            "fields": ("has_water", "water_source", "has_electricity", "electricity_meter",
                      "has_road_access", "road_type", "road_distance_km",
                      "has_buildings", "building_description", "fencing"),
            "classes": ("collapse",),
        }),
        ("Plot Documents", {
            "fields": ("title_deed", "soil_report"),
        }),
        ("Verification Documents", {
            "fields": ("official_search", "landowner_id_doc", "kra_pin"),
            "classes": ("collapse",),
        }),
        ("Images", {
            "fields": ("image_preview",),
            "classes": ("collapse",),
        }),
        ("Documents Summary", {
            "fields": ("documents_summary",),
            "classes": ("collapse",),
        }),
        ("Contact Requests", {
            "fields": ("contact_requests_summary",),
            "classes": ("collapse",),
        }),
        ("Verification", {
            "fields": ("verification_info",),
            "classes": ("collapse",),
        }),
        ("Timestamps", {
            "fields": ("created_at", "updated_at"),
            "classes": ("collapse",),
        }),
    )
    
    inlines = [PlotImageInline, VerificationDocumentInline, TitleSearchResultInline]
    
    actions = ["verify_selected", "reject_selected", "add_sample_images", "export_as_csv"]
    
    def owner_info(self, obj):
        """Display owner (agent or landowner) with verification status"""
        if obj.agent:
            verified = "✓" if obj.agent.verified else "✗"
            return format_html(
                '<span title="Agent"><strong>A:</strong> {}</span><br><small>verified: {}</small>',
                obj.agent.user.username,
                verified
            )
        elif obj.landowner:
            verified = "✓" if obj.landowner.verified else "✗"
            return format_html(
                '<span title="Landowner"><strong>L:</strong> {}</span><br><small>verified: {}</small>',
                obj.landowner.user.username,
                verified
            )
        return "-"
    owner_info.short_description = "Owner"
    
    def listing_type_display(self, obj):
        """Display listing type with color coding"""
        colors = {
            'sale': 'green',
            'lease': 'blue',
            'both': 'purple',
        }
        color = colors.get(obj.listing_type, 'gray')
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span>',
            color,
            obj.get_listing_type_display()
        )
    listing_type_display.short_description = "Type"
    
    def land_type_display(self, obj):
        """Display land type"""
        return obj.get_land_type_display()
    land_type_display.short_description = "Land Type"
    
    def price_display(self, obj):
        """Display price formatted"""
        return f"KES {obj.price:,.0f}"
    price_display.short_description = "Price"
    price_display.admin_order_field = "price"
    
    def price_per_acre_display(self, obj):
        """Display price per acre"""
        if obj.price_per_acre:
            return f"KES {obj.price_per_acre:,.0f}"
        elif obj.sale_price and obj.area and obj.area > 0:
            per_acre = obj.sale_price / obj.area
            return f"KES {per_acre:,.0f} (calculated)"
        return "-"
    price_per_acre_display.short_description = "Price/Acre"
    
    def image_count(self, obj):
        """Display image count with color"""
        count = obj.images.count()
        if count > 0:
            return format_html(
                '<span style="color: green; font-weight: bold;">{}</span>',
                count
            )
        return format_html(
            '<span style="color: red; font-weight: bold;">{}</span>',
            "0"
        )
    image_count.short_description = "Images"
    
    def image_preview(self, obj):
        """Preview images"""
        images = obj.images.all()[:5]
        if images.exists():
            html = '<div style="display: flex; flex-wrap: wrap; gap: 10px;">'
            for image in images:
                html += format_html(
                    '<div style="flex: 0 0 150px; margin-bottom: 10px;">'
                    '<img src="{}" style="width: 150px; height: 100px; object-fit: cover; border-radius: 5px;" />'
                    '</div>',
                    image.image.url if image.image else ''
                )
            html += '</div>'
            return format_html(html)
        return "No images uploaded"
    image_preview.short_description = "Image Gallery"
    
    def documents_summary(self, obj):
        """Display summary of document status"""
        docs_status = []
        
        if obj.title_deed:
            docs_status.append(('Title Deed', '✓', 'green'))
        else:
            docs_status.append(('Title Deed', '✗', 'red'))
            
        if obj.official_search:
            docs_status.append(('Official Search', '✓', 'green'))
        else:
            docs_status.append(('Official Search', '✗', 'red'))
            
        if obj.landowner_id_doc:
            docs_status.append(('Landowner ID', '✓', 'green'))
        else:
            docs_status.append(('Landowner ID', '✗', 'red'))
            
        if obj.kra_pin:
            docs_status.append(('KRA PIN', '✓', 'green'))
        else:
            docs_status.append(('KRA PIN', '✗', 'red'))
            
        if obj.soil_report:
            docs_status.append(('Soil Report', '✓', 'green'))
        else:
            docs_status.append(('Soil Report', '✗', 'orange'))
        
        html = '<div style="display: grid; grid-template-columns: repeat(2, 1fr); gap: 10px;">'
        for doc_name, status, color in docs_status:
            html += format_html(
                '<div style="padding: 8px; background: #f8f9fa; border-radius: 5px;">'
                '<strong>{}:</strong> <span style="color: {}; font-weight: bold;">{}</span>'
                '</div>',
                doc_name, color, status
            )
        html += '</div>'
        
        return format_html(html)
    documents_summary.short_description = "Documents Status"
    
    def contact_requests_count(self, obj):
        """Display count of contact requests with link"""
        count = obj.contact_requests.count()
        if count > 0:
            return format_html(
                '<a href="/admin/listings/contactrequest/?plot__id__exact={}" style="color: {}; font-weight: bold;">{} ({})</a>',
                obj.id,
                'red' if count > 5 else 'orange' if count > 2 else 'green',
                count,
                'urgent' if count > 5 else 'new' if count > 0 else ''
            )
        return "0"
    contact_requests_count.short_description = "Contact Requests"
    
    def contact_requests_summary(self, obj):
        """Display summary of recent contact requests"""
        requests = obj.contact_requests.all()[:10]
        if requests.exists():
            html = '<div style="max-height: 300px; overflow-y: auto; padding: 10px; background: #f8f9fa; border-radius: 5px;">'
            for req in requests:
                responded = "✓" if req.responded else "●"
                color = "green" if req.responded else "orange"
                html += format_html("""
                    <div style="border-bottom: 1px solid #ddd; padding: 8px 0; margin-bottom: 8px;">
                        <div style="display: flex; justify-content: space-between;">
                            <span style="color: {}; font-weight: bold;">{} {}</span>
                            <small>{}</small>
                        </div>
                        <div><strong>{}</strong>: {}</div>
                        <div><small>Type: {} | Created: {}</small></div>
                        <div><a href="/admin/listings/contactrequest/{}/change/" target="_blank">View Details →</a></div>
                    </div>
                """,
                    color, responded, req.user.get_full_name() or req.user.username,
                    req.created_at.strftime("%b %d, %H:%M"),
                    req.get_request_type_display(),
                    req.message[:100] + ("..." if len(req.message) > 100 else "") if req.message else "No message",
                    req.get_request_type_display(),
                    req.created_at.strftime("%Y-%m-%d"),
                    req.id
                )
            html += '</div>'
            
            total_count = obj.contact_requests.count()
            if total_count > 10:
                html += format_html(
                    '<div style="margin-top: 10px; text-align: center;">'
                    '<a href="/admin/listings/contactrequest/?plot__id__exact={}" target="_blank">'
                    'View all {} contact requests →</a>'
                    '</div>',
                    obj.id,
                    total_count
                )
            
            return format_html(html)
        return "No contact requests yet"
    contact_requests_summary.short_description = "Recent Contact Requests"
    
    def reaction_count_display(self, obj):
        """Display reaction counts"""
        counts = obj.get_reaction_counts()
        total = obj.total_reaction_count()
        
        if total == 0:
            return format_html('<span style="color: #ccc;">No reactions</span>')
        
        return format_html(
            '❤️ {} | 👍 {} | 🌱 {} | <strong>Total: {}</strong>',
            counts.get('love', 0),
            counts.get('like', 0),
            counts.get('potential', 0),
            total
        )
    reaction_count_display.short_description = "Reactions"
    
    def has_all_documents(self, obj):
        """Check if plot has all required documents - uses property without parentheses"""
        if obj.has_all_documents:  # Property, not method
            return format_html('<span style="color: green; font-weight: bold;">✓ Complete</span>')
        else:
            missing = []
            if not obj.title_deed:
                missing.append('Title')
            if not obj.official_search:
                missing.append('Search')
            if not obj.landowner_id_doc:
                missing.append('ID')
            if not obj.kra_pin:
                missing.append('KRA')
            return format_html(
                '<span style="color: red; font-weight: bold;">✗ Missing: {}</span>',
                ', '.join(missing)
            )
    has_all_documents.short_description = "All Documents"
    
    # ============ VERIFICATION METHODS ============
    
    def get_verification(self, obj):
        """Helper method to get verification object"""
        from django.contrib.contenttypes.models import ContentType
        content_type = ContentType.objects.get_for_model(Plot)
        try:
            return VerificationStatus.objects.get(
                content_type=content_type,
                object_id=obj.id
            )
        except VerificationStatus.DoesNotExist:
            return None
    
    def verification_display(self, obj):
        """Display verification status with colors"""
        verification = self.get_verification(obj)
        if verification:
            status = verification.current_stage
            colors = {
                'pending': 'orange',
                'api_verification_started': 'blue',
                'title_search_completed': 'blue',
                'owner_verified': 'blue',
                'encumbrance_check': 'blue',
                'physical_location_verified': 'blue',
                'admin_review': 'purple',
                'approved': 'green',
                'rejected': 'red',
            }
            color = colors.get(status, 'gray')
            display_map = dict(VerificationStatus.STAGES)
            display_text = display_map.get(status, status.replace('_', ' ').title())
            
            # Add progress indicator
            progress = verification.progress_percentage
            return format_html(
                '<span style="color: {}; font-weight: bold;">{}</span><br>'
                '<small>Progress: {}%</small>',
                color,
                display_text,
                progress
            )
        return format_html('<span style="color: gray;">No Status</span>')
    verification_display.short_description = "Status"
    
    def verification_info(self, obj):
        """Display detailed verification information"""
        verification = self.get_verification(obj)
        if verification:
            info = f"""
            <div style="background: #f8f9fa; padding: 15px; border-radius: 5px;">
                <strong>Status:</strong> {verification.get_current_stage_display()}<br>
                <strong>Progress:</strong> {verification.progress_percentage}%<br>
                <strong>Search Reference:</strong> {verification.search_reference or 'Not available'}<br>
                <strong>API Responses:</strong> {len(verification.api_responses)}<br>
                <strong>Submitted:</strong> {verification.document_uploaded_at or 'Not submitted'}<br>
                <strong>Admin Review:</strong> {verification.admin_review_at or 'Not yet'}<br>
                <strong>Approved:</strong> {verification.approved_at or 'Not yet'}<br>
                <strong>Details:</strong> {verification.stage_details or 'No details'}
            </div>
            """
            return format_html(info)
        return "No verification status"
    verification_info.short_description = "Verification Details"
    
    # ============ ADMIN ACTIONS ============
    
    def verify_selected(self, request, queryset):
        """Admin action to verify selected plots"""
        from django.contrib.contenttypes.models import ContentType
        
        content_type = ContentType.objects.get_for_model(Plot)
        count = 0
        for plot in queryset:
            verification, created = VerificationStatus.objects.get_or_create(
                content_type=content_type,
                object_id=plot.id,
                defaults={
                    'current_stage': 'approved',
                    'document_uploaded_at': timezone.now(),
                    'approved_at': timezone.now()
                }
            )
            if not created:
                verification.current_stage = 'approved'
                verification.approved_at = timezone.now()
            verification.stage_details = {
                'reviewed_by': request.user.username, 
                'reviewed_at': timezone.now().isoformat(),
                'action': 'verified'
            }
            verification.save()
            count += 1
        self.message_user(request, f"✅ {count} plot(s) verified.")
    verify_selected.short_description = "✅ Verify selected plots"
    
    def reject_selected(self, request, queryset):
        """Admin action to reject selected plots"""
        from django.contrib.contenttypes.models import ContentType
        
        content_type = ContentType.objects.get_for_model(Plot)
        count = 0
        for plot in queryset:
            verification, created = VerificationStatus.objects.get_or_create(
                content_type=content_type,
                object_id=plot.id,
                defaults={
                    'current_stage': 'rejected',
                    'document_uploaded_at': timezone.now()
                }
            )
            if not created:
                verification.current_stage = 'rejected'
            verification.stage_details = {
                'reviewed_by': request.user.username, 
                'reviewed_at': timezone.now().isoformat(),
                'notes': 'Rejected by admin',
                'action': 'rejected'
            }
            verification.save()
            count += 1
        self.message_user(request, f"❌ {count} plot(s) rejected.")
    reject_selected.short_description = "❌ Reject selected plots"
    
    def export_as_csv(self, request, queryset):
        """Export plots as CSV with correct verification status"""
        import csv
        from django.http import HttpResponse
        from django.contrib.contenttypes.models import ContentType
        
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="plots_export.csv"'
        
        writer = csv.writer(response)
        writer.writerow([
            'ID', 'Title', 'Location', 'Price', 'Area', 'Listing Type', 'Land Type',
            'Soil Type', 'Crop Suitability', 'Owner Type', 'Owner', 'Status',
            'Progress %', 'Images', 'Created At'
        ])
        
        content_type = ContentType.objects.get_for_model(Plot)
        for plot in queryset:
            owner_type = 'Agent' if plot.agent else 'Landowner'
            owner_name = plot.agent.user.username if plot.agent else (plot.landowner.user.username if plot.landowner else 'N/A')
            
            # Get verification data
            try:
                verification = VerificationStatus.objects.get(
                    content_type=content_type,
                    object_id=plot.id
                )
                status = verification.current_stage
                progress = verification.progress_percentage
                status_display = dict(VerificationStatus.STAGES).get(status, status)
            except VerificationStatus.DoesNotExist:
                status = 'pending'
                status_display = 'Pending'
                progress = 0
            
            writer.writerow([
                plot.id,
                plot.title,
                plot.location,
                plot.price,
                plot.area,
                plot.get_listing_type_display(),
                plot.get_land_type_display(),
                plot.soil_type,
                plot.crop_suitability,
                owner_type,
                owner_name,
                status_display,
                f"{progress}%",
                plot.images.count(),
                plot.created_at.strftime('%Y-%m-%d')
            ])
        
        return response
    export_as_csv.short_description = "📊 Export selected to CSV"
    
    def add_sample_images(self, request, queryset):
        """Add sample images to plots without images"""
        try:
            from django.core.files import File
            from PIL import Image, ImageDraw
            import io
            import random
            
            colors = [(73, 109, 137), (46, 125, 50), (183, 28, 28), (245, 124, 0), (106, 27, 154)]
            count = 0
            
            for plot in queryset:
                if plot.images.count() == 0:
                    img = Image.new('RGB', (800, 600), color=random.choice(colors))
                    draw = ImageDraw.Draw(img)
                    
                    try:
                        from PIL import ImageFont
                        font = ImageFont.truetype("arial.ttf", 40)
                    except:
                        font = None
                    
                    text = f"Plot: {plot.title[:20]}"
                    if font:
                        bbox = draw.textbbox((0, 0), text, font=font)
                        text_width = bbox[2] - bbox[0]
                        text_height = bbox[3] - bbox[1]
                        x = (800 - text_width) / 2
                        y = (600 - text_height) / 2
                        draw.text((x, y), text, fill=(255, 255, 255), font=font)
                    else:
                        draw.text((100, 250), text, fill=(255, 255, 255))
                    
                    img_io = io.BytesIO()
                    img.save(img_io, 'JPEG', quality=85)
                    img_io.seek(0)
                    
                    plot_image = PlotImage(plot=plot)
                    plot_image.image.save(f"plot_{plot.id}_sample.jpg", File(img_io), save=True)
                    plot_image.save()
                    count += 1
            
            self.message_user(request, f"🖼️ Added sample images to {count} plot(s).")
        except ImportError:
            self.message_user(request, "PIL/Pillow not installed. Cannot generate sample images.", level='error')
        except Exception as e:
            self.message_user(request, f"Error generating sample images: {str(e)}", level='error')
    add_sample_images.short_description = "🖼️ Add sample images to selected plots"
    
    def save_model(self, request, obj, form, change):
        """Create verification status for new plots"""
        super().save_model(request, obj, form, change)
        
        # Create verification status for new plots
        if not change:  # Only for new plots
            from django.contrib.contenttypes.models import ContentType
            content_type = ContentType.objects.get_for_model(Plot)
            VerificationStatus.objects.get_or_create(
                content_type=content_type,
                object_id=obj.id,
                defaults={
                    'current_stage': 'pending',
                    'document_uploaded_at': timezone.now()
                }
            )
    
    ordering = ('-created_at',)
    
    def get_queryset(self, request):
        """Optimize queryset - removed verification from select_related"""
        queryset = super().get_queryset(request)
        queryset = queryset.select_related(
            'agent__user',
            'landowner__user'
        ).prefetch_related(
            'images',
            'contact_requests',
            'reactions'
        )
        return queryset
    
# ----------------------------------------
# PLOT IMAGES (Simple)
# ----------------------------------------
@admin.register(PlotImage)
class PlotImageAdmin(admin.ModelAdmin):
    list_display = ('id', 'plot_title', 'image_preview', 'uploaded_at')
    list_filter = ('uploaded_at',)
    search_fields = ('plot__title',)
    
    def plot_title(self, obj):
        return obj.plot.title
    plot_title.short_description = 'Plot'
    
    def image_preview(self, obj):
        if obj.image:
            return format_html('<img src="{}" style="max-height: 50px;" />', obj.image.url)
        return '-'
    image_preview.short_description = 'Preview'


# ----------------------------------------
# CONTACT REQUESTS (Simple)
# ----------------------------------------
@admin.register(ContactRequest)
class ContactRequestAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'plot_title', 'request_type', 'responded', 'created_at')
    list_filter = ('request_type', 'responded', 'created_at')
    search_fields = ('user__username', 'plot__title', 'message')
    
    def plot_title(self, obj):
        return obj.plot.title if obj.plot else '-'
    plot_title.short_description = 'Plot'
    
    def has_add_permission(self, request):
        return False


# ----------------------------------------
# USER INTERESTS (Simple)
# ----------------------------------------
@admin.register(UserInterest)
class UserInterestAdmin(admin.ModelAdmin):
    list_display = ('user', 'plot_title', 'status', 'created_at')
    list_filter = ('status', 'created_at')
    search_fields = ('user__username', 'plot__title')
    
    def plot_title(self, obj):
        return obj.plot.title
    plot_title.short_description = 'Plot'

@admin.register(VerificationStatus)
class VerificationStatusAdmin(admin.ModelAdmin):
    list_display = ('id', 'content_object_display', 'current_stage', 'progress', 'created_at')
    list_filter = ('current_stage', 'created_at')
    list_select_related = ('content_type',)  # Optimize queries
    search_fields = ('search_reference',)
    readonly_fields = ('created_at', 'updated_at', 'api_responses', 'stage_details', 
                       'progress_percentage', 'content_type', 'object_id', 'content_object_display')
    
    fieldsets = (
        ('Target', {
            'fields': ('content_type', 'object_id', 'content_object_display')  # ✅ Use display field instead
        }),
        ('Current Status', {
            'fields': ('current_stage', 'is_complete', 'progress_percentage')
        }),
        ('API Data', {
            'fields': ('search_reference', 'search_fee_paid', 'api_responses'),
            'classes': ('collapse',),
        }),
        ('Timestamps', {
            'fields': ('document_uploaded_at', 'api_started_at', 'title_search_at',
                      'owner_verified_at', 'admin_review_at', 'approved_at', 'rejected_at'),
            'classes': ('collapse',),
        }),
        ('Details', {
            'fields': ('stage_details',),
            'classes': ('collapse',),
        }),
    )
    
    def content_object_display(self, obj):
        """Display the content object (landowner, agent, or plot)"""
        if obj.content_object:
            if hasattr(obj.content_object, 'user'):
                # For LandownerProfile or Agent
                user = obj.content_object.user
                return format_html(
                    '<strong>{}</strong><br><small>{} - {}</small>',
                    user.get_full_name() or user.username,
                    obj.content_object.__class__.__name__,
                    obj.content_type
                )
            elif hasattr(obj.content_object, 'title'):
                # For Plot
                return format_html(
                    '<strong>{}</strong><br><small>Plot #{} - {}</small>',
                    obj.content_object.title,
                    obj.content_object.id,
                    obj.content_object.location
                )
            return str(obj.content_object)
        return "-"
    content_object_display.short_description = 'Content Object'
    
    def progress(self, obj):
        """Display progress percentage with a simple bar"""
        progress = obj.progress_percentage
        return format_html(
            '{}% <progress value="{}" max="100" style="width: 60px;"></progress>',
            progress, progress
        )
    progress.short_description = 'Progress'
    
    def get_queryset(self, request):
        """Optimize queryset"""
        queryset = super().get_queryset(request)
        return queryset.select_related('content_type')
    
    actions = ['mark_as_approved', 'mark_as_rejected', 'reset_to_pending']
    
    def mark_as_approved(self, request, queryset):
        for obj in queryset:
            obj.update_stage('approved', {
                'approved_by': request.user.username,
                'approved_at': timezone.now().isoformat()
            })
        self.message_user(request, f"{queryset.count()} verification(s) marked as approved.")
    mark_as_approved.short_description = "Mark selected as approved"
    
    def mark_as_rejected(self, request, queryset):
        for obj in queryset:
            obj.update_stage('rejected', {
                'rejected_by': request.user.username,
                'rejected_at': timezone.now().isoformat()
            })
        self.message_user(request, f"{queryset.count()} verification(s) marked as rejected.")
    mark_as_rejected.short_description = "Mark selected as rejected"
    
    def reset_to_pending(self, request, queryset):
        for obj in queryset:
            obj.update_stage('document_uploaded')
        self.message_user(request, f"{queryset.count()} verification(s) reset to pending.")
    reset_to_pending.short_description = "Reset selected to pending"


# -----------------------------
# FYP: Audit, Pricing, Verification Tasks, Document Verification
# -----------------------------
@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'action', 'object_type', 'object_id', 'ip_address', 'created_at')
    list_filter = ('action', 'created_at')
    search_fields = ('user__username', 'action', 'object_type')
    readonly_fields = ('user', 'action', 'object_type', 'object_id', 'extra', 'ip_address', 'user_agent', 'created_at')
    date_hierarchy = 'created_at'


@admin.register(PriceComparable)
class PriceComparableAdmin(admin.ModelAdmin):
    list_display = ('location', 'area_acres', 'sale_price', 'price_per_acre', 'soil_type', 'sale_date', 'verified')
    list_filter = ('verified',)
    search_fields = ('location', 'soil_type')


@admin.register(PricingSuggestion)
class PricingSuggestionAdmin(admin.ModelAdmin):
    list_display = ('plot', 'suggested_price', 'price_range_min', 'price_range_max', 'comparable_plots_used', 'generated_at')
    list_filter = ('generated_at',)
    search_fields = ('plot__title',)


@admin.register(VerificationTask)
class VerificationTaskAdmin(admin.ModelAdmin):
    list_display = ('plot', 'verification_type', 'assigned_to', 'status', 'approved', 'assigned_at')
    list_filter = ('verification_type', 'status')
    search_fields = ('plot__title', 'assigned_to__username')


@admin.register(VerificationLog)
class VerificationLogAdmin(admin.ModelAdmin):
    list_display = ('plot', 'verified_by', 'verification_type', 'created_at')
    list_filter = ('verification_type',)
    search_fields = ('plot__title',)


@admin.register(DocumentVerification)
class DocumentVerificationAdmin(admin.ModelAdmin):
    list_display = ('user', 'document_type', 'approved', 'name_matches_user', 'verified_by', 'verified_at')
    list_filter = ('document_type', 'approved')
    search_fields = ('user__username',)

