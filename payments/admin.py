from django.contrib import admin

from .models import PaymentDispute, PaymentEvent, PaymentMilestone, PaymentRequest


class PaymentMilestoneInline(admin.TabularInline):
    model = PaymentMilestone
    extra = 0


class PaymentEventInline(admin.TabularInline):
    model = PaymentEvent
    extra = 0
    readonly_fields = ("event_type", "actor", "message", "created_at")
    can_delete = False


@admin.register(PaymentRequest)
class PaymentRequestAdmin(admin.ModelAdmin):
    list_display = (
        "internal_reference",
        "title",
        "amount",
        "method",
        "status",
        "buyer",
        "seller",
        "created_at",
    )
    list_filter = ("status", "method", "category", "escrow_enabled", "created_at")
    search_fields = ("internal_reference", "title", "provider_reference", "phone_number")
    raw_id_fields = ("buyer", "seller", "plot")
    inlines = [PaymentMilestoneInline, PaymentEventInline]


@admin.register(PaymentDispute)
class PaymentDisputeAdmin(admin.ModelAdmin):
    list_display = ("payment", "reason", "status", "opened_by", "created_at")
    list_filter = ("reason", "status", "created_at")
    search_fields = ("payment__internal_reference", "details", "resolution_notes")
