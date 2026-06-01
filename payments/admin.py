from django.contrib import admin
from django.contrib import messages
from django.utils.html import format_html, format_html_join
from django.urls import reverse
from django.utils import timezone
from decimal import Decimal

from .models import (
    BankBeneficiary,
    BankTransferRequest,
    PaymentDisbursement,
    Wallet,
    WalletTransaction,
    WalletDepositRequest,
    WalletWithdrawalRequest,
)
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
    actions = ["mark_paid", "move_to_escrow", "release_funds", "refund"]

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

    def mark_paid(self, request, queryset):
        for payment in queryset:
            if payment.status == PaymentRequest.Status.PENDING:
                payment.apply_transition("mark_paid", actor=request.user)
        self.message_user(request, f"{queryset.count()} payment(s) marked as paid.")
    mark_paid.short_description = "Mark selected payments as paid"

    def move_to_escrow(self, request, queryset):
        for payment in queryset:
            if payment.status == PaymentRequest.Status.PAID:
                payment.apply_transition("move_escrow", actor=request.user)
        self.message_user(request, f"{queryset.count()} payment(s) moved to escrow.")
    move_to_escrow.short_description = "Move selected payments to escrow"

    def release_funds(self, request, queryset):
        for payment in queryset:
            if payment.status in [PaymentRequest.Status.IN_ESCROW, PaymentRequest.Status.PARTIALLY_RELEASED]:
                payment.apply_transition("release", actor=request.user)
        self.message_user(request, f"{queryset.count()} payment(s) released.")
    release_funds.short_description = "Release funds for selected payments"

    def refund(self, request, queryset):
        for payment in queryset:
            if payment.status in [PaymentRequest.Status.PENDING, PaymentRequest.Status.PAID, PaymentRequest.Status.IN_ESCROW]:
                payment.apply_transition("refund", actor=request.user)
        self.message_user(request, f"{queryset.count()} payment(s) refunded.")
    refund.short_description = "Refund selected payments"


@admin.register(PaymentDispute)
class PaymentDisputeAdmin(admin.ModelAdmin):
    list_display = ("payment", "reason", "status", "opened_by", "created_at")
    list_filter = ("reason", "status", "created_at")
    search_fields = ("payment__internal_reference", "details", "resolution_notes")
    actions = ["mark_under_review", "mark_resolved", "mark_rejected"]

    def mark_under_review(self, request, queryset):
        queryset.update(status=PaymentDispute.Status.UNDER_REVIEW)
        self.message_user(request, f"{queryset.count()} dispute(s) marked as under review.")
    mark_under_review.short_description = "Mark as Under Review"

    def mark_resolved(self, request, queryset):
        queryset.update(status=PaymentDispute.Status.RESOLVED, resolved_at=timezone.now(), resolved_by=request.user)
        self.message_user(request, f"{queryset.count()} dispute(s) marked as resolved.")
    mark_resolved.short_description = "Mark as Resolved"

    def mark_rejected(self, request, queryset):
        queryset.update(status=PaymentDispute.Status.REJECTED)
        self.message_user(request, f"{queryset.count()} dispute(s) marked as rejected.")
    mark_rejected.short_description = "Mark as Rejected"


# ============================================================
# FIXED WALLET ADMIN
# ============================================================

@admin.register(Wallet)
class WalletAdmin(admin.ModelAdmin):
    list_display = [
        'user_link', 
        'account_number', 
        'balance_display', 
        'available_balance_display',
        'is_active', 
        'has_pin', 
        'created_at'
    ]
    list_filter = ['is_active', 'created_at']
    search_fields = ['user__username', 'user__email', 'account_number']
    readonly_fields = ['account_number', 'balance_display', 'available_balance_display', 'created_at', 'updated_at']
    list_select_related = ['user']
    
    def user_link(self, obj):
        url = reverse("admin:auth_user_change", args=[obj.user.id])
        return format_html('<a href="{}">{}</a>', url, obj.user.username)
    user_link.short_description = "User"
    
    def balance_display(self, obj):
        return format_html(
            '<span style="font-weight: bold; color: {};">KES {}</span>',
            '#2E7D32' if obj.balance > 0 else '#757575',
            f'{obj.balance:,.2f}'
        )
    balance_display.short_description = "Balance"
    
    def available_balance_display(self, obj):
        return format_html(
            '<span style="color: {};">KES {}</span>',
            '#2E7D32' if obj.available_balance > 0 else '#757575',
            f'{obj.available_balance:,.2f}'
        )
    available_balance_display.short_description = "Available Balance"
    
    def has_pin(self, obj):
        return format_html(
            '<span style="color: {};">{}</span>',
            '#2E7D32' if obj.pin_hash else '#D32F2F',
            '✓' if obj.pin_hash else '✗'
        )
    has_pin.short_description = "PIN Set"
    
    fieldsets = (
        ("Wallet Information", {
            'fields': ('user', 'account_number', 'is_active')
        }),
        ("Security", {
            'fields': ('pin_hash', 'failed_pin_attempts', 'locked_until'),
            'classes': ('collapse',)
        }),
        ("Balance Information (Calculated)", {
            'fields': ('balance_display', 'available_balance_display'),
            'description': 'Balances are calculated from immutable transaction logs.'
        }),
        ("Timestamps", {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


@admin.register(WalletTransaction)
class WalletTransactionAdmin(admin.ModelAdmin):
    list_display = [
        'reference', 
        'wallet_link', 
        'amount_display', 
        'type_badge', 
        'status_badge', 
        'channel', 
        'created_at'
    ]
    list_filter = ['type', 'status', 'channel', 'created_at']
    search_fields = [
        'reference', 
        'wallet__user__username',
        'wallet__account_number'
    ]
    readonly_fields = [
        'reference', 'wallet', 'amount', 'type', 'channel', 'description', 
        'metadata', 'created_at', 'completed_at', 'status'
    ]
    list_select_related = ['wallet__user']
    date_hierarchy = 'created_at'
    
    def wallet_link(self, obj):
        url = reverse("admin:payments_wallet_change", args=[obj.wallet.id])
        return format_html('<a href="{}">{}</a>', url, obj.wallet.account_number)
    wallet_link.short_description = "Wallet"
    
    def amount_display(self, obj):
        color = '#2E7D32' if obj.type == 'CREDIT' else '#D32F2F'
        sign = '+' if obj.type == 'CREDIT' else '-'
        return format_html('<span style="color: {}; font-weight: bold;">{} KES {}</span>', 
                          color, sign, f'{obj.amount:,.2f}')
    amount_display.short_description = "Amount"
    
    def type_badge(self, obj):
        badge_class = 'success' if obj.type == 'CREDIT' else 'warning'
        type_display = 'Credit (Deposit)' if obj.type == 'CREDIT' else 'Debit (Withdrawal)'
        return format_html('<span class="badge bg-{}">{}</span>', 
                          badge_class, type_display)
    type_badge.short_description = "Type"
    
    def status_badge(self, obj):
        color_map = {
            'SUCCESS': 'success',
            'PENDING': 'warning',
            'FAILED': 'danger',
            'PROCESSING': 'info',
            'FROZEN': 'secondary',
            'CANCELLED': 'dark',
        }
        badge_class = color_map.get(obj.status, 'secondary')
        return format_html('<span class="badge bg-{}">{}</span>', 
                          badge_class, obj.status)
    status_badge.short_description = "Status"
    
    fieldsets = (
        ("Transaction Details", {
            'fields': ('reference', 'wallet', 'amount', 'type', 'status', 'channel')
        }),
        ("Payment Information", {
            'fields': ('description', 'metadata'),
            'classes': ('collapse',)
        }),
        ("Timestamps", {
            'fields': ('created_at', 'completed_at'),
            'classes': ('collapse',)
        }),
    )
    
    def has_add_permission(self, request):
        """Prevent manual creation of transactions"""
        return False
    
    def has_delete_permission(self, request, obj=None):
        """Prevent deletion of successful transactions"""
        if obj and obj.status == 'SUCCESS':
            return False
        return super().has_delete_permission(request, obj)


@admin.register(WalletDepositRequest)
class WalletDepositRequestAdmin(admin.ModelAdmin):
    list_display = [
        'id', 
        'user_link', 
        'amount_display', 
        'status_badge', 
        'payment_method', 
        'created_at'
    ]
    list_filter = ['status', 'payment_method', 'created_at']
    search_fields = [
        'user__username', 
        'user__email', 
        'reference', 
    ]
    readonly_fields = [
        'reference', 'user', 'amount', 'payment_method', 'phone_number',
        'status', 'created_at', 'completed_at'
    ]
    list_select_related = ['user']
    date_hierarchy = 'created_at'
    
    def user_link(self, obj):
        url = reverse("admin:auth_user_change", args=[obj.user.id])
        return format_html('<a href="{}">{}</a>', url, obj.user.username)
    user_link.short_description = "User"
    
    def amount_display(self, obj):
        return format_html('<span style="font-weight: bold;">KES {}</span>', f'{obj.amount:,.2f}')
    amount_display.short_description = "Amount"
    
    def status_badge(self, obj):
        color_map = {
            'pending': 'warning',
            'processing': 'info',
            'completed': 'success',
            'failed': 'danger',
            'expired': 'secondary',
        }
        badge_class = color_map.get(obj.status, 'secondary')
        return format_html('<span class="badge bg-{}">{}</span>', badge_class, obj.status.title())
    status_badge.short_description = "Status"
    
    actions = ['mark_completed', 'mark_failed']
    
    def mark_completed(self, request, queryset):
        count = queryset.filter(status__in=['pending', 'processing']).update(status='completed', completed_at=timezone.now())
        self.message_user(request, f"{count} deposit(s) marked as completed.")
    mark_completed.short_description = "Mark selected deposits as completed"
    
    def mark_failed(self, request, queryset):
        count = queryset.filter(status__in=['pending', 'processing']).update(status='failed')
        self.message_user(request, f"{count} deposit(s) marked as failed.")
    mark_failed.short_description = "Mark selected deposits as failed"


@admin.register(WalletWithdrawalRequest)
class WalletWithdrawalRequestAdmin(admin.ModelAdmin):
    list_display = [
        'id', 
        'user_link', 
        'amount_display', 
        'status_badge', 
        'payment_method', 
        'requires_approval_badge', 
        'created_at'
    ]
    list_filter = ['status', 'payment_method', 'created_at']
    search_fields = [
        'user__username', 
        'user__email', 
        'reference', 
        'phone_number',
    ]
    readonly_fields = [
        'reference', 'user', 'amount', 'payment_method', 'phone_number',
        'bank_name', 'bank_account_name', 'bank_account_number', 'bank_branch',
        'status', 'rejection_reason', 'created_at', 'completed_at'
    ]
    list_select_related = ['user']
    date_hierarchy = 'created_at'
    actions = ['approve_withdrawals', 'reject_withdrawals']
    
    def user_link(self, obj):
        url = reverse("admin:auth_user_change", args=[obj.user.id])
        return format_html('<a href="{}">{}</a>', url, obj.user.username)
    user_link.short_description = "User"
    
    def amount_display(self, obj):
        return format_html('<span style="font-weight: bold;">KES {}</span>', f'{obj.amount:,.2f}')
    amount_display.short_description = "Amount"
    
    def status_badge(self, obj):
        color_map = {
            'pending': 'warning',
            'approved': 'info',
            'processing': 'info',
            'completed': 'success',
            'failed': 'danger',
            'rejected': 'danger',
            'cancelled': 'secondary',
        }
        badge_class = color_map.get(obj.status, 'secondary')
        return format_html('<span class="badge bg-{}">{}</span>', badge_class, obj.status.title())
    status_badge.short_description = "Status"
    
    def requires_approval_badge(self, obj):
        if obj.amount > Decimal('100000.00'):
            return format_html('<span class="badge bg-warning">Requires Approval</span>')
        return format_html('<span class="badge bg-success">Auto-approved</span>')
    requires_approval_badge.short_description = "Approval"
    
    def approve_withdrawals(self, request, queryset):
        from .wallet_service import WalletService
        count = 0
        for withdrawal in queryset.filter(status='pending'):
            try:
                WalletService.approve_withdrawal(withdrawal.reference, request.user)
                count += 1
            except Exception as e:
                self.message_user(request, f"Error approving {withdrawal.reference}: {e}", level='ERROR')
        self.message_user(request, f"{count} withdrawal(s) approved.")
    approve_withdrawals.short_description = "Approve selected withdrawals"
    
    def reject_withdrawals(self, request, queryset):
        from .wallet_service import WalletService
        count = 0
        for withdrawal in queryset.filter(status='pending'):
            try:
                WalletService.reject_withdrawal(withdrawal.reference, request.user, "Rejected by admin")
                count += 1
            except Exception as e:
                self.message_user(request, f"Error rejecting {withdrawal.reference}: {e}", level='ERROR')
        self.message_user(request, f"{count} withdrawal(s) rejected.")
    reject_withdrawals.short_description = "Reject selected withdrawals"
    
    fieldsets = (
        ("Withdrawal Request", {
            'fields': ('reference', 'user', 'amount', 'payment_method', 'status')
        }),
        ("Mobile Money Details", {
            'fields': ('phone_number',),
            'classes': ('collapse',)
        }),
        ("Bank Transfer Details", {
            'fields': ('bank_name', 'bank_account_name', 'bank_account_number', 'bank_branch'),
            'classes': ('collapse',)
        }),
        ("Approval & Processing", {
            'fields': ('rejection_reason',),
            'classes': ('collapse',)
        }),
        ("Timestamps", {
            'fields': ('created_at', 'completed_at'),
            'classes': ('collapse',)
        }),
    ) 


@admin.register(BankBeneficiary)
class BankBeneficiaryAdmin(admin.ModelAdmin):
    list_display = [
        "legal_name",
        "bank_name",
        "account_name",
        "account_number",
        "currency",
        "is_verified",
        "user",
        "created_at",
    ]
    list_filter = ["is_verified", "bank_name", "currency", "created_at"]
    search_fields = ["legal_name", "bank_name", "account_name", "account_number", "user__username"]
    readonly_fields = ["created_at", "updated_at"]
    raw_id_fields = ["user"]
    fieldsets = (
        (
            "Beneficiary",
            {
                "fields": (
                    "user",
                    "legal_name",
                    "bank_name",
                    "bank_code",
                    "account_name",
                    "account_number",
                    "branch_name",
                    "currency",
                )
            },
        ),
        (
            "Verification",
            {
                "fields": ("is_verified", "verification_reference", "metadata"),
                "classes": ("collapse",),
            },
        ),
        (
            "Timestamps",
            {
                "fields": ("created_at", "updated_at"),
                "classes": ("collapse",),
            },
        ),
    )


@admin.register(BankTransferRequest)
class BankTransferRequestAdmin(admin.ModelAdmin):
    list_display = [
        "reference",
        "payment",
        "beneficiary_name",
        "bank_name",
        "rail",
        "amount",
        "status",
        "provider",
        "created_at",
    ]
    list_filter = ["status", "rail", "provider", "created_at"]
    search_fields = [
        "reference",
        "provider_reference",
        "payment__internal_reference",
        "beneficiary_name",
        "account_number",
    ]
    raw_id_fields = ["payment", "disbursement", "beneficiary"]
    readonly_fields = [
        "reference",
        "payment",
        "disbursement",
        "beneficiary",
        "created_at",
        "updated_at",
        "submitted_at",
        "completed_at",
        "reconciled_at",
    ]
    fieldsets = (
        (
            "Transfer",
            {
                "fields": (
                    "reference",
                    "payment",
                    "disbursement",
                    "beneficiary",
                    "beneficiary_name",
                    "amount",
                    "currency",
                    "rail",
                    "provider",
                    "status",
                )
            },
        ),
        (
            "Destination",
            {
                "fields": ("bank_name", "bank_code", "account_name", "account_number"),
            },
        ),
        (
            "Provider Data",
            {
                "fields": (
                    "idempotency_key",
                    "provider_reference",
                    "request_payload",
                    "provider_response",
                    "callback_payload",
                    "failure_reason",
                ),
                "classes": ("collapse",),
            },
        ),
        (
            "Timestamps",
            {
                "fields": ("submitted_at", "completed_at", "reconciled_at", "created_at", "updated_at"),
                "classes": ("collapse",),
            },
        ),
    )


@admin.register(PaymentDisbursement)
class PaymentDisbursementAdmin(admin.ModelAdmin):
    list_display = [
        "payment",
        "code",
        "recipient_name",
        "recipient_role",
        "amount",
        "status",
        "bank_transfer_state",
        "created_at",
    ]
    list_filter = ["status", "recipient_role", "stage_code", "created_at"]
    search_fields = ["payment__internal_reference", "recipient_name", "code"]
    raw_id_fields = ["payment", "recipient_user"]
    readonly_fields = [
        "payment",
        "code",
        "recipient_role",
        "recipient_user",
        "recipient_name",
        "paid_by_side",
        "amount",
        "release_trigger",
        "stage_code",
        "notes",
        "released_at",
        "metadata",
        "created_at",
        "updated_at",
        "bank_transfer_state",
    ]
    actions = ["queue_bank_payouts"]

    def bank_transfer_state(self, obj):
        transfer = getattr(obj, "bank_transfer_request", None)
        if not transfer:
            return "Not queued"
        return f"{transfer.get_status_display()} ({transfer.get_rail_display()})"
    bank_transfer_state.short_description = "Bank transfer"

    def queue_bank_payouts(self, request, queryset):
        from .bank_transfer_service import BankTransferService

        count = 0
        skipped = []
        for disbursement in queryset.filter(
            status__in=[PaymentDisbursement.Status.RELEASED, PaymentDisbursement.Status.READY]
        ):
            beneficiary = (
                BankBeneficiary.objects.filter(user=disbursement.recipient_user, is_verified=True)
                .order_by("-updated_at")
                .first()
            )
            if not beneficiary:
                skipped.append(disbursement.code)
                continue
            try:
                BankTransferService.queue_disbursement(
                    disbursement,
                    beneficiary=beneficiary,
                    created_by=request.user,
                )
                count += 1
            except Exception as exc:
                self.message_user(
                    request,
                    f"Could not queue {disbursement.code} for {disbursement.payment.internal_reference}: {exc}",
                    level=messages.ERROR,
                )
        message = f"{count} payout(s) queued for bank transfer."
        if skipped:
            message += f" Skipped {len(skipped)} disbursement(s) without a verified beneficiary."
        self.message_user(request, message)
    queue_bank_payouts.short_description = "Queue selected payouts for bank transfer"
