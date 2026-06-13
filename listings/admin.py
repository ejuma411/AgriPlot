from django.contrib import admin
from django.utils import timezone
from .models import (
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

admin.site.site_header = "AgriPlot Administration"
admin.site.site_title = "AgriPlot Admin"
admin.site.index_title = "System Management"

@admin.register(Plot)
class PlotAdmin(admin.ModelAdmin):
    list_display = ("id", "title", "location", "listing_type", "market_status", "is_hidden", "created_at")
    list_filter = ("listing_type", "market_status", "is_hidden")
    search_fields = ("title", "location", "parcel_number")
    readonly_fields = ("created_at", "updated_at")

@admin.register(ContactRequest)
class ContactRequestAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "plot", "request_type", "responded", "created_at")
    list_filter = ("request_type", "responded")
    search_fields = ("user__username", "plot__title")

@admin.register(UserInterest)
class UserInterestAdmin(admin.ModelAdmin):
    list_display = ("user", "plot", "status", "created_at")
    list_filter = ("status",)
    search_fields = ("user__username", "plot__title")

@admin.register(PriceComparable)
class PriceComparableAdmin(admin.ModelAdmin):
    list_display = ("location", "area_acres", "sale_price", "price_per_acre", "verified")
    list_filter = ("verified",)
    search_fields = ("location",)

@admin.register(PricingSuggestion)
class PricingSuggestionAdmin(admin.ModelAdmin):
    list_display = ("plot", "suggested_price", "generated_at")
    search_fields = ("plot__title",)

@admin.register(MarketPriceBand)
class MarketPriceBandAdmin(admin.ModelAdmin):
    list_display = ("county", "market_zone", "land_type", "is_active")
    list_filter = ("county", "is_active")

@admin.register(ComparableSale)
class ComparableSaleAdmin(admin.ModelAdmin):
    list_display = ("plot", "county", "price_per_acre")
    search_fields = ("plot__title", "county")

@admin.register(PlotImage)
class PlotImageAdmin(admin.ModelAdmin):
    list_display = ("plot", "uploaded_by", "uploaded_at")

@admin.register(SitePage)
class SitePageAdmin(admin.ModelAdmin):
    list_display = ("slug", "title")

@admin.register(WaterSource)
class WaterSourceAdmin(admin.ModelAdmin):
    list_display = ("name", "plot")

@admin.register(Road)
class RoadAdmin(admin.ModelAdmin):
    list_display = ("name", "plot", "road_type")

@admin.register(Market)
class MarketAdmin(admin.ModelAdmin):
    list_display = ("name", "plot")

@admin.register(School)
class SchoolAdmin(admin.ModelAdmin):
    list_display = ("name", "plot")

@admin.register(HealthFacility)
class HealthFacilityAdmin(admin.ModelAdmin):
    list_display = ("name", "plot")

@admin.register(LandTransferAgreement)
class LandTransferAgreementAdmin(admin.ModelAdmin):
    list_display = ("plot", "seller", "buyer", "agreement_date")

@admin.register(FraudReport)
class FraudReportAdmin(admin.ModelAdmin):
    list_display = ("plot", "reporter", "status", "created_at")
    list_filter = ("status",)

@admin.register(UserPlotView)
class UserPlotViewAdmin(admin.ModelAdmin):
    list_display = ("plot", "user", "view_count", "viewed_at")
