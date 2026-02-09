from django.contrib import admin
from .models import *
from django.utils.html import format_html
from django.utils import timezone

# ----------------------------------------
# ContactRequest Admin - ADD THIS SECTION
# ----------------------------------------
@admin.register(ContactRequest)
class ContactRequestAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "user_info",
        "broker_info",
        "plot_info",
        "request_type_display",
        "responded_display",
        "created_at",
        "response_time",
    )
    
    list_filter = (
        "request_type",
        "responded",
        "created_at",
        "broker",
    )
    
    search_fields = (
        "user__username",
        "user__email",
        "broker__user__username",
        "broker__user__email",
        "plot__title",
        "message",
    )
    
    readonly_fields = (
        "user",
        "plot",
        "broker",
        "request_type",
        "message",
        "created_at",
        "responded_at",
        "response_time_calculated",
        "summary_info",
        "user_info_admin",
        "plot_info_admin",
        "broker_info_admin",
    )
    
    fieldsets = (
        ("Request Information", {
            "fields": ("summary_info", "request_type", "message")
        }),
        ("User Details", {
            "fields": ("user_info_admin",),
            "classes": ("collapse",),
        }),
        ("Plot Details", {
            "fields": ("plot_info_admin",),
            "classes": ("collapse",),
        }),
        ("Broker Details", {
            "fields": ("broker_info_admin",),
            "classes": ("collapse",),
        }),
        ("Response Management", {
            "fields": ("responded", "responded_at", "admin_notes")
        }),
        ("Timestamps", {
            "fields": ("created_at", "response_time_calculated"),
            "classes": ("collapse",),
        }),
    )
    
    actions = ["mark_as_responded", "mark_as_unresponded", "export_to_csv"]
    
    def user_info(self, obj):
        return format_html(
            '<strong>{}</strong><br><small>{}</small>',
            obj.user.get_full_name() or obj.user.username,
            obj.user.email
        )
    user_info.short_description = "User"
    
    def broker_info(self, obj):
        if obj.broker:
            return format_html(
                '<strong>{}</strong><br><small>{}</small>',
                obj.broker.user.get_full_name() or obj.broker.user.username,
                obj.broker.user.email
            )
        return "-"
    broker_info.short_description = "Broker"
    
    def plot_info(self, obj):
        if obj.plot:
            return format_html(
                '<a href="{}" target="_blank"><strong>{}</strong></a><br><small>{}</small>',
                f"/admin/listings/plot/{obj.plot.id}/change/",
                obj.plot.title[:30] + ("..." if len(obj.plot.title) > 30 else ""),
                obj.plot.location[:30]
            )
        return "-"
    plot_info.short_description = "Plot"
    
    def request_type_display(self, obj):
        type_colors = {
            'email': 'blue',
            'phone_request': 'orange',
            'phone_view': 'green',
            'visit_request': 'purple',
            'message': 'teal',
        }
        color = type_colors.get(obj.request_type, 'gray')
        return format_html(
            '<span style="background: {}; color: white; padding: 3px 8px; border-radius: 3px; font-size: 0.85em;">{}</span>',
            color,
            obj.get_request_type_display()
        )
    request_type_display.short_description = "Type"
    
    def responded_display(self, obj):
        if obj.responded:
            return format_html(
                '<span style="color: green; font-weight: bold;">✓</span><br><small>{}</small>',
                obj.responded_at.strftime("%b %d, %Y") if obj.responded_at else ""
            )
        return format_html('<span style="color: orange; font-weight: bold;">●</span>')
    responded_display.short_description = "Responded"
    
    def response_time(self, obj):
        if obj.responded and obj.responded_at and obj.created_at:
            hours = (obj.responded_at - obj.created_at).total_seconds() / 3600
            if hours < 1:
                return f"{int(hours * 60)}min"
            elif hours < 24:
                return f"{int(hours)}h"
            else:
                days = hours / 24
                return f"{days:.1f}d"
        elif not obj.responded:
            hours = (timezone.now() - obj.created_at).total_seconds() / 3600
            if hours > 72:  # 3 days
                return format_html(
                    '<span style="color: red; font-weight: bold;">{:.0f}d</span>',
                    hours / 24
                )
            elif hours > 24:
                return format_html(
                    '<span style="color: orange; font-weight: bold;">{:.0f}d</span>',
                    hours / 24
                )
            else:
                return f"{int(hours)}h"
        return "-"
    response_time.short_description = "Response Time"
    
    def user_info_admin(self, obj):
        user = obj.user
        return format_html("""
            <div style="background: #f8f9fa; padding: 15px; border-radius: 5px;">
                <strong>Username:</strong> {}<br>
                <strong>Email:</strong> {}<br>
                <strong>Full Name:</strong> {}<br>
                <strong>Date Joined:</strong> {}<br>
                <strong>Last Login:</strong> {}
            </div>
        """,
            user.username,
            user.email,
            user.get_full_name() or "Not set",
            user.date_created if hasattr(user, 'date_created') else user.date_joined,
            user.last_login if user.last_login else "Never"
        )
    user_info_admin.short_description = "User Details"
    
    def plot_info_admin(self, obj):
        if obj.plot:
            plot = obj.plot
            return format_html("""
                <div style="background: #f8f9fa; padding: 15px; border-radius: 5px;">
                    <strong>Title:</strong> {}<br>
                    <strong>Location:</strong> {}<br>
                    <strong>Price:</strong> KES {:,.0f}<br>
                    <strong>Area:</strong> {} acres<br>
                    <strong>Status:</strong> {}<br>
                    <strong><a href="/admin/listings/plot/{}/change/" target="_blank">View Full Details →</a></strong>
                </div>
            """,
                plot.title,
                plot.location,
                plot.price,
                plot.area,
                plot.verification_status.status if hasattr(plot, 'verification_status') else "Unknown",
                plot.id
            )
        return "No plot associated"
    plot_info_admin.short_description = "Plot Details"
    
    def broker_info_admin(self, obj):
        if obj.broker:
            broker = obj.broker
            return format_html("""
                <div style="background: #f8f9fa; padding: 15px; border-radius: 5px;">
                    <strong>Name:</strong> {}<br>
                    <strong>Email:</strong> {}<br>
                    <strong>Phone:</strong> {}<br>
                    <strong>License:</strong> {}<br>
                    <strong>Verified:</strong> {}<br>
                    <strong><a href="/admin/listings/broker/{}/change/" target="_blank">View Broker →</a></strong>
                </div>
            """,
                broker.user.get_full_name() or broker.user.username,
                broker.user.email,
                broker.phone_number or "Not set",
                broker.license_number or "Not set",
                "✓ Yes" if broker.verified else "✗ No",
                broker.id
            )
        return "No broker associated"
    broker_info_admin.short_description = "Broker Details"
    
    def summary_info(self, obj):
        if obj is None:
            return "New contact request form"
        
        return format_html("""
            <div style="background: #e3f2fd; padding: 15px; border-radius: 5px; margin-bottom: 20px;">
                <h4 style="margin-top: 0;">Contact Request Summary</h4>
                <p><strong>Type:</strong> {} from {} regarding plot: <strong>{}</strong></p>
                <p><strong>Status:</strong> {} {}</p>
                <p><strong>Message Preview:</strong> {}</p>
            </div>
        """,
            obj.get_request_type_display() if obj.request_type else "Not set",
            obj.user.get_full_name() or obj.user.username if obj.user else "No user",
            obj.plot.title if obj.plot else "Unknown Plot",
            "Responded" if obj.responded else "Pending",
            f"on {obj.responded_at.strftime('%b %d, %Y %H:%M')}" if obj.responded and obj.responded_at else "",
            obj.message[:200] + ("..." if len(obj.message) > 200 else "") if obj.message else "No message"
        )
    summary_info.short_description = "Summary"
    
    def response_time_calculated(self, obj):
        if obj is None:
            return "New request - not saved yet"
        
        if obj.responded and obj.responded_at:
            delta = obj.responded_at - obj.created_at
            hours = delta.total_seconds() / 3600
            
            if hours < 1:
                return f"Responded in {int(hours * 60)} minutes"
            elif hours < 24:
                return f"Responded in {int(hours)} hours"
            else:
                days = hours / 24
                return f"Responded in {days:.1f} days"
        else:
            # Check if created_at exists (it won't for new objects)
            if hasattr(obj, 'created_at') and obj.created_at:
                hours = (timezone.now() - obj.created_at).total_seconds() / 3600
                if hours > 72:
                    return format_html(
                        '<span style="color: red; font-weight: bold;">Pending for {:.0f} days (URGENT)</span>',
                        hours / 24
                    )
                elif hours > 24:
                    return format_html(
                        '<span style="color: orange; font-weight: bold;">Pending for {:.0f} days</span>',
                        hours / 24
                    )
                else:
                    return f"Pending for {int(hours)} hours"
            else:
                return "Request not yet submitted"
    response_time_calculated.short_description = "Response Time"
    
    def mark_as_responded(self, request, queryset):
        updated = queryset.update(
            responded=True,
            responded_at=timezone.now()
        )
        self.message_user(
            request,
            f"Marked {updated} contact request(s) as responded.",
            level='success'
        )
    mark_as_responded.short_description = "Mark selected as responded"
    
    def mark_as_unresponded(self, request, queryset):
        updated = queryset.update(
            responded=False,
            responded_at=None
        )
        self.message_user(
            request,
            f"Marked {updated} contact request(s) as unresponded.",
            level='success'
        )
    mark_as_unresponded.short_description = "Mark selected as unresponded"
    
    def export_to_csv(self, request, queryset):
        import csv
        from django.http import HttpResponse
        
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="contact_requests.csv"'
        
        writer = csv.writer(response)
        writer.writerow([
            'ID', 'User', 'User Email', 'Broker', 'Plot', 
            'Request Type', 'Message', 'Responded', 'Responded At',
            'Created At', 'Response Time (hours)'
        ])
        
        for obj in queryset:
            response_time = ""
            if obj.responded and obj.responded_at:
                hours = (obj.responded_at - obj.created_at).total_seconds() / 3600
                response_time = f"{hours:.1f}"
            
            writer.writerow([
                obj.id,
                obj.user.get_full_name() or obj.user.username,
                obj.user.email,
                obj.broker.user.get_full_name() if obj.broker else "",
                obj.plot.title if obj.plot else "",
                obj.get_request_type_display(),
                obj.message or "",
                "Yes" if obj.responded else "No",
                obj.responded_at.strftime("%Y-%m-%d %H:%M") if obj.responded_at else "",
                obj.created_at.strftime("%Y-%m-%d %H:%M"),
                response_time
            ])
        
        return response
    export_to_csv.short_description = "Export selected to CSV"
    
    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        queryset = queryset.select_related(
            'user', 
            'plot', 
            'broker__user'
        )
        return queryset
    
    ordering = ('-created_at',)
    
    list_per_page = 50

# ----------------------------------------
# Inline Models for Related Data
# ----------------------------------------
class VerificationDocumentInline(admin.TabularInline):
    model = VerificationDocument
    extra = 0  # don't show empty extra rows
    readonly_fields = ("uploaded_at", "uploaded_by")
    fields = ("doc_type", "file", "uploaded_by", "uploaded_at")
    show_change_link = True


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
# Plot Admin
# ----------------------------------------
@admin.register(Plot)
class PlotAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "title",
        "broker_info",
        "location",
        "price_display",
        "area",
        "image_count",
        "verification_status",
        "has_title_deed",
        "has_verification_docs",
        "reaction_count_display",
        "contact_requests_count",
    )
    
    list_filter = (
        "soil_type", 
        "broker",
        "verification_status__status",
    )
    
    search_fields = (
        "title", 
        "location", 
        "broker__user__username",
    )
    
    readonly_fields = ("broker", "verification_info", "image_preview", "contact_requests_summary", "created_at", "updated_at")
    
    fieldsets = (
        ("Basic Information", {
            "fields": ("title", "broker", "location", "price", "area")
        }),
        ("Agricultural Details", {
            "fields": ("soil_type", "ph_level", "crop_suitability"),
            "classes": ("collapse",),
        }),
        ("Plot Documents", {
            "fields": ("title_deed", "soil_report"),
        }),
        ("Verification Documents", {
            "fields": ("official_search", "seller_id", "kra_pin"),
            "classes": ("collapse",),
        }),
        ("Images", {
            "fields": ("image_preview",),
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
    
    # Inline for images
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
    
    inlines = [PlotImageInline]
    
    actions = ["verify_selected", "reject_selected", "add_sample_images"]
    
    def contact_requests_count(self, obj):
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
    
    def broker_info(self, obj):
        if obj.broker:
            broker = obj.broker
            verified = "✓" if broker.verified else "✗"
            return f"{broker.user.username} ({verified})"
        return "No broker"
    broker_info.short_description = "Broker"
    
    def price_display(self, obj):
        return f"KES {obj.price:,.0f}"
    price_display.short_description = "Price"
    price_display.admin_order_field = "price"
    
    def verification_status(self, obj):
        if hasattr(obj, "verification_status"):
            status = obj.verification_status.status
            colors = {
                "pending": "orange",
                "verified": "green",
                "rejected": "red",
                "in_review": "blue",
            }
            color = colors.get(status, "gray")
            return format_html(
                '<span style="color: {}; font-weight: bold;">{}</span>',
                color,
                status.upper()
            )
        return "-"
    verification_status.short_description = "Status"
    
    def has_title_deed(self, obj):
        if obj.title_deed:
            return format_html('<span style="color: green; font-weight: bold;">✓</span>')
        return format_html('<span style="color: red; font-weight: bold;">✗</span>')
    has_title_deed.short_description = "Title Deed"
    
    def has_verification_docs(self, obj):
        docs = ['official_search', 'seller_id', 'kra_pin']
        uploaded = 0
        for doc in docs:
            if getattr(obj, doc):
                uploaded += 1
        return f"{uploaded}/3"
    has_verification_docs.short_description = "Verification Docs"
    
    def reaction_count_display(self, obj):
        """Display reaction counts for the plot"""
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
    has_verification_docs.short_description = "Verification Docs"
    
    def image_count(self, obj):
        count = obj.images_list.count()
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
        images = obj.images_list.all()[:5]
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
    
    def verification_info(self, obj):
        if hasattr(obj, "verification_status"):
            status = obj.verification_status
            info = f"""
            <div style="background: #f8f9fa; padding: 15px; border-radius: 5px;">
                <strong>Status:</strong> {status.status.upper()}<br>
                <strong>Reviewed by:</strong> {status.reviewed_by.username if status.reviewed_by else "Not reviewed"}<br>
                <strong>Reviewed at:</strong> {status.reviewed_at if status.reviewed_at else "Not reviewed"}<br>
                <strong>Notes:</strong> {status.review_notes or "No notes"}
            </div>
            """
            return format_html(info)
        return "No verification status"
    verification_info.short_description = "Verification Details"
    
    def verify_selected(self, request, queryset):
        for plot in queryset:
            status, created = PlotVerificationStatus.objects.get_or_create(plot=plot)
            status.status = "verified"
            status.reviewed_by = request.user
            status.reviewed_at = timezone.now()
            status.save()
        self.message_user(request, f"{queryset.count()} plot(s) verified.")
    verify_selected.short_description = "Verify selected plots"
    
    def reject_selected(self, request, queryset):
        for plot in queryset:
            status, created = PlotVerificationStatus.objects.get_or_create(plot=plot)
            status.status = "rejected"
            status.reviewed_by = request.user
            status.reviewed_at = timezone.now()
            status.save()
        self.message_user(request, f"{queryset.count()} plot(s) rejected.")
    reject_selected.short_description = "Reject selected plots"
    
    def add_sample_images(self, request, queryset):
        try:
            from django.core.files import File
            from PIL import Image, ImageDraw
            import io
            
            for plot in queryset:
                if plot.images_list.count() == 0:
                    img = Image.new('RGB', (800, 600), color=(73, 109, 137))
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
            
            self.message_user(request, f"Added sample images to {queryset.count()} plot(s).")
        except ImportError:
            self.message_user(request, "PIL/Pillow not installed. Cannot generate sample images.", level='error')
        except Exception as e:
            self.message_user(request, f"Error generating sample images: {str(e)}", level='error')
    add_sample_images.short_description = "Add sample images to selected plots"
    
    def save_model(self, request, obj, form, change):
        if not change and not hasattr(obj, "verification_status"):
            PlotVerificationStatus.objects.create(plot=obj, status="pending")
        super().save_model(request, obj, form, change)
    
    ordering = ('-id',)
    
    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        queryset = queryset.prefetch_related(
            'images_list', 
            'verification_status',
            'contact_requests'
        )
        return queryset

@admin.register(PlotImage)
class PlotImageAdmin(admin.ModelAdmin):
    list_display = ('id', 'plot_title', 'preview', 'uploaded_at')
    list_filter = ('plot', 'uploaded_at')
    search_fields = ('plot__title',)
    readonly_fields = ('preview', 'uploaded_at')
    
    fieldsets = (
        (None, {
            'fields': ('plot', 'image')
        }),
        ('Preview', {
            'fields': ('preview',),
            'classes': ('collapse',),
        }),
        ('Timestamps', {
            'fields': ('uploaded_at',),
            'classes': ('collapse',),
        }),
    )
    
    def plot_title(self, obj):
        return obj.plot.title
    plot_title.short_description = "Plot"
    plot_title.admin_order_field = "plot__title"
    
    def preview(self, obj):
        if obj.image:
            return format_html(
                '<img src="{}" style="max-height: 200px; max-width: 300px;" />',
                obj.image.url
            )
        return "No image"
    preview.short_description = "Preview"
    
    ordering = ('-uploaded_at',)


@admin.register(SoilReport)
class SoilReportAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'plot_link', 'pH', 'organic_matter_pct', 'lab_id', 'verification_status', 'sample_date', 'created_at'
    )
    list_filter = ('verification_status', 'sample_date', 'lab_id')
    search_fields = ('plot__title', 'lab_id')
    readonly_fields = ('created_at', 'updated_at')

    def plot_link(self, obj):
        return format_html('<a href="/admin/listings/plot/{}/change/">{}</a>', obj.plot.id, obj.plot.title)
    plot_link.short_description = 'Plot'

# ----------------------------------------
# Profile Admin
# ----------------------------------------
@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "phone", "address", "is_verified_seller", "is_verified_broker")
    search_fields = ("user__username", "user__email")
    list_filter = ("is_verified_seller", "is_verified_broker")


# ----------------------------------------
# SellerProfile Admin
# ----------------------------------------
@admin.register(SellerProfile)
class SellerProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "verified", "has_national_id", "has_kra_pin", "has_title_deed", "has_land_search")
    list_filter = ("verified",)
    search_fields = ("user__username", "user__email")
    
    def has_national_id(self, obj):
        return "✓" if obj.national_id else "✗"
    has_national_id.short_description = "National ID"
    
    def has_kra_pin(self, obj):
        return "✓" if obj.kra_pin else "✗"
    has_kra_pin.short_description = "KRA PIN"
    
    def has_title_deed(self, obj):
        return "✓" if obj.title_deed else "✗"
    has_title_deed.short_description = "Title Deed"
    
    def has_land_search(self, obj):
        return "✓" if obj.land_search else "✗"
    has_land_search.short_description = "Land Search"


# ----------------------------------------
# Broker Admin (Add contact requests info)
# ----------------------------------------
@admin.register(Broker)
class BrokerAdmin(admin.ModelAdmin):
    list_display = ("user", "phone", "license_number", "has_license_doc", "verified", "contact_requests_count", "response_rate")
    list_filter = ("verified",)
    search_fields = ("user__username", "phone", "license_number")
    
    readonly_fields = ("contact_requests_summary", "response_stats")
    
    fieldsets = (
        ("Basic Information", {
            "fields": ("user", "phone", "license_number", "license_doc", "verified")
        }),
        ("Contact Requests", {
            "fields": ("contact_requests_summary", "response_stats"),
            "classes": ("collapse",),
        }),
        ("Additional Info", {
            "fields": ("created_at", "updated_at"),
            "classes": ("collapse",),
        }),
    )
    
    def contact_requests_count(self, obj):
        total = obj.contact_requests.count()
        responded = obj.contact_requests.filter(responded=True).count()
        
        if total > 0:
            rate = (responded / total) * 100
            color = "green" if rate >= 80 else "orange" if rate >= 50 else "red"
            return format_html(
                '<span style="font-weight: bold;">{} / {}</span><br>'
                '<small style="color: {};">{:.0f}% response rate</small>',
                responded, total, color, rate
            )
        return "0"
    contact_requests_count.short_description = "Contact Requests"
    
    def response_rate(self, obj):
        total = obj.contact_requests.count()
        if total == 0:
            return "No requests"
        
        responded = obj.contact_requests.filter(responded=True).count()
        rate = (responded / total) * 100
        
        if rate >= 80:
            return format_html('<span style="color: green; font-weight: bold;">{:.0f}%</span>', rate)
        elif rate >= 50:
            return format_html('<span style="color: orange; font-weight: bold;">{:.0f}%</span>', rate)
        else:
            return format_html('<span style="color: red; font-weight: bold;">{:.0f}%</span>', rate)
    response_rate.short_description = "Response Rate"
    
    def contact_requests_summary(self, obj):
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
                        <div><strong>Plot:</strong> {}</div>
                        <div><small>Type: {} | {}</small></div>
                        <div><a href="/admin/listings/contactrequest/{}/change/" target="_blank">View Details →</a></div>
                    </div>
                """,
                    color, responded, req.user.get_full_name() or req.user.username,
                    req.created_at.strftime("%b %d, %H:%M"),
                    req.plot.title if req.plot else "No plot",
                    req.get_request_type_display(),
                    "Responded" if req.responded else "Pending",
                    req.id
                )
            html += '</div>'
            
            total_count = obj.contact_requests.count()
            if total_count > 10:
                html += format_html(
                    '<div style="margin-top: 10px; text-align: center;">'
                    '<a href="/admin/listings/contactrequest/?broker__id__exact={}" target="_blank">'
                    'View all {} contact requests →</a>'
                    '</div>',
                    obj.id,
                    total_count
                )
            
            return format_html(html)
        return "No contact requests yet"
    contact_requests_summary.short_description = "Recent Contact Requests"
    
    def response_stats(self, obj):
        total = obj.contact_requests.count()
        if total == 0:
            return "No contact requests"
        
        responded = obj.contact_requests.filter(responded=True).count()
        pending = total - responded
        
        # Calculate average response time
        responded_requests = obj.contact_requests.filter(responded=True, responded_at__isnull=False)
        avg_response_hours = 0
        if responded_requests.exists():
            total_hours = 0
            for req in responded_requests:
                if req.responded_at:
                    hours = (req.responded_at - req.created_at).total_seconds() / 3600
                    total_hours += hours
            avg_response_hours = total_hours / responded_requests.count()
        
        return format_html("""
            <div style="background: #e3f2fd; padding: 15px; border-radius: 5px;">
                <h4 style="margin-top: 0;">Response Statistics</h4>
                <div style="display: flex; gap: 20px; margin-bottom: 15px;">
                    <div style="text-align: center;">
                        <div style="font-size: 24px; font-weight: bold;">{}</div>
                        <div style="font-size: 12px;">Total Requests</div>
                    </div>
                    <div style="text-align: center;">
                        <div style="font-size: 24px; font-weight: bold; color: green;">{}</div>
                        <div style="font-size: 12px;">Responded</div>
                    </div>
                    <div style="text-align: center;">
                        <div style="font-size: 24px; font-weight: bold; color: orange;">{}</div>
                        <div style="font-size: 12px;">Pending</div>
                    </div>
                </div>
                <div><strong>Response Rate:</strong> {:.0f}%</div>
                <div><strong>Avg Response Time:</strong> {:.1f} hours</div>
                <div><strong>Recent Activity:</strong> Last request {}</div>
            </div>
        """,
            total, responded, pending,
            (responded / total * 100) if total > 0 else 0,
            avg_response_hours,
            obj.contact_requests.order_by('-created_at').first().created_at.strftime("%b %d, %Y") if obj.contact_requests.exists() else "Never"
        )
    response_stats.short_description = "Response Statistics"
    
    def has_license_doc(self, obj):
        return "✓" if obj.license_doc else "✗"
    has_license_doc.short_description = "License Doc"
    
    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        queryset = queryset.prefetch_related('contact_requests')
        return queryset


# ----------------------------------------
# VerificationDocument Admin
# ----------------------------------------
@admin.register(VerificationDocument)
class VerificationDocumentAdmin(admin.ModelAdmin):
    list_display = ("plot", "doc_type", "uploaded_by", "uploaded_at", "preview")
    list_filter = ("doc_type",)
    search_fields = ("plot__title", "uploaded_by__username")
    readonly_fields = ("preview", "uploaded_at")
    
    def preview(self, obj):
        if obj.file:
            if obj.file.name.lower().endswith(('.jpg', '.jpeg', '.png', '.gif')):
                return format_html(
                    '<img src="{}" style="max-height: 100px; max-width: 150px;" />',
                    obj.file.url
                )
            else:
                return format_html(
                    '<a href="{}" target="_blank">📄 View Document</a>',
                    obj.file.url
                )
    preview.short_description = "Preview"


# ----------------------------------------
# TitleSearchResult Admin
# ----------------------------------------
@admin.register(TitleSearchResult)
class TitleSearchResultAdmin(admin.ModelAdmin):
    list_display = (
        "plot",
        "search_platform",
        "official_owner",
        "parcel_number",
        "verified",
        "search_date",
    )
    list_filter = ("search_platform", "verified")
    search_fields = ("plot__title", "parcel_number", "official_owner")


# ----------------------------------------
# PlotVerificationStatus Admin
# ----------------------------------------
@admin.register(PlotVerificationStatus)
class PlotVerificationStatusAdmin(admin.ModelAdmin):
    list_display = ("plot", "status", "reviewed_by", "reviewed_at")
    list_filter = ("status",)
    search_fields = ("plot__title", "reviewed_by__username")
    readonly_fields = ("reviewed_at",)


# ----------------------------------------
# UserInterest Admin
# ----------------------------------------
@admin.register(UserInterest)
class UserInterestAdmin(admin.ModelAdmin):
    list_display = ("user", "plot", "status", "created_at", "updated_at")
    list_filter = ("status", "created_at")
    search_fields = ("user__username", "plot__title", "message")
    readonly_fields = ("created_at", "updated_at")


# ----------------------------------------
# PlotReaction Admin
# ----------------------------------------
@admin.register(PlotReaction)
class PlotReactionAdmin(admin.ModelAdmin):
    list_display = ("user", "plot", "reaction_emoji", "created_at")
    list_filter = ("reaction_type", "created_at")
    search_fields = ("user__username", "plot__title")
    readonly_fields = ("created_at",)
    
    def reaction_emoji(self, obj):
        """Display emoji for reaction type"""
        emoji_map = {
            'love': '❤️ Love',
            'like': '👍 Like',
            'potential': '🌱 Potential'
        }
        return emoji_map.get(obj.reaction_type, obj.reaction_type)
    reaction_emoji.short_description = "Reaction"