from django.contrib import admin
from .models import MockLandRegistry, RegistryMismatchAttempt


@admin.register(MockLandRegistry)
class MockLandRegistryAdmin(admin.ModelAdmin):
    list_display = (
        "parcel_number",
        "registered_owner_name",
        "owner_id_number",
        "county",
        "subcounty",
        "land_type",
        "acreage_ha",
        "is_charged",
        "has_caution",
    )
    search_fields = ("parcel_number", "registered_owner_name", "owner_id_number", "owner_kra_pin")
    list_filter = ("land_type", "is_charged", "has_caution")


@admin.register(RegistryMismatchAttempt)
class RegistryMismatchAttemptAdmin(admin.ModelAdmin):
    list_display = ("parcel_number", "provided_owner_name", "provided_owner_id", "user", "reason", "created_at")
    search_fields = ("parcel_number", "provided_owner_name", "provided_owner_id")
    list_filter = ("created_at",)
