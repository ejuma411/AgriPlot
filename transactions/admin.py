from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html
from django.utils import timezone
from decimal import Decimal

from .models import Transaction, TransactionMilestone, TransactionDocument, TransactionEvent


@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = (
        "id", 
        "plot_link", 
        "buyer_link", 
        "seller_link", 
        "stage_badge", 
        "financial_summary", 
        "escrow_status",
        "stamp_duty_status",
        "created_at_short"
    )
    list_filter = (
        "stage", 
        "transaction_type", 
        "created_at",
        ("stage", admin.ChoicesFieldListFilter),
    )
    search_fields = ("plot__title", "plot__parcel_number", "buyer__username", "buyer__email", "seller__username", "seller__email")
    readonly_fields = (
        "created_at", 
        "updated_at", 
        "due_diligence_completed_at",
        "commitment_completed_at",
        "contracts_completed_at",
        "statutory_consents_completed_at",
        "taxation_completed_at",
        "registration_completed_at",
        "disbursement_completed_at",
        "completed_at",
        "deposit_held_in_escrow_at",
        "balance_held_in_escrow_at",
        "disbursed_at",
        "platform_fee_deducted_at",
        "stamp_duty_receipt_verified_at",
        "legal_workspace_link",
        "payment_link",
    )
    raw_id_fields = ("plot", "buyer", "seller", "buyer_advocate", "seller_advocate", "payment_request")
    
    fieldsets = (
        ("Transaction Information", {
            "fields": (
                "transaction_type",
                "stage",
                "payment_request",
                "legal_workspace_link",
                "payment_link",
            )
        }),
        ("Parties", {
            "fields": ("plot", "buyer", "seller", "buyer_advocate", "seller_advocate")
        }),
        ("Financial Details", {
            "fields": (
                "agreed_price",
                "ten_percent_deposit",
                "ninety_percent_balance",
                "deposit_paid",
                "balance_paid",
                "balance_due",
                "platform_fee_percentage",
                "platform_fee_amount",
                "seller_net_amount",
            )
        }),
        ("Escrow & Disbursement", {
            "fields": (
                "deposit_held_in_escrow_at",
                "balance_held_in_escrow_at",
                "disbursed_at",
                "platform_fee_deducted_at",
            ),
            "classes": ("collapse",),
        }),
        ("Taxation (Stamp Duty - Paid to KRA)", {
            "fields": (
                "stamp_duty_percentage",
                "stamp_duty_amount",
                "capital_gains_tax",
                "stamp_duty_receipt_number",
                "stamp_duty_receipt_verified_at",
                "stamp_duty_verified_by",
            ),
            "classes": ("collapse",),
        }),
        ("LCB & Statutory Consents", {
            "fields": (
                "lcb_meeting_date",
                "lcb_consent_reference",
                "lcb_application_fee",
            ),
            "classes": ("collapse",),
        }),
        ("Legal Timeline (Audit Trail)", {
            "fields": (
                "due_diligence_completed_at",
                "commitment_completed_at",
                "contracts_completed_at",
                "statutory_consents_completed_at",
                "taxation_completed_at",
                "registration_completed_at",
                "disbursement_completed_at",
                "completed_at",
            ),
            "classes": ("collapse",),
        }),
        ("Metadata", {
            "fields": ("notes", "created_at", "updated_at", "cancelled_at", "cancellation_reason"),
            "classes": ("collapse",),
        }),
    )
    
    def get_queryset(self, request):
        return super().get_queryset(request).select_related(
            'plot', 'buyer', 'seller', 'buyer_advocate', 'seller_advocate', 'payment_request'
        )
    
    def _safe_decimal(self, value):
        """Convert value to Decimal safely, handling SafeString and other types"""
        if value is None:
            return Decimal('0')
        if isinstance(value, Decimal):
            return value
        if isinstance(value, (int, float)):
            return Decimal(str(value))
        # Handle SafeString and other string types
        try:
            # Convert to string first to handle SafeString
            str_value = str(value)
            # Remove any commas, currency symbols, and extra spaces
            str_value = str_value.replace(',', '').replace('KES', '').replace('$', '').strip()
            return Decimal(str_value)
        except (ValueError, TypeError, Decimal.InvalidOperation):
            return Decimal('0')
    
    def _format_kes(self, value):
        """Format Decimal as KES string with commas"""
        decimal_value = self._safe_decimal(value)
        return f"KES {decimal_value:,.2f}"
    
    def plot_link(self, obj):
        if obj.plot:
            url = reverse('admin:listings_plot_change', args=[obj.plot.id])
            return format_html('<a href="{}">{}</a>', url, obj.plot.title)
        return "-"
    plot_link.short_description = "Plot"
    plot_link.admin_order_field = "plot__title"
    
    def buyer_link(self, obj):
        if obj.buyer:
            url = reverse('admin:auth_user_change', args=[obj.buyer.id])
            return format_html('<a href="{}">{}</a>', url, obj.buyer.username)
        return "-"
    buyer_link.short_description = "Buyer"
    buyer_link.admin_order_field = "buyer__username"
    
    def seller_link(self, obj):
        if obj.seller:
            url = reverse('admin:auth_user_change', args=[obj.seller.id])
            return format_html('<a href="{}">{}</a>', url, obj.seller.username)
        return "-"
    seller_link.short_description = "Seller"
    seller_link.admin_order_field = "seller__username"
    
    def stage_badge(self, obj):
        colors = {
            Transaction.Stage.DRAFT: "#6c757d",
            Transaction.Stage.DUE_DILIGENCE: "#0d6efd",
            Transaction.Stage.COMMITMENT: "#0dcaf0",
            Transaction.Stage.CONTRACTS: "#6f42c1",
            Transaction.Stage.STATUTORY_CONSENTS: "#fd7e14",
            Transaction.Stage.TAXATION: "#ffc107",
            Transaction.Stage.REGISTRATION: "#20c997",
            Transaction.Stage.DISBURSEMENT: "#198754",
            Transaction.Stage.COMPLETED: "#0f5c3f",
            Transaction.Stage.CANCELLED: "#dc3545",
        }
        color = colors.get(obj.stage, "#6c757d")
        return format_html(
            '<span style="background: {}; color: white; padding: 4px 8px; border-radius: 12px; font-size: 11px; font-weight: 500;">{}</span>',
            color, obj.get_stage_display()
        )
    stage_badge.short_description = "Stage"
    stage_badge.admin_order_field = "stage"
    
    def financial_summary(self, obj):
        # Convert all values to Decimal safely
        agreed_price = self._safe_decimal(obj.agreed_price)
        deposit_paid = self._safe_decimal(obj.deposit_paid)
        balance_paid = self._safe_decimal(obj.balance_paid)
        balance_due = self._safe_decimal(obj.balance_due)
        
        # Calculate percentages (as integers for display)
        if agreed_price > 0:
            deposit_percent = int((deposit_paid / agreed_price) * 100)
            balance_percent = int((balance_paid / agreed_price) * 100)
        else:
            deposit_percent = 0
            balance_percent = 0
        
        # Format numbers using string replacement instead of format_html with format specifiers
        # Convert to float then format manually to avoid SafeString issues
        agreed_str = "{:,.2f}".format(float(agreed_price))
        deposit_str = "{:,.2f}".format(float(deposit_paid))
        balance_str = "{:,.2f}".format(float(balance_paid))
        due_str = "{:,.2f}".format(float(balance_due))
        
        # Build HTML as string then mark as safe
        html = (
            '<div style="font-size: 12px;">'
            f'<strong>KES {agreed_str}</strong><br>'
            f'<span style="color: #2e7d32;">Deposit: KES {deposit_str} ({deposit_percent}%)</span><br>'
            f'<span style="color: #1976d2;">Balance: KES {balance_str} ({balance_percent}%)</span><br>'
            f'<span style="color: #ff9800;">Due: KES {due_str}</span>'
            '</div>'
        )
        return format_html(html)
    financial_summary.short_description = "Financial Summary"
    
    def escrow_status(self, obj):
        if obj.disbursed_at:
            return format_html('<span style="color: #2e7d32;">✓ Disbursed to Seller</span>')
        if obj.balance_held_in_escrow_at and obj.deposit_held_in_escrow_at:
            return format_html('<span style="color: #ff9800;">💰 Full Amount in Escrow</span>')
        if obj.deposit_held_in_escrow_at:
            return format_html('<span style="color: #ff9800;">💵 Deposit (10%) in Escrow</span>')
        if obj.stage in [Transaction.Stage.CONTRACTS, Transaction.Stage.STATUTORY_CONSENTS, Transaction.Stage.TAXATION]:
            return format_html('<span style="color: #999;">⏳ Awaiting Escrow</span>')
        return format_html('<span style="color: #999;">—</span>')
    escrow_status.short_description = "Escrow Status"
    
    def stamp_duty_status(self, obj):
        if obj.stamp_duty_receipt_verified_at:
            return format_html(
                '<span style="color: #2e7d32;">✓ Verified</span><br>'
                '<span style="font-size: 11px;">Receipt: {}</span>',
                obj.stamp_duty_receipt_number or "N/A"
            )
        elif obj.stage == Transaction.Stage.TAXATION:
            return format_html('<span style="color: #ff9800;">⏳ Pending Verification</span>')
        return format_html('<span style="color: #999;">—</span>')
    stamp_duty_status.short_description = "Stamp Duty (KRA)"
    
    def created_at_short(self, obj):
        return obj.created_at.strftime("%Y-%m-%d %H:%M")
    created_at_short.short_description = "Created"
    created_at_short.admin_order_field = "created_at"
    
    def legal_workspace_link(self, obj):
        url = reverse('admin:transactions_transaction_change', args=[obj.id])
        return format_html('<a href="{}">Open Legal Workspace</a>', url)
    legal_workspace_link.short_description = "Legal Workspace"
    
    def payment_link(self, obj):
        if obj.payment_request:
            url = reverse('admin:payments_paymentrequest_change', args=[obj.payment_request.id])
            return format_html('<a href="{}">View Payment</a>', url)
        return "No linked payment"
    payment_link.short_description = "Linked Payment"
    
    def escrow_status_display(self, obj):
        lines = []
        if obj.deposit_held_in_escrow_at:
            lines.append(f"Deposit held: {obj.deposit_held_in_escrow_at.strftime('%Y-%m-%d %H:%M')}")
        else:
            lines.append("Deposit: Pending")
        
        if obj.balance_held_in_escrow_at:
            lines.append(f"Balance held: {obj.balance_held_in_escrow_at.strftime('%Y-%m-%d %H:%M')}")
        else:
            lines.append("Balance: Pending")
        
        if obj.disbursed_at:
            lines.append(f"Disbursed to seller: {obj.disbursed_at.strftime('%Y-%m-%d %H:%M')}")
            platform_fee = self._safe_decimal(obj.platform_fee_amount)
            seller_net = self._safe_decimal(obj.seller_net_amount)
            lines.append(f"Platform fee deducted: KES {platform_fee:,.2f}")
            lines.append(f"Seller net received: KES {seller_net:,.2f}")
        
        return format_html("<br>".join(lines))
    escrow_status_display.short_description = "Escrow Details"
    
    def stamp_duty_status_display(self, obj):
        if obj.stamp_duty_receipt_verified_at:
            return format_html(
                "✓ Verified by {} at {}<br>Receipt: {}",
                obj.stamp_duty_verified_by.username if obj.stamp_duty_verified_by else "System",
                obj.stamp_duty_receipt_verified_at.strftime('%Y-%m-%d %H:%M'),
                obj.stamp_duty_receipt_number or "N/A"
            )
        return "Pending verification (paid directly to KRA via iTax)"
    stamp_duty_status_display.short_description = "Stamp Duty Details"
    
    actions = ["verify_stamp_duty", "mark_disbursed", "send_reports"]
    
    def verify_stamp_duty(self, request, queryset):
        """Admin action to manually verify stamp duty payment to KRA"""
        count = 0
        for transaction in queryset:
            if not transaction.stamp_duty_receipt_verified_at:
                transaction.stamp_duty_receipt_verified_at = timezone.now()
                transaction.stamp_duty_verified_by = request.user
                transaction.save(update_fields=['stamp_duty_receipt_verified_at', 'stamp_duty_verified_by', 'updated_at'])
                
                transaction.add_event(
                    'stamp_duty_verified',
                    f"Stamp duty verified by admin {request.user.username}. Receipt: {transaction.stamp_duty_receipt_number}",
                    actor=request.user
                )
                count += 1
        self.message_user(request, f"Verified stamp duty for {count} transaction(s)")
    verify_stamp_duty.short_description = "Verify stamp duty receipts (KRA iTax)"
    
    def mark_disbursed(self, request, queryset):
        """Admin action to manually mark funds as disbursed"""
        count = 0
        for transaction in queryset:
            if not transaction.disbursed_at and transaction.stage == Transaction.Stage.REGISTRATION:
                transaction.disbursed_at = timezone.now()
                transaction.platform_fee_deducted_at = timezone.now()
                transaction.stage = Transaction.Stage.DISBURSEMENT
                transaction.save(update_fields=['disbursed_at', 'platform_fee_deducted_at', 'stage', 'updated_at'])
                
                transaction.add_event(
                    'disbursement_marked',
                    f"Disbursement marked by admin {request.user.username}",
                    actor=request.user
                )
                count += 1
        self.message_user(request, f"Marked {count} transaction(s) as disbursed")
    mark_disbursed.short_description = "Mark as disbursed (after registration)"
    
    def send_reports(self, request, queryset):
        """Admin action to resend transaction reports"""
        from notifications.notification_service import NotificationService
        count = 0
        for transaction in queryset:
            if transaction.stage == Transaction.Stage.COMPLETED:
                # Trigger report sending
                transaction._send_transaction_reports()
                count += 1
        self.message_user(request, f"Sent reports for {count} transaction(s)")
    send_reports.short_description = "Resend transaction reports"


# Keep the rest of your admin registrations unchanged (TransactionMilestoneAdmin, TransactionDocumentAdmin, TransactionEventAdmin)
# They remain exactly as you had them

# Keep the rest of your admin registrations unchanged
@admin.register(TransactionMilestone)
class TransactionMilestoneAdmin(admin.ModelAdmin):
    list_display = ("transaction_link", "milestone_type_badge", "achieved_by_link", "achieved_at_short", "notes_preview")
    list_filter = ("milestone_type", "achieved_at")
    search_fields = ("transaction__id", "transaction__plot__title", "notes")
    readonly_fields = ("achieved_at",)
    
    fieldsets = (
        ("Milestone Information", {
            "fields": ("transaction", "milestone_type", "achieved_by", "achieved_at")
        }),
        ("Notes", {
            "fields": ("notes",)
        }),
    )
    
    def get_queryset(self, request):
        return super().get_queryset(request).select_related('transaction', 'achieved_by')
    
    def transaction_link(self, obj):
        url = reverse('admin:transactions_transaction_change', args=[obj.transaction.id])
        return format_html('<a href="{}">TX #{}</a>', url, obj.transaction.id)
    transaction_link.short_description = "Transaction"
    
    def milestone_type_badge(self, obj):
        colors = {
            "due_diligence": "#0d6efd",
            "commitment": "#0dcaf0",
            "contracts": "#6f42c1",
            "statutory_consents": "#fd7e14",
            "taxation": "#ffc107",
            "registration": "#20c997",
            "disbursement": "#198754",
            "completed": "#0f5c3f",
            "cancelled": "#dc3545",
        }
        color = colors.get(obj.milestone_type, "#6c757d")
        return format_html(
            '<span style="background: {}; color: white; padding: 2px 8px; border-radius: 12px; font-size: 11px;">{}</span>',
            color, obj.get_milestone_type_display()
        )
    milestone_type_badge.short_description = "Milestone"
    
    def achieved_by_link(self, obj):
        if obj.achieved_by:
            url = reverse('admin:auth_user_change', args=[obj.achieved_by.id])
            return format_html('<a href="{}">{}</a>', url, obj.achieved_by.username)
        return "System"
    achieved_by_link.short_description = "Achieved By"
    
    def achieved_at_short(self, obj):
        return obj.achieved_at.strftime("%Y-%m-%d %H:%M")
    achieved_at_short.short_description = "Date"
    achieved_at_short.admin_order_field = "achieved_at"
    
    def notes_preview(self, obj):
        if obj.notes:
            return obj.notes[:100] + "..." if len(obj.notes) > 100 else obj.notes
        return "-"
    notes_preview.short_description = "Notes"


@admin.register(TransactionDocument)
class TransactionDocumentAdmin(admin.ModelAdmin):
    list_display = (
        "transaction_link", 
        "document_type_badge", 
        "status_badge", 
        "uploaded_by_link", 
        "uploaded_at_short",
        "reference_number_preview",
        "verification_status"
    )
    list_filter = ("document_type", "status", "uploaded_at")
    search_fields = ("transaction__id", "filename", "reference_number", "uploaded_by__username")
    readonly_fields = ("uploaded_at", "file_size", "mime_type", "verification_timeline")
    raw_id_fields = ("transaction", "verified_by", "uploaded_by")
    
    fieldsets = (
        ("Document Information", {
            "fields": ("transaction", "document_type", "file", "filename", "file_size", "mime_type")
        }),
        ("Document Metadata", {
            "fields": ("document_date", "reference_number", "notes")
        }),
        ("Verification", {
            "fields": ("status", "verified_by", "verified_at", "rejection_reason", "verification_timeline")
        }),
        ("Audit", {
            "fields": ("uploaded_by", "uploaded_at"),
            "classes": ("collapse",),
        }),
    )
    
    def get_queryset(self, request):
        return super().get_queryset(request).select_related('transaction', 'uploaded_by', 'verified_by')
    
    def transaction_link(self, obj):
        url = reverse('admin:transactions_transaction_change', args=[obj.transaction.id])
        return format_html('<a href="{}">TX #{}</a>', url, obj.transaction.id)
    transaction_link.short_description = "Transaction"
    
    def document_type_badge(self, obj):
        # Color coding by document category
        due_diligence_docs = ['OFFICIAL_SEARCH', 'SURVEY_MAP']
        commitment_docs = ['LETTER_OF_OFFER']
        contract_docs = ['SALE_AGREEMENT']
        consent_docs = ['LCB_CONSENT', 'SPOUSAL_CONSENT']
        tax_docs = ['STAMP_DUTY_RECEIPT', 'VALUATION_REPORT', 'CGT_RECEIPT']
        registration_docs = ['TRANSFER_FORM', 'ORIGINAL_TITLE_DEED', 'NEW_TITLE_DEED']
        supporting_docs = ['ID_DOCUMENT', 'KRA_PIN', 'RATES_CLEARANCE', 'RENT_CLEARANCE', 'PASSPORT_PHOTO']
        
        if obj.document_type in due_diligence_docs:
            color = "#0d6efd"
        elif obj.document_type in commitment_docs:
            color = "#0dcaf0"
        elif obj.document_type in contract_docs:
            color = "#6f42c1"
        elif obj.document_type in consent_docs:
            color = "#fd7e14"
        elif obj.document_type in tax_docs:
            color = "#ffc107"
        elif obj.document_type in registration_docs:
            color = "#20c997"
        elif obj.document_type in supporting_docs:
            color = "#6c757d"
        else:
            color = "#6c757d"
        
        return format_html(
            '<span style="background: {}; color: white; padding: 2px 8px; border-radius: 12px; font-size: 11px;">{}</span>',
            color, obj.get_document_type_display()
        )
    document_type_badge.short_description = "Document Type"
    
    def status_badge(self, obj):
        colors = {
            "pending": "#ffc107",
            "verified": "#198754",
            "rejected": "#dc3545",
        }
        color = colors.get(obj.status, "#6c757d")
        return format_html(
            '<span style="background: {}; color: white; padding: 2px 8px; border-radius: 12px; font-size: 11px;">{}</span>',
            color, obj.get_status_display()
        )
    status_badge.short_description = "Status"
    
    def uploaded_by_link(self, obj):
        if obj.uploaded_by:
            url = reverse('admin:auth_user_change', args=[obj.uploaded_by.id])
            return format_html('<a href="{}">{}</a>', url, obj.uploaded_by.username)
        return "-"
    uploaded_by_link.short_description = "Uploaded By"
    
    def uploaded_at_short(self, obj):
        return obj.uploaded_at.strftime("%Y-%m-%d %H:%M")
    uploaded_at_short.short_description = "Uploaded"
    
    def reference_number_preview(self, obj):
        if obj.reference_number:
            return obj.reference_number[:30]
        return "-"
    reference_number_preview.short_description = "Reference"
    
    def verification_status(self, obj):
        if obj.verified_at:
            return format_html(
                '✓ Verified<br><span style="font-size: 11px;">by {} on {}</span>',
                obj.verified_by.username if obj.verified_by else "System",
                obj.verified_at.strftime('%Y-%m-%d %H:%M')
            )
        elif obj.status == "rejected":
            return format_html(
                '✗ Rejected<br><span style="font-size: 11px;">Reason: {}</span>',
                obj.rejection_reason[:50] if obj.rejection_reason else "No reason provided"
            )
        return "Awaiting verification"
    verification_status.short_description = "Verification"
    
    def verification_timeline(self, obj):
        lines = []
        if obj.uploaded_at:
            lines.append(f"Uploaded: {obj.uploaded_at.strftime('%Y-%m-%d %H:%M:%S')}")
        if obj.verified_at:
            lines.append(f"Verified: {obj.verified_at.strftime('%Y-%m-%d %H:%M:%S')}")
            if obj.verified_by:
                lines.append(f"Verified by: {obj.verified_by.username}")
        if obj.rejection_reason:
            lines.append(f"Rejection reason: {obj.rejection_reason}")
        return format_html("<br>".join(lines) if lines else "No verification events")
    verification_timeline.short_description = "Timeline"
    
    actions = ["verify_documents", "reject_documents"]
    
    def verify_documents(self, request, queryset):
        """Admin action to verify selected documents"""
        count = 0
        for doc in queryset:
            if doc.status != "verified":
                doc.status = "verified"
                doc.verified_by = request.user
                doc.verified_at = timezone.now()
                doc.save(update_fields=['status', 'verified_by', 'verified_at', 'updated_at'])
                
                doc.transaction.add_event(
                    'document_verified',
                    f"Document {doc.get_document_type_display()} verified by {request.user.username}",
                    actor=request.user
                )
                count += 1
        self.message_user(request, f"Verified {count} document(s)")
    verify_documents.short_description = "Verify selected documents"
    
    def reject_documents(self, request, queryset):
        """Admin action to reject selected documents"""
        count = 0
        for doc in queryset:
            if doc.status != "rejected":
                doc.status = "rejected"
                doc.verified_by = request.user
                doc.verified_at = timezone.now()
                doc.save(update_fields=['status', 'verified_by', 'verified_at', 'updated_at'])
                
                doc.transaction.add_event(
                    'document_rejected',
                    f"Document {doc.get_document_type_display()} rejected by {request.user.username}",
                    actor=request.user
                )
                count += 1
        self.message_user(request, f"Rejected {count} document(s)")
    reject_documents.short_description = "Reject selected documents"


@admin.register(TransactionEvent)
class TransactionEventAdmin(admin.ModelAdmin):
    list_display = ("transaction_link", "event_type", "actor_link", "message_preview", "created_at_short")
    list_filter = ("event_type", "created_at")
    search_fields = ("transaction__id", "message", "actor__username")
    readonly_fields = ("created_at",)
    
    fieldsets = (
        ("Event Information", {
            "fields": ("transaction", "event_type", "actor", "message")
        }),
        ("Audit", {
            "fields": ("created_at", "ip_address"),
            "classes": ("collapse",),
        }),
    )
    
    def get_queryset(self, request):
        return super().get_queryset(request).select_related('transaction', 'actor')
    
    def transaction_link(self, obj):
        url = reverse('admin:transactions_transaction_change', args=[obj.transaction.id])
        return format_html('<a href="{}">TX #{}</a>', url, obj.transaction.id)
    transaction_link.short_description = "Transaction"
    
    def actor_link(self, obj):
        if obj.actor:
            url = reverse('admin:auth_user_change', args=[obj.actor.id])
            return format_html('<a href="{}">{}</a>', url, obj.actor.username)
        return "System"
    actor_link.short_description = "Actor"
    
    def message_preview(self, obj):
        if obj.message:
            return obj.message[:100] + "..." if len(obj.message) > 100 else obj.message
        return "-"
    message_preview.short_description = "Message"
    
    def created_at_short(self, obj):
        return obj.created_at.strftime("%Y-%m-%d %H:%M:%S")
    created_at_short.short_description = "Timestamp"