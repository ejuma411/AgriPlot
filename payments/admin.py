from django.contrib import admin
from django.utils.html import format_html, format_html_join

from .models import (
    PaymentClosingStep,
    PaymentDispute,
    PaymentEvent,
    PaymentMilestone,
    PaymentRequest,
)


class PaymentMilestoneInline(admin.TabularInline):
    model = PaymentMilestone
    extra = 0


class PaymentEventInline(admin.TabularInline):
    model = PaymentEvent
    extra = 0
    readonly_fields = ("event_type", "actor", "message", "created_at")
    can_delete = False


class PaymentClosingStepInline(admin.TabularInline):
    model = PaymentClosingStep
    extra = 0
    readonly_fields = (
        "sequence",
        "display_title_readonly",
        "code",
        "responsible_party_display",
        "display_document_readonly",
        "completed_at",
        "completed_by",
        "created_at",
        "updated_at",
    )
    fields = (
        "sequence",
        "display_title_readonly",
        "code",
        "status",
        "responsible_party_display",
        "document",
        "display_document_readonly",
        "notes",
        "completed_at",
        "completed_by",
    )

    def display_title_readonly(self, obj):
        return obj.display_title

    display_title_readonly.short_description = "Stage"

    def responsible_party_display(self, obj):
        return obj.responsible_party_label

    responsible_party_display.short_description = "Responsible party"

    def display_document_readonly(self, obj):
        return obj.display_document_name or "-"

    display_document_readonly.short_description = "Expected evidence"


@admin.register(PaymentRequest)
class PaymentRequestAdmin(admin.ModelAdmin):
    list_display = (
        "internal_reference",
        "title",
        "transaction_type",
        "category",
        "amount",
        "method",
        "status",
        "current_tracker_step",
        "closing_progress",
        "buyer",
        "seller",
        "created_at",
    )
    list_filter = ("status", "method", "category", "escrow_enabled", "created_at")
    search_fields = ("internal_reference", "title", "provider_reference", "phone_number")
    raw_id_fields = ("buyer", "seller", "plot")
    readonly_fields = ("internal_reference", "current_tracker_step", "closing_progress", "process_overview")
    fieldsets = (
        (
            "Payment",
            {
                "fields": (
                    "internal_reference",
                    "plot",
                    "buyer",
                    "seller",
                    "transaction_type",
                    "category",
                    "amount",
                    "method",
                    "status",
                )
            },
        ),
        (
            "Tracker Overview",
            {
                "fields": (
                    "current_tracker_step",
                    "closing_progress",
                    "process_overview",
                )
            },
        ),
    )
    inlines = [PaymentClosingStepInline, PaymentMilestoneInline, PaymentEventInline]

    def current_tracker_step(self, obj):
        step = obj.next_closing_step
        if not step:
            return "All stages completed"
        return f"{step.display_title} ({step.responsible_party_label})"

    current_tracker_step.short_description = "Current stage"

    def closing_progress(self, obj):
        return f"{obj.closing_progress_value}%"

    closing_progress.short_description = "Tracker progress"

    def process_overview(self, obj):
        return format_html_join(
            "",
            "<div style='margin-bottom:6px;'><strong>{}</strong> — {} <span style='color:#667085;'>({})</span></div>",
            (
                (
                    step["sequence"],
                    f"{step['title']}: {step['state_label']}",
                    step["caption"],
                )
                for step in obj.dashboard_process_steps
            ),
        ) or format_html("<span>-</span>")

    process_overview.short_description = "Buyer-facing stage flow"


@admin.register(PaymentDispute)
class PaymentDisputeAdmin(admin.ModelAdmin):
    list_display = ("payment", "reason", "status", "opened_by", "created_at")
    list_filter = ("reason", "status", "created_at")
    search_fields = ("payment__internal_reference", "details", "resolution_notes")
