from datetime import timezone

from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html
from django.db.models import Count, Q
from .models import (
    Wallet,
    WalletTransaction,
    WalletDepositRequest,
    WalletWithdrawalRequest,
    PaymentRequest,
    PaymentClosingStep,
    PaymentDisbursement,
    PaymentCertificate,
    PaymentMilestone,
    PaymentDispute,
    PaymentEvent,
    BankBeneficiary,
    BankTransferRequest,
    LeaseWaitlistEntry,
    WalletDisbursement,
)


@admin.register(PaymentRequest)
class PaymentRequestAdmin(admin.ModelAdmin):
    list_display = ("internal_reference", "title", "amount", "status", "created_at")
    list_filter = ("status", "method", "category")
    search_fields = ("internal_reference", "title", "buyer__email", "seller__email")
    raw_id_fields = ("buyer", "seller", "plot")
    readonly_fields = ("internal_reference", "created_at", "updated_at")
    
    fieldsets = (
        ("Basic Information", {
            "fields": ("internal_reference", "title", "description", "amount", "status")
        }),
        ("Parties", {
            "fields": ("buyer", "seller", "plot")
        }),
    )
    
    
@admin.register(PaymentClosingStep)
class PaymentClosingStepAdmin(admin.ModelAdmin):
    list_display = ("payment_ref", "title", "code", "status_badge", "completed_at_short")
    list_filter = ("status", "code")
    search_fields = ("payment__internal_reference", "title", "consent_reference_number")
    raw_id_fields = ("payment", "completed_by")
    readonly_fields = ("created_at", "updated_at", "completed_at")
    
    fieldsets = (
        ("Step Information", {
            "fields": ("payment", "code", "title", "sequence", "status")
        }),
        ("Documents & Evidence", {
            "fields": ("document", "document_name", "notes", "guidance")
        }),
        ("Stamp Duty Specific", {
            "fields": ("official_market_value", "assessed_stamp_duty"),
            "classes": ("collapse",),
        }),
        ("LCB Consent Specific", {
            "fields": ("consent_reference_number", "meeting_date"),
            "classes": ("collapse",),
        }),
        ("Completion Docs Specific", {
            "fields": ("original_title_received", "seller_id_copy_received", "transfer_forms_signed"),
            "classes": ("collapse",),
        }),
        ("Timestamps", {
            "fields": ("created_at", "updated_at", "completed_at", "completed_by"),
            "classes": ("collapse",),
        }),
    )
    
    def get_queryset(self, request):
        return super().get_queryset(request).select_related('payment', 'completed_by')
    
    def payment_ref(self, obj):
        return obj.payment.internal_reference
    payment_ref.short_description = "Payment"
    payment_ref.admin_order_field = "payment__internal_reference"
    
    def status_badge(self, obj):
        colors = {
            "pending": "gray",
            "in_progress": "orange",
            "completed": "green",
            "blocked": "red",
        }
        color = colors.get(obj.status, "gray")
        return format_html(
            '<span style="background: {}; color: white; padding: 2px 8px; border-radius: 12px; font-size: 11px;">{}</span>',
            color, obj.get_status_display()
        )
    status_badge.short_description = "Status"
    
    def completed_at_short(self, obj):
        return obj.completed_at.strftime("%Y-%m-%d %H:%M") if obj.completed_at else "-"
    completed_at_short.short_description = "Completed"


@admin.register(PaymentDisbursement)
class PaymentDisbursementAdmin(admin.ModelAdmin):
    list_display = ("payment_ref", "recipient_name", "amount_display", "status_badge", "released_at_short")
    list_filter = ("status", "recipient_role", "paid_by_side")
    search_fields = ("payment__internal_reference", "recipient_name")
    raw_id_fields = ("payment", "recipient_user")
    readonly_fields = ("created_at", "updated_at", "released_at")
    
    def payment_ref(self, obj):
        return obj.payment.internal_reference
    payment_ref.short_description = "Payment"
    
    def amount_display(self, obj):
        return f"KES {obj.amount:,.2f}"
    amount_display.short_description = "Amount"
    
    def status_badge(self, obj):
        colors = {
            "planned": "gray",
            "held": "orange",
            "ready": "blue",
            "released": "green",
        }
        color = colors.get(obj.status, "gray")
        return format_html(
            '<span style="background: {}; color: white; padding: 2px 8px; border-radius: 12px; font-size: 11px;">{}</span>',
            color, obj.get_status_display()
        )
    status_badge.short_description = "Status"
    
    def released_at_short(self, obj):
        return obj.released_at.strftime("%Y-%m-%d %H:%M") if obj.released_at else "-"
    released_at_short.short_description = "Released"


@admin.register(PaymentCertificate)
class PaymentCertificateAdmin(admin.ModelAdmin):
    list_display = ("payment_ref", "title", "audience", "status_badge", "issued_at_short")
    list_filter = ("status", "audience")
    search_fields = ("payment__internal_reference", "title")
    raw_id_fields = ("payment",)
    
    def payment_ref(self, obj):
        return obj.payment.internal_reference
    payment_ref.short_description = "Payment"
    
    def status_badge(self, obj):
        colors = {
            "pending": "gray",
            "ready": "orange",
            "issued": "green",
        }
        color = colors.get(obj.status, "gray")
        return format_html(
            '<span style="background: {}; color: white; padding: 2px 8px; border-radius: 12px; font-size: 11px;">{}</span>',
            color, obj.get_status_display()
        )
    status_badge.short_description = "Status"
    
    def issued_at_short(self, obj):
        return obj.issued_at.strftime("%Y-%m-%d %H:%M") if obj.issued_at else "-"
    issued_at_short.short_description = "Issued"


@admin.register(Wallet)
class WalletAdmin(admin.ModelAdmin):
    list_display = ("account_number", "user_link", "balance_display", "is_active", "created_at_short")
    list_filter = ("is_active", "created_at")
    search_fields = ("account_number", "user__username", "user__email")
    raw_id_fields = ("user",)
    readonly_fields = ("account_number", "created_at", "updated_at")
    
    fieldsets = (
        ("Wallet Information", {
            "fields": ("account_number", "user", "balance", "is_active")
        }),
        ("PIN Security", {
            "fields": ("pin_hash", "failed_pin_attempts", "locked_until"),
            "classes": ("collapse",),
        }),
        ("Timestamps", {
            "fields": ("created_at", "updated_at"),
            "classes": ("collapse",),
        }),
    )
    
    def user_link(self, obj):
        if obj.user:
            url = reverse('admin:auth_user_change', args=[obj.user.id])
            return format_html('<a href="{}">{}</a>', url, obj.user.username)
        return "-"
    user_link.short_description = "User"
    user_link.admin_order_field = "user__username"
    
    def balance_display(self, obj):
        return f"KES {obj.balance:,.2f}"
    balance_display.short_description = "Balance"
    balance_display.admin_order_field = "balance"
    
    def created_at_short(self, obj):
        return obj.created_at.strftime("%Y-%m-%d %H:%M")
    created_at_short.short_description = "Created"
    
    actions = ["activate_wallets", "deactivate_wallets"]
    
    def activate_wallets(self, request, queryset):
        updated = queryset.update(is_active=True)
        self.message_user(request, f"Activated {updated} wallet(s)")
    activate_wallets.short_description = "Activate selected wallets"
    
    def deactivate_wallets(self, request, queryset):
        updated = queryset.update(is_active=False)
        self.message_user(request, f"Deactivated {updated} wallet(s)")
    deactivate_wallets.short_description = "Deactivate selected wallets"


@admin.register(WalletTransaction)
class WalletTransactionAdmin(admin.ModelAdmin):
    list_display = ("reference", "wallet_account", "amount_display", "type_badge", "status_badge", "channel", "created_at_short")
    list_filter = ("type", "status", "channel", "created_at")
    search_fields = ("reference", "wallet__account_number", "mpesa_receipt")
    raw_id_fields = ("wallet", "payment_request")
    readonly_fields = ("reference", "created_at", "completed_at")
    
    def wallet_account(self, obj):
        return obj.wallet.account_number
    wallet_account.short_description = "Wallet"
    wallet_account.admin_order_field = "wallet__account_number"
    
    def amount_display(self, obj):
        color = "green" if obj.type == "CREDIT" else "red"
        return format_html(
            '<span style="color: {};">KES {:,.2f}</span>',
            color, obj.amount
        )
    amount_display.short_description = "Amount"
    
    def type_badge(self, obj):
        colors = {"CREDIT": "green", "DEBIT": "red"}
        color = colors.get(obj.type, "gray")
        return format_html(
            '<span style="background: {}; color: white; padding: 2px 8px; border-radius: 12px; font-size: 11px;">{}</span>',
            color, obj.get_type_display()
        )
    type_badge.short_description = "Type"
    
    def status_badge(self, obj):
        colors = {
            "PENDING": "orange",
            "PROCESSING": "blue",
            "SUCCESS": "green",
            "FAILED": "red",
            "CANCELLED": "gray",
            "FROZEN": "purple",
        }
        color = colors.get(obj.status, "gray")
        return format_html(
            '<span style="background: {}; color: white; padding: 2px 8px; border-radius: 12px; font-size: 11px;">{}</span>',
            color, obj.get_status_display()
        )
    status_badge.short_description = "Status"
    
    def created_at_short(self, obj):
        return obj.created_at.strftime("%Y-%m-%d %H:%M")
    created_at_short.short_description = "Created"
    
    actions = ["mark_as_success", "mark_as_failed"]
    
    def mark_as_success(self, request, queryset):
        for tx in queryset:
            if tx.status != "SUCCESS":
                tx.mark_success()
        self.message_user(request, f"Marked {queryset.count()} transaction(s) as successful")
    mark_as_success.short_description = "Mark selected as successful"
    
    def mark_as_failed(self, request, queryset):
        for tx in queryset:
            if tx.status != "FAILED":
                tx.mark_failed("Admin action")
        self.message_user(request, f"Marked {queryset.count()} transaction(s) as failed")
    mark_as_failed.short_description = "Mark selected as failed"


@admin.register(WalletDepositRequest)
class WalletDepositRequestAdmin(admin.ModelAdmin):
    list_display = ("reference", "user_link", "amount_display", "status_badge", "created_at_short")
    list_filter = ("status", "payment_method", "created_at")
    search_fields = ("reference", "user__username", "user__email")
    raw_id_fields = ("user", "payment_request", "wallet_transaction")
    readonly_fields = ("reference", "created_at", "completed_at", "expires_at")
    
    def user_link(self, obj):
        if obj.user:
            url = reverse('admin:auth_user_change', args=[obj.user.id])
            return format_html('<a href="{}">{}</a>', url, obj.user.username)
        return "-"
    user_link.short_description = "User"
    
    def amount_display(self, obj):
        return f"KES {obj.amount:,.2f}"
    amount_display.short_description = "Amount"
    
    def status_badge(self, obj):
        colors = {
            "pending": "orange",
            "processing": "blue",
            "completed": "green",
            "failed": "red",
            "expired": "gray",
        }
        color = colors.get(obj.status, "gray")
        return format_html(
            '<span style="background: {}; color: white; padding: 2px 8px; border-radius: 12px; font-size: 11px;">{}</span>',
            color, obj.status.upper()
        )
    status_badge.short_description = "Status"
    
    def created_at_short(self, obj):
        return obj.created_at.strftime("%Y-%m-%d %H:%M")
    created_at_short.short_description = "Created"


@admin.register(WalletWithdrawalRequest)
class WalletWithdrawalRequestAdmin(admin.ModelAdmin):
    list_display = ("reference", "user_link", "amount_display", "status_badge", "requires_approval", "created_at_short")
    list_filter = ("status", "payment_method", "created_at")
    search_fields = ("reference", "user__username", "user__email")
    raw_id_fields = ("user", "requested_by", "approved_by", "processed_by", "wallet_transaction")
    readonly_fields = ("reference", "created_at", "approved_at", "processed_at", "completed_at")
    
    fieldsets = (
        ("Withdrawal Request", {
            "fields": ("reference", "user", "amount", "payment_method", "phone_number", "status")
        }),
        ("Bank Transfer Details", {
            "fields": ("bank_name", "bank_account_name", "bank_account_number", "bank_branch", "bank_code"),
            "classes": ("collapse",),
        }),
        ("Approval Workflow", {
            "fields": ("requires_maker_checker", "requested_by", "approved_by", "approved_at", "approval_notes"),
            "classes": ("collapse",),
        }),
        ("Processing", {
            "fields": ("processed_by", "processed_at", "provider_reference", "provider_response"),
            "classes": ("collapse",),
        }),
        ("Timestamps", {
            "fields": ("created_at", "completed_at", "updated_at"),
            "classes": ("collapse",),
        }),
    )
    
    def user_link(self, obj):
        if obj.user:
            url = reverse('admin:auth_user_change', args=[obj.user.id])
            return format_html('<a href="{}">{}</a>', url, obj.user.username)
        return "-"
    user_link.short_description = "User"
    
    def amount_display(self, obj):
        return f"KES {obj.amount:,.2f}"
    amount_display.short_description = "Amount"
    
    def status_badge(self, obj):
        colors = {
            "pending": "orange",
            "approved": "blue",
            "processing": "purple",
            "completed": "green",
            "failed": "red",
            "rejected": "darkred",
            "cancelled": "gray",
        }
        color = colors.get(obj.status, "gray")
        return format_html(
            '<span style="background: {}; color: white; padding: 2px 8px; border-radius: 12px; font-size: 11px;">{}</span>',
            color, obj.status.upper()
        )
    status_badge.short_description = "Status"
    
    def requires_approval(self, obj):
        return "✓" if obj.requires_maker_checker() else "-"
    requires_approval.short_description = "2FA Required"
    
    def created_at_short(self, obj):
        return obj.created_at.strftime("%Y-%m-%d %H:%M")
    created_at_short.short_description = "Created"
    
    actions = ["approve_withdrawals", "reject_withdrawals", "mark_as_processed"]
    
    def approve_withdrawals(self, request, queryset):
        for w in queryset:
            if w.status == "pending":
                w.approve(request.user, "Batch approval via admin")
        self.message_user(request, f"Approved {queryset.count()} withdrawal(s)")
    approve_withdrawals.short_description = "Approve selected withdrawals"
    
    def reject_withdrawals(self, request, queryset):
        for w in queryset:
            if w.status == "pending":
                w.reject(request.user, "Rejected via admin")
        self.message_user(request, f"Rejected {queryset.count()} withdrawal(s)")
    reject_withdrawals.short_description = "Reject selected withdrawals"
    
    def mark_as_processed(self, request, queryset):
        for w in queryset:
            if w.status == "approved":
                w.status = "processing"
                w.processed_by = request.user
                w.processed_at = timezone.now()
                w.save()
        self.message_user(request, f"Marked {queryset.count()} withdrawal(s) as processing")
    mark_as_processed.short_description = "Mark as processing"


@admin.register(BankBeneficiary)
class BankBeneficiaryAdmin(admin.ModelAdmin):
    list_display = ("legal_name", "bank_name", "account_name", "account_number", "is_verified")
    list_filter = ("is_verified", "bank_name", "currency")
    search_fields = ("legal_name", "account_name", "account_number")
    raw_id_fields = ("user",)
    readonly_fields = ("created_at", "updated_at")
    
    actions = ["verify_beneficiaries"]
    
    def verify_beneficiaries(self, request, queryset):
        updated = queryset.update(is_verified=True, verification_reference=f"ADMIN-{timezone.now().timestamp()}")
        self.message_user(request, f"Verified {updated} beneficiary(ies)")
    verify_beneficiaries.short_description = "Verify selected beneficiaries"


@admin.register(BankTransferRequest)
class BankTransferRequestAdmin(admin.ModelAdmin):
    list_display = ("reference", "beneficiary_name", "amount_display", "rail", "status_badge", "created_at_short")
    list_filter = ("status", "rail", "provider", "created_at")
    search_fields = ("reference", "beneficiary_name", "account_number")
    raw_id_fields = ("payment", "disbursement", "beneficiary")
    readonly_fields = ("reference", "idempotency_key", "created_at", "submitted_at", "completed_at")
    
    def amount_display(self, obj):
        return f"KES {obj.amount:,.2f}"
    amount_display.short_description = "Amount"
    
    def status_badge(self, obj):
        colors = {
            "draft": "gray",
            "queued": "orange",
            "submitted": "blue",
            "processing": "purple",
            "settled": "green",
            "failed": "red",
            "reversed": "darkred",
            "reconciled": "teal",
        }
        color = colors.get(obj.status, "gray")
        return format_html(
            '<span style="background: {}; color: white; padding: 2px 8px; border-radius: 12px; font-size: 11px;">{}</span>',
            color, obj.status.upper()
        )
    status_badge.short_description = "Status"
    
    def created_at_short(self, obj):
        return obj.created_at.strftime("%Y-%m-%d %H:%M")
    created_at_short.short_description = "Created"


@admin.register(LeaseWaitlistEntry)
class LeaseWaitlistEntryAdmin(admin.ModelAdmin):
    list_display = ("plot_title", "user_link", "desired_duration_months", "status_badge", "queue_position", "created_at_short")
    list_filter = ("status", "desired_duration_months", "created_at")
    search_fields = ("plot__title", "user__username")
    raw_id_fields = ("plot", "user")
    readonly_fields = ("created_at", "updated_at", "last_notified_at")
    
    def plot_title(self, obj):
        return obj.plot.title if obj.plot else "-"
    plot_title.short_description = "Plot"
    plot_title.admin_order_field = "plot__title"
    
    def user_link(self, obj):
        if obj.user:
            url = reverse('admin:auth_user_change', args=[obj.user.id])
            return format_html('<a href="{}">{}</a>', url, obj.user.username)
        return "-"
    user_link.short_description = "User"
    
    def status_badge(self, obj):
        colors = {
            "waiting": "orange",
            "contacted": "blue",
            "confirmed": "green",
            "converted": "teal",
            "withdrawn": "gray",
        }
        color = colors.get(obj.status, "gray")
        return format_html(
            '<span style="background: {}; color: white; padding: 2px 8px; border-radius: 12px; font-size: 11px;">{}</span>',
            color, obj.get_status_display()
        )
    status_badge.short_description = "Status"
    
    def queue_position(self, obj):
        pos = obj.queue_position
        if pos:
            return f"#{pos}"
        return "-"
    queue_position.short_description = "Queue"
    
    def created_at_short(self, obj):
        return obj.created_at.strftime("%Y-%m-%d %H:%M")
    created_at_short.short_description = "Created"
    
    actions = ["mark_contacted", "mark_confirmed", "mark_converted"]
    
    def mark_contacted(self, request, queryset):
        for entry in queryset:
            entry.mark_contacted()
        self.message_user(request, f"Marked {queryset.count()} entry(s) as contacted")
    mark_contacted.short_description = "Mark as contacted"
    
    def mark_confirmed(self, request, queryset):
        for entry in queryset:
            entry.mark_confirmed()
        self.message_user(request, f"Marked {queryset.count()} entry(s) as confirmed")
    mark_confirmed.short_description = "Mark as confirmed"
    
    def mark_converted(self, request, queryset):
        for entry in queryset:
            entry.mark_converted()
        self.message_user(request, f"Marked {queryset.count()} entry(s) as converted")
    mark_converted.short_description = "Mark as converted"


@admin.register(WalletDisbursement)
class WalletDisbursementAdmin(admin.ModelAdmin):
    list_display = ("reference", "payment_ref", "recipient_wallet", "amount_display", "status_badge", "created_at_short")
    list_filter = ("status", "created_at")
    search_fields = ("reference", "payment_request__internal_reference")
    raw_id_fields = ("payment_request", "recipient_wallet", "wallet_transaction")
    readonly_fields = ("reference", "created_at", "completed_at")
    
    def payment_ref(self, obj):
        return obj.payment_request.internal_reference
    payment_ref.short_description = "Payment"
    
    def recipient_wallet(self, obj):
        return obj.recipient_wallet.account_number
    recipient_wallet.short_description = "Recipient Wallet"
    
    def amount_display(self, obj):
        return f"KES {obj.amount:,.2f}"
    amount_display.short_description = "Amount"
    
    def status_badge(self, obj):
        colors = {
            "pending": "orange",
            "processing": "blue",
            "completed": "green",
            "failed": "red",
        }
        color = colors.get(obj.status, "gray")
        return format_html(
            '<span style="background: {}; color: white; padding: 2px 8px; border-radius: 12px; font-size: 11px;">{}</span>',
            color, obj.status.upper()
        )
    status_badge.short_description = "Status"
    
    def created_at_short(self, obj):
        return obj.created_at.strftime("%Y-%m-%d %H:%M")
    created_at_short.short_description = "Created"