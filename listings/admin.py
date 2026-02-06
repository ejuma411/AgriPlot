from django.contrib import admin
from .models import *
from django.utils.html import format_html
from django.utils import timezone

# ----------------------------------------
# Inline Models for Related Data
# ----------------------------------------
class VerificationDocumentInline(admin.TabularInline):
    model = VerificationDocument
    extra = 0  # don’t show empty extra rows
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
    
    readonly_fields = ("broker", "verification_info", "image_preview")
    
    fieldsets = (
        ("Basic Information", {
            "fields": ("title", "broker", "location", "price", "area")
        }),
        ("Agricultural Details", {
            "fields": ("soil_type", "ph_level", "crop_suitability"),
            "classes": ("collapse",),
        }),
        ("Documents", {
            "fields": ("title_deed", "soil_report"),
        }),
        ("Images", {
            "fields": ("image_preview",),
            "classes": ("collapse",),
        }),
        ("Verification", {
            "fields": ("verification_info",),
            "classes": ("collapse",),
        }),
    )
    
    # Inline for images
    class PlotImageInline(admin.TabularInline):
        model = PlotImage
        extra = 1
        fields = ('image', 'preview', 'uploaded_at')  # Removed 'caption'
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
                "needs_review": "blue",
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
            return "✓"
        return "✗"
    has_title_deed.short_description = "Title Deed"
    
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
                <strong>Comments:</strong> {status.comments or "No comments"}
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
            from PIL import Image
            import io
            from PIL import ImageDraw, ImageFont
            
            for plot in queryset:
                if plot.images_list.count() == 0:
                    img = Image.new('RGB', (800, 600), color=(73, 109, 137))
                    draw = ImageDraw.Draw(img)
                    
                    try:
                        font = ImageFont.truetype("arial.ttf", 40)
                    except:
                        font = ImageFont.load_default()
                    
                    text = f"Plot: {plot.title[:20]}"
                    bbox = draw.textbbox((0, 0), text, font=font)
                    text_width = bbox[2] - bbox[0]
                    text_height = bbox[3] - bbox[1]
                    x = (800 - text_width) / 2
                    y = (600 - text_height) / 2
                    
                    draw.text((x, y), text, fill=(255, 255, 255), font=font)
                    
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
        queryset = queryset.prefetch_related('images_list', 'verification_status')  # Changed from 'plot_images'
        return queryset

@admin.register(PlotImage)
class PlotImageAdmin(admin.ModelAdmin):
    list_display = ('id', 'plot_title', 'preview', 'uploaded_at')  # Removed 'caption'
    list_filter = ('plot', 'uploaded_at')
    search_fields = ('plot__title',)  # Removed 'caption' from search
    readonly_fields = ('preview', 'uploaded_at')
    
    fieldsets = (
        (None, {
            'fields': ('plot', 'image')  # Removed 'caption'
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

# ----------------------------------------
# Profile Admin
# ----------------------------------------
@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "phone", "address")
    search_fields = ("user__username", "user__email")


# ----------------------------------------
# SellerProfile Admin
# ----------------------------------------
@admin.register(SellerProfile)
class SellerProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "national_id", "kra_pin", "verified")
    list_filter = ("verified",)
    search_fields = ("user__username", "national_id", "kra_pin")


# ----------------------------------------
# Broker Admin
# ----------------------------------------
@admin.register(Broker)
class BrokerAdmin(admin.ModelAdmin):
    list_display = ("user", "license_number", "verified")
    list_filter = ("verified",)
    search_fields = ("user__username", "license_number")


# ----------------------------------------
# VerificationDocument Admin
# ----------------------------------------
@admin.register(VerificationDocument)
class VerificationDocumentAdmin(admin.ModelAdmin):
    list_display = ("plot", "doc_type", "uploaded_by", "uploaded_at")
    list_filter = ("doc_type",)
    search_fields = ("plot__title", "uploaded_by__username")


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
