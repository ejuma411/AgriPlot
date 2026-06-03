from django.contrib import admin
from django.core.management import call_command
from django.db.utils import OperationalError, ProgrammingError
from django.utils import timezone
from django.utils.html import format_html

from accounts.models import Agent, LandownerProfile
from listings.models import (
    ComparableSale,
    ContactRequest,
    MarketPriceBand,
    Plot,
    PlotImage,
    PriceComparable,
    PricingSuggestion,
    SitePage,
    UserInterest,
    WaterSource,
    Road,
    Market,
    School,
    HealthFacility,
    LandTransferAgreement,
    FraudReport,
    UserPlotView,
)
from verification.models import TitleSearchResult, VerificationDocument, VerificationStatus


admin.site.site_header = "AgriPlot Administration"
admin.site.site_title = "AgriPlot Admin"
admin.site.index_title = "System Management"


class SafeMissingTableAdmin(admin.ModelAdmin):
    """Gracefully handle admin pages for models whose migrations are not applied yet."""

    def get_queryset(self, request):
        try:
            return super().get_queryset(request)
        except (ProgrammingError, OperationalError):
            return self.model.objects.none()


class VerificationDocumentInline(admin.TabularInline):
    model = VerificationDocument
    extra = 0
    readonly_fields = ("uploaded_at", "uploaded_by", "preview")
    fields = ("doc_type", "file", "preview", "uploaded_by", "uploaded_at")
    show_change_link = True

    def preview(self, obj):
        if obj.file:
            if obj.file.name.lower().endswith((".jpg", ".jpeg", ".png", ".gif")):
                return format_html(
                    '<img src="{}" style="max-height: 50px; max-width: 50px;" />',
                    obj.file.url,
                )
            return format_html('<a href="{}" target="_blank">📄</a>', obj.file.url)
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


class WaterSourceInline(admin.TabularInline):
    model = WaterSource
    extra = 0


class RoadInline(admin.TabularInline):
    model = Road
    extra = 0


class MarketInline(admin.TabularInline):
    model = Market
    extra = 0


class SchoolInline(admin.TabularInline):
    model = School
    extra = 0


class HealthFacilityInline(admin.TabularInline):
    model = HealthFacility
    extra = 0


@admin.register(Plot)
class PlotAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "title",
        "owner_info",
        "location",
        "coordinates_display",
        "price_display",
        "area_with_unit",
        "effective_usable_area_display",
        "listing_type_display",
        "market_zone",
        "pricing_review_display",
        "market_status_display",
        "land_type_display",
        "verification_display",
        "has_all_documents",
        "is_registry_record",
        "is_hidden",
        "contact_requests_count",
        "created_at",
    )

    list_filter = (
        "county",
        "ownership_type",
        "encumbrances",
        "price_basis",
        "lease_basis",
        "listing_type",
        "market_zone",
        "market_status",
        "land_type",
        "is_hidden",
        "created_at",
    )

    search_fields = (
        "title",
        "location",
        "parcel_number",
        "agent__user__username",
        "landowner__user__username",
    )

    readonly_fields = (
        "agent",
        "landowner",
        "verification_info",
        "contact_requests_summary",
        "documents_summary",
        "created_at",
        "updated_at",
        "price_per_acre_display",
    )

    fieldsets = (
        (
            "Basic Information",
            {
                "fields": (
                    "title",
                    "agent",
                    "landowner",
                    "location",
                    "county",
                    "subcounty",
                    "nearest_town",
                    "area",
                    "area_unit",
                    "latitude",
                    "longitude",
                    "listing_type",
                    "market_zone",
                    "land_type",
                    "land_use_description",
                )
            },
        ),
        (
            "Ownership & Legal Status",
            {
                "fields": (
                    "parcel_number",
                    "registration_section",
                    "owner_full_name",
                    "owner_id_number",
                    "spousal_consent",
                    "ownership_type",
                    "tenure_details",
                    "encumbrances",
                    "encumbrance_details",
                )
            },
        ),
        ("Registry", {"fields": ("is_registry_record",), "classes": ("collapse",)}),
        (
            "Pricing (Sale)",
            {
                "fields": (
                    "sale_price",
                    "price_per_acre_display",
                    "price_basis",
                    "valuation_report",
                    "government_price_proof",
                    "price_notes",
                    "is_price_negotiable",
                    "price_review_required",
                    "pricing_override_reason",
                )
            },
        ),
        (
            "Pricing (Lease)",
            {"fields": ("lease_price_monthly", "lease_price_yearly", "lease_duration", "lease_terms", "lease_basis")},
        ),
        (
            "Availability",
            {
                "fields": (
                    "market_status",
                    "is_hidden",
                    "lease_start_date",
                    "lease_end_date",
                    "availability_notes",
                )
            },
        ),
        ("Agricultural Summary (Verified)", {"fields": ("soil_type", "ph_level", "crop_suitability"), "classes": ("collapse",)}),
        (
            "Infrastructure",
            {
                "fields": (
                    "has_water",
                    "water_source",
                    "has_electricity",
                    "electricity_meter",
                    "has_road_access",
                    "road_type",
                    "road_distance_km",
                    "has_buildings",
                    "building_description",
                    "fencing",
                ),
                "classes": ("collapse",),
            },
        ),
        ("Plot Documents", {"fields": ("title_deed", "survey_map", "spousal_consent_doc", "soil_report")}),
        (
            "Verification Documents",
            {"fields": ("official_search", "rates_clearance", "rent_clearance", "landowner_id_doc", "kra_pin"), "classes": ("collapse",)},
        ),
        ("Documents Summary", {"fields": ("documents_summary",), "classes": ("collapse",)}),
        ("Contact Requests", {"fields": ("contact_requests_summary",), "classes": ("collapse",)}),
        ("Verification", {"fields": ("verification_info",), "classes": ("collapse",)}),
        ("Timestamps", {"fields": ("created_at", "updated_at"), "classes": ("collapse",)}),
    )

    inlines = [
        VerificationDocumentInline,
        TitleSearchResultInline,
        WaterSourceInline,
        RoadInline,
        MarketInline,
        SchoolInline,
        HealthFacilityInline,
    ]
    actions = ["verify_selected", "reject_selected", "hide_selected", "show_selected", "export_as_csv"]
    ordering = ("-created_at",)

    def owner_info(self, obj):
        if obj.agent:
            verified = "✓" if obj.agent.verified else "✗"
            return format_html(
                '<span title="Agent"><strong>A:</strong> {}</span><br><small>verified: {}</small>',
                obj.agent.user.username,
                verified,
            )
        if obj.landowner:
            verified = "✓" if obj.landowner.verified else "✗"
            return format_html(
                '<span title="Landowner"><strong>L:</strong> {}</span><br><small>verified: {}</small>',
                obj.landowner.user.username,
                verified,
            )
        return "-"

    owner_info.short_description = "Owner"

    def area_with_unit(self, obj):
        return obj.area_display

    area_with_unit.short_description = "Area"

    def effective_usable_area_display(self, obj):
        return obj.effective_usable_area_display

    effective_usable_area_display.short_description = "Usable Area"

    def listing_type_display(self, obj):
        colors = {"sale": "green", "lease": "blue", "both": "purple"}
        color = colors.get(obj.listing_type, "gray")
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span>',
            color,
            obj.get_listing_type_display(),
        )

    listing_type_display.short_description = "Type"

    def land_type_display(self, obj):
        return obj.get_land_type_display()

    def market_status_display(self, obj):
        colors = {
            "available": "green",
            "reserved": "#9a6700",
            "leased": "#0a66c2",
            "sold": "#b42318",
        }
        color = colors.get(obj.market_status, "gray")
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span>',
            color,
            obj.market_status_label,
        )

    market_status_display.short_description = "Availability"

    land_type_display.short_description = "Land Type"

    def pricing_review_display(self, obj):
        badge = obj.pricing_review_badge
        colors = {
            "success": "#027a48",
            "warning": "#b54708",
            "danger": "#b42318",
            "secondary": "#475467",
        }
        return format_html(
            '<span style="color: {}; font-weight: 600;">{}</span>',
            colors.get(badge["tone"], "#475467"),
            badge["label"],
        )

    pricing_review_display.short_description = "Pricing Review"

    def price_display(self, obj):
        return f"KES {obj.price:,.0f}"

    price_display.short_description = "Price"
    price_display.admin_order_field = "price"

    def price_per_acre_display(self, obj):
        from decimal import Decimal

        if obj.price_per_acre:
            return f"KES {obj.price_per_acre:,.0f}"
        if obj.sale_price and obj.area and obj.area > 0:
            area = Decimal(str(obj.area))
            per_acre = obj.sale_price / area
            return f"KES {per_acre:,.0f} (calculated)"
        return "-"

    price_per_acre_display.short_description = "Price/Acre"

    def coordinates_display(self, obj):
        if obj.latitude is not None and obj.longitude is not None:
            return format_html('<span title="Open in map">{}°, {}°</span>', obj.latitude, obj.longitude)
        return format_html('<span style="color: #999;">—</span>')

    coordinates_display.short_description = "Coordinates"

    def documents_summary(self, obj):
        docs_status = []
        docs_status.append(("Title Deed", "✓" if obj.title_deed else "✗", "green" if obj.title_deed else "red"))
        docs_status.append(("Official Search", "✓" if obj.official_search else "✗", "green" if obj.official_search else "red"))
        docs_status.append(("Landowner ID", "✓" if obj.landowner_id_doc else "✗", "green" if obj.landowner_id_doc else "red"))
        docs_status.append(("KRA PIN", "✓" if obj.kra_pin else "✗", "green" if obj.kra_pin else "red"))
        docs_status.append(("Soil Report", "✓" if obj.soil_report else "✗", "green" if obj.soil_report else "orange"))

        html = '<div style="display: grid; grid-template-columns: repeat(2, 1fr); gap: 10px;">'
        for doc_name, status, color in docs_status:
            html += format_html(
                '<div style="padding: 8px; background: #f8f9fa; border-radius: 5px;">'
                "<strong>{}:</strong> <span style=\"color: {}; font-weight: bold;\">{}</span>"
                "</div>",
                doc_name,
                color,
                status,
            )
        html += "</div>"
        return format_html(html)

    documents_summary.short_description = "Documents Status"

    def contact_requests_count(self, obj):
        count = obj.contact_requests.count()
        if count > 0:
            return format_html(
                '<a href="/admin/listings/contactrequest/?plot__id__exact={}" style="color: {}; font-weight: bold;">{} ({})</a>',
                obj.id,
                "red" if count > 5 else "orange" if count > 2 else "green",
                count,
                "urgent" if count > 5 else "new",
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
                html += format_html(
                    """
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
                    color,
                    responded,
                    req.user.username,
                    req.user.email or "-",
                    req.plot.title if req.plot else "-",
                    (req.message or "")[:120],
                    req.request_type,
                    req.created_at.strftime("%Y-%m-%d %H:%M"),
                    req.id,
                )
            html += "</div>"
            return format_html(html)
        return "No contact requests"

    contact_requests_summary.short_description = "Recent Contact Requests"

    def get_verification(self, obj):
        try:
            return obj.verification.get()
        except Exception:
            return None

    def verification_display(self, obj):
        verification = self.get_verification(obj)
        if verification:
            status = verification.current_stage
            colors = {
                "pending": "orange",
                "api_verification_started": "blue",
                "title_search_completed": "blue",
                "owner_verified": "blue",
                "encumbrance_check": "blue",
                "physical_location_verified": "blue",
                "admin_review": "purple",
                "approved": "green",
                "rejected": "red",
            }
            color = colors.get(status, "gray")
            display_map = dict(VerificationStatus.STAGES)
            display_text = display_map.get(status, status.replace("_", " ").title())
            progress = verification.progress_percentage
            return format_html(
                '<span style="color: {}; font-weight: bold;">{}</span><br><small>Progress: {}%</small>',
                color,
                display_text,
                progress,
            )
        return format_html('<span style="color: gray;">No Status</span>')

    verification_display.short_description = "Status"

    def verification_info(self, obj):
        verification = self.get_verification(obj)
        if not verification:
            return "No verification status"
        stage_details = verification.stage_details or {}
        info = f"""
            <div style="background: #f8f9fa; padding: 15px; border-radius: 5px;">
                <strong>Status:</strong> {verification.get_current_stage_display()}<br>
                <strong>Progress:</strong> {verification.progress_percentage}%<br>
                <strong>Search Reference:</strong> {verification.search_reference or 'Not available'}<br>
                <strong>API Responses:</strong> {len(verification.api_responses)}<br>
                <strong>Submitted:</strong> {verification.document_uploaded_at or 'Not submitted'}<br>
                <strong>Admin Review:</strong> {verification.admin_review_at or 'Not yet'}<br>
                <strong>Approved:</strong> {verification.approved_at or 'Not yet'}<br>
                <strong>Details:</strong> {stage_details or 'No details'}
            </div>
            """
        return format_html(info)

    verification_info.short_description = "Verification Details"

    def verify_selected(self, request, queryset):
        from django.contrib.contenttypes.models import ContentType

        content_type = ContentType.objects.get_for_model(Plot)
        count = 0
        for plot in queryset:
            verification, created = VerificationStatus.objects.get_or_create(
                content_type=content_type,
                object_id=plot.id,
                defaults={
                    "current_stage": "approved",
                    "document_uploaded_at": timezone.now(),
                    "approved_at": timezone.now(),
                },
            )
            if not created:
                verification.current_stage = "approved"
                verification.approved_at = timezone.now()
            verification.stage_details = {
                "reviewed_by": request.user.username,
                "reviewed_at": timezone.now().isoformat(),
                "action": "verified",
            }
            verification.save()
            count += 1
        self.message_user(request, f"✅ {count} plot(s) verified.")

    verify_selected.short_description = "✅ Verify selected plots"

    def reject_selected(self, request, queryset):
        from django.contrib.contenttypes.models import ContentType

        content_type = ContentType.objects.get_for_model(Plot)
        count = 0
        for plot in queryset:
            verification, created = VerificationStatus.objects.get_or_create(
                content_type=content_type,
                object_id=plot.id,
                defaults={
                    "current_stage": "rejected",
                    "document_uploaded_at": timezone.now(),
                },
            )
            if not created:
                verification.current_stage = "rejected"
            verification.rejected_at = timezone.now()
            verification.stage_details = {
                "reviewed_by": request.user.username,
                "reviewed_at": timezone.now().isoformat(),
                "notes": "Rejected by admin",
                "action": "rejected",
            }
            verification.save()
            count += 1
        self.message_user(request, f"❌ {count} plot(s) rejected.")

    reject_selected.short_description = "❌ Reject selected plots"

    def hide_selected(self, request, queryset):
        count = queryset.update(is_hidden=True)
        self.message_user(request, f"{count} plot(s) hidden from the public marketplace.")

    hide_selected.short_description = "Hide selected plots"

    def show_selected(self, request, queryset):
        count = queryset.update(is_hidden=False)
        self.message_user(request, f"{count} plot(s) restored to the public marketplace.")

    show_selected.short_description = "Show selected plots"

    def export_as_csv(self, request, queryset):
        import csv

        from django.contrib.contenttypes.models import ContentType
        from django.http import HttpResponse

        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="plots_export.csv"'
        writer = csv.writer(response)
        writer.writerow(
            [
                "ID",
                "Title",
                "Location",
                "Price",
                "Area",
                "Listing Type",
                "Land Type",
                "Soil Type",
                "Crop Suitability",
                "Owner Type",
                "Owner",
                "Status",
                "Progress %",
                "Coordinates",
                "Created At",
            ]
        )

        for plot in queryset:
            owner_type = "Agent" if plot.agent else "Landowner"
            owner_name = (
                plot.agent.user.username
                if plot.agent
                else (plot.landowner.user.username if plot.landowner else "N/A")
            )
            verification = self.get_verification(plot)
            if verification:
                status = verification.current_stage
                progress = verification.progress_percentage
                status_display = dict(VerificationStatus.STAGES).get(status, status)
            else:
                status_display = "Pending"
                progress = 0

            writer.writerow(
                [
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
                    f"{plot.latitude},{plot.longitude}"
                    if (plot.latitude and plot.longitude)
                    else "",
                    plot.created_at.strftime("%Y-%m-%d"),
                ]
            )
        return response

    export_as_csv.short_description = "📊 Export selected to CSV"

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        queryset = queryset.select_related("agent__user", "landowner__user").prefetch_related("contact_requests")
        return queryset


@admin.register(ContactRequest)
class ContactRequestAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "plot_title", "request_type", "responded", "created_at")
    list_filter = ("request_type", "responded", "created_at")
    search_fields = ("user__username", "plot__title", "message")

    def plot_title(self, obj):
        return obj.plot.title if obj.plot else "-"

    plot_title.short_description = "Plot"

    def has_add_permission(self, request):
        return False


@admin.register(UserInterest)
class UserInterestAdmin(admin.ModelAdmin):
    list_display = ("user", "plot_title", "status", "created_at")
    list_filter = ("status", "created_at")
    search_fields = ("user__username", "plot__title")

    def plot_title(self, obj):
        return obj.plot.title

    plot_title.short_description = "Plot"


@admin.register(PriceComparable)
class PriceComparableAdmin(admin.ModelAdmin):
    list_display = ("location", "area_acres", "sale_price", "price_per_acre", "soil_type", "sale_date", "verified")
    list_filter = ("verified",)
    search_fields = ("location", "soil_type")


@admin.register(PricingSuggestion)
class PricingSuggestionAdmin(admin.ModelAdmin):
    list_display = ("plot", "suggested_price", "price_range_min", "price_range_max", "comparable_plots_used", "generated_at")
    list_filter = ("generated_at",)
    search_fields = ("plot__title",)


@admin.register(MarketPriceBand)
class MarketPriceBandAdmin(admin.ModelAdmin):
    list_display = (
        "county",
        "subcounty",
        "market_zone",
        "land_type",
        "listing_type",
        "area_unit",
        "min_price_per_unit",
        "max_price_per_unit",
        "effective_from",
        "is_active",
    )
    list_filter = ("county", "market_zone", "land_type", "listing_type", "area_unit", "is_active")
    search_fields = ("county", "subcounty", "source")
    ordering = ("county", "subcounty", "market_zone", "land_type", "listing_type")
    actions = ["seed_default_bands", "seed_registry_bands"]

    def seed_default_bands(self, request, queryset):
        call_command("seed_price_bands")
        self.message_user(request, "Seeded default MarketPriceBand entries.")

    seed_default_bands.short_description = "Seed default price bands"

    def seed_registry_bands(self, request, queryset):
        call_command("seed_registry_price_bands")
        self.message_user(request, "Seeded registry-derived price bands.")

    seed_registry_bands.short_description = "Seed registry price bands"


@admin.register(ComparableSale)
class ComparableSaleAdmin(admin.ModelAdmin):
    list_display = ("plot", "county", "price_per_acre", "source")
    list_filter = ("county",)
    search_fields = ("plot__title", "county", "source")


@admin.register(PlotImage)
class PlotImageAdmin(admin.ModelAdmin):
    list_display = ("plot", "uploaded_by", "uploaded_at")
    list_filter = ("uploaded_at",)
    search_fields = ("plot__title", "uploaded_by__username")


@admin.register(SitePage)
class SitePageAdmin(admin.ModelAdmin):
    list_display = ("slug", "title", "updated_at")
    search_fields = ("slug", "title")

@admin.register(WaterSource)
class WaterSourceAdmin(SafeMissingTableAdmin):
    list_display = ("name", "plot", "description")
    search_fields = ("name", "plot__title")
    list_filter = ("plot__county",)

@admin.register(Road)
class RoadAdmin(SafeMissingTableAdmin):
    list_display = ("name", "plot", "road_type")
    search_fields = ("name", "plot__title")
    list_filter = ("plot__county",)

@admin.register(Market)
class MarketAdmin(SafeMissingTableAdmin):
    list_display = ("name", "plot", "description")
    search_fields = ("name", "plot__title")
    list_filter = ("plot__county",)

@admin.register(School)
class SchoolAdmin(SafeMissingTableAdmin):
    list_display = ("name", "plot", "level")
    search_fields = ("name", "plot__title")
    list_filter = ("plot__county",)

@admin.register(HealthFacility)
class HealthFacilityAdmin(SafeMissingTableAdmin):
    list_display = ("name", "plot", "facility_type")
    search_fields = ("name", "plot__title")
    list_filter = ("plot__county",)

@admin.register(LandTransferAgreement)
class LandTransferAgreementAdmin(SafeMissingTableAdmin):
    list_display = ("plot", "seller", "buyer", "agreement_date")
    list_filter = ("agreement_date",)
    search_fields = ("plot__title", "seller__user__username", "buyer__user__username")

@admin.register(FraudReport)
class FraudReportAdmin(SafeMissingTableAdmin):
    list_display = ("plot", "reporter", "status", "plot_hidden", "created_at")
    list_filter = ("status", "created_at")
    search_fields = ("plot__title", "reporter__username", "reason")
    actions = ("mark_reviewed_and_hide_plot", "dismiss_reports_and_restore_plot")

    def plot_hidden(self, obj):
        return obj.plot.is_hidden

    plot_hidden.boolean = True
    plot_hidden.short_description = "Plot Hidden"

    def mark_reviewed_and_hide_plot(self, request, queryset):
        now = timezone.now()
        updated = 0
        hidden = 0
        for report in queryset.select_related("plot"):
            report.status = "reviewed"
            report.reviewed_at = now
            report.save(update_fields=["status", "reviewed_at"])
            updated += 1
            if not report.plot.is_hidden:
                report.plot.is_hidden = True
                report.plot.save(update_fields=["is_hidden", "updated_at"])
                hidden += 1
        self.message_user(request, f"{updated} report(s) marked reviewed. {hidden} linked plot(s) hidden.")

    mark_reviewed_and_hide_plot.short_description = "Mark reviewed and hide linked plots"

    def dismiss_reports_and_restore_plot(self, request, queryset):
        now = timezone.now()
        updated = 0
        restored = 0
        for report in queryset.select_related("plot"):
            report.status = "dismissed"
            report.reviewed_at = now
            report.save(update_fields=["status", "reviewed_at"])
            updated += 1
            if report.plot.is_hidden and not report.plot.fraud_reports.exclude(pk=report.pk).filter(status__in=["pending", "reviewed"]).exists():
                report.plot.is_hidden = False
                report.plot.save(update_fields=["is_hidden", "updated_at"])
                restored += 1
        self.message_user(request, f"{updated} report(s) dismissed. {restored} linked plot(s) restored.")

    dismiss_reports_and_restore_plot.short_description = "Dismiss reports and restore plots"


@admin.register(UserPlotView)
class UserPlotViewAdmin(SafeMissingTableAdmin):
    list_display = ("user", "plot", "view_count", "viewed_at")
    list_filter = ("viewed_at",)
    search_fields = ("user__username", "plot__title")
