from decimal import Decimal
from django.urls import reverse
from django.conf import settings
from .models import PaymentRequest, PaymentCertificate, PaymentClosingStep
from datetime import datetime


class PaymentPresenter:
    """
    Presenter for PaymentRequest with PLATFORM ESCROW model.
    Funds are held by the platform in a licensed escrow account,
    then automatically disbursed to seller AFTER registration completes,
    WITH platform fees deducted before disbursement.
    Stamp duty is paid directly to KRA iTax (platform never touches it).
    """
    
    def __init__(self, payment_request: PaymentRequest):
        self.payment = payment_request
        self._legal_transaction = None
        self._load_legal_transaction()

    def _load_legal_transaction(self):
        """Load the associated legal transaction if it exists"""
        try:
            self._legal_transaction = self.payment.legal_transaction
        except Exception:
            self._legal_transaction = None

    @property
    def has_legal_transaction(self):
        return self._legal_transaction is not None

    @property
    def legal_transaction_stage(self):
        if self._legal_transaction:
            return self._legal_transaction.get_stage_display()
        return "No legal transaction linked"


    @property
    def deposit_amount(self):
        """Calculate 10% deposit amount"""
        from decimal import Decimal
        return self.payment.amount * Decimal('0.1')

    @property
    def balance_amount(self):
        """Calculate 90% balance amount"""
        from decimal import Decimal
        return self.payment.amount * Decimal('0.9')

    @property
    def stamp_duty_rural(self):
        """Calculate 2% stamp duty for rural areas"""
        from decimal import Decimal
        return self.payment.amount * Decimal('0.02')

    @property
    def stamp_duty_urban(self):
        """Calculate 4% stamp duty for urban areas"""
        from decimal import Decimal
        return self.payment.amount * Decimal('0.04')

    @property
    def legal_transaction_progress(self):
        if not self._legal_transaction:
            return 0
        
        # Keep the progress bar aligned to the canonical transaction stage enum.
        stage_order = [
            'due_diligence',
            'commitment',
            'contracts',
            'statutory_consents',
            'taxation',
            'completion',
            'registration',
            'disbursement',
            'completed',
        ]
        
        current_stage = self._legal_transaction.stage
        if current_stage in stage_order:
            current_index = stage_order.index(current_stage)
            denominator = max(len(stage_order) - 1, 1)
            return int((current_index / denominator) * 100)
        return 0

    @property
    def legal_transaction_stage_index(self):
        """Zero-based index of the current legal transaction stage."""
        if not self._legal_transaction:
            return 0

        stage_order = [
            'due_diligence',
            'commitment',
            'contracts',
            'statutory_consents',
            'taxation',
            'completion',
            'registration',
            'disbursement',
            'completed',
        ]

        current_stage = self._legal_transaction.stage
        if current_stage in stage_order:
            return stage_order.index(current_stage)
        return 0

    @property
    def legal_workspace_url(self):
        if self._legal_transaction:
            return reverse('transactions:detail', kwargs={'pk': self._legal_transaction.pk})
        return None

    @property
    def missing_legal_documents(self):
        if not self._legal_transaction:
            return []
        
        from transactions.models import TransactionDocument
        
        required_docs = self._legal_transaction.get_required_documents_for_stage()
        missing = []
        
        for doc_type in required_docs:
            has_doc = TransactionDocument.objects.filter(
                transaction=self._legal_transaction,
                document_type=doc_type,
                status='verified'
            ).exists()
            if not has_doc:
                missing.append(dict(TransactionDocument.DocType.choices).get(doc_type, doc_type))
        
        return missing

    @property
    def legal_requirements_met(self):
        if not self._legal_transaction:
            if self.payment.transaction_type == PaymentRequest.TransactionType.PURCHASE:
                return False
            return True
        
        can_advance, _ = self._legal_transaction.can_advance_to_next_stage()
        return can_advance

    @property
    def can_proceed_to_payment(self):
        """
        Determines if user can proceed to payment based on current stage.
        Platform holds all funds except stamp duty (paid directly to KRA).
        """
        current_step_code = self.payment.metadata.get('current_step_code', 'due_diligence')
        
        # Stamp duty is paid directly to KRA, not through platform
        if current_step_code == 'stamp_duty':
            return True
            
        return self.legal_requirements_met

    @property
    def search_result_summary(self):
        search_result = getattr(self.payment.plot, "search_result", None) if self.payment.plot else None
        if not search_result:
            return "Official land search result pending. Must be obtained via Ardhisasa/eCitizen."
        if search_result.encumbrances:
            return f"WARNING: Registered encumbrances found: {search_result.encumbrances}. Legal advice required."
        if search_result.verified:
            return "Official search completed. No encumbrances recorded. Title is free for transfer."
        return "Search result uploaded but verification pending."

    @property
    def platform_fee_percentage(self):
        """Platform fee as percentage of transaction value (1-3% standard for Kenya)"""
        value = self.payment.amount
        if value < Decimal('1000000'):  # Below 1M KES
            return Decimal('0.03')  # 3%
        elif value < Decimal('5000000'):  # 1M-5M KES
            return Decimal('0.025')  # 2.5%
        elif value < Decimal('10000000'):  # 5M-10M KES
            return Decimal('0.02')  # 2%
        else:  # Above 10M KES
            return Decimal('0.015')  # 1.5%
    
    @property
    def platform_fee_amount(self):
        """Calculate platform fee based on percentage"""
        return self.payment.amount * self.platform_fee_percentage
    
    @property
    def seller_net_amount(self):
        """Amount seller receives after platform fee deduction"""
        return self.payment.amount - self.platform_fee_amount

    @property
    def transaction_stage_matrix(self):
        """
        Platform escrow workflow for Kenya land purchase.
        Funds are held by platform and disbursed ONLY after registration,
        WITH platform fee deducted before seller payment.
        Stamp duty is paid directly to KRA iTax.
        """
        if self.payment.transaction_type == PaymentRequest.TransactionType.PURCHASE:
            return self._get_purchase_workflow()
        
        if self.payment.transaction_type == PaymentRequest.TransactionType.LEASE:
            return self._get_lease_workflow()
        
        return []

    def _get_purchase_workflow(self):
        """Platform escrow workflow with automatic disbursement after registration"""
        total_price = self.payment.amount
        deposit_10_percent = total_price * Decimal('0.1')
        balance_90_percent = total_price * Decimal('0.9')
        platform_fee = self.platform_fee_amount
        seller_net = self.seller_net_amount
        
        return [
            {
                "stage": "1. Due Diligence",
                "step_code": "due_diligence",
                "money_required": f"{self.payment._money_display(self.payment.official_search_fee)} (paid via eCitizen/Ardhisasa)",
                "who_pays": "Buyer",
                "payment_channel": "eCitizen (outside platform)",
                "action": "Display land documents, ownership verification, title search results, and land control checks.",
                "document_required": "Official Search Certificate (green card)",
                "platform_role": "Upload and verify search certificate",
                "payment_step": "due_diligence",
                "funds_held_by": "N/A (paid directly to government)",
            },
            {
                "stage": "2. Offer Agreement",
                "step_code": "commitment",
                "money_required": "No payment",
                "who_pays": "N/A",
                "payment_channel": "N/A",
                "action": "Generate the offer letter / sale agreement for review, negotiation, and e-signing.",
                "document_required": "Offer Letter / Sale Agreement",
                "platform_role": "Template generation, change tracking, digital signing",
                "payment_step": "offer_agreement",
                "funds_held_by": "N/A",
            },
            {
                "stage": "3. Agreement Deposit",
                "step_code": "contracts",
                "money_required": f"{self.payment._money_display(deposit_10_percent)} (10% of {self.payment._money_display(total_price)})",
                "who_pays": "Buyer",
                "payment_channel": "Platform escrow (M-Pesa, bank, card)",
                "action": "Buyer pays 10% agreement deposit after the sale agreement is accepted.",
                "document_required": "Signed Sale Agreement",
                "platform_role": "Hold deposit in licensed escrow, store agreement",
                "payment_step": "agreement_deposit",
                "funds_held_by": "PLATFORM ESCROW",
                "disbursement_condition": "Released AFTER registration, with fee deducted",
            },
            {
                "stage": "4. Statutory Consents",
                "step_code": "statutory_consents",
                "money_required": "No payment to AgriPlot",
                "who_pays": "N/A",
                "payment_channel": "N/A",
                "action": "Land Control Board consent, county consent, spousal consent, and tax compliance are checked.",
                "document_required": "LCB Consent / Supporting Clearances",
                "platform_role": "Track consent status and store supporting documents",
                "payment_step": "statutory_consents",
                "funds_held_by": "N/A",
            },
            {
                "stage": "5. Stamp Duty Payment",
                "step_code": "taxation",
                "money_required": "Calculated automatically and paid directly to KRA",
                "who_pays": "Buyer",
                "payment_channel": "KRA iTax ONLY",
                "action": "Buyer pays stamp duty directly to KRA and uploads the receipt for verification.",
                "document_required": "Stamp Duty Payment Receipt from KRA",
                "platform_role": "Verify receipt, NEVER touch stamp duty funds",
                "payment_step": "stamp_duty",
                "funds_held_by": "KRA (platform never holds)",
                "critical_note": "Platform does NOT collect stamp duty. Buyer pays KRA directly via iTax.",
            },
            {
                "stage": "6. Completion Balance",
                "step_code": "completion",
                "money_required": f"{self.payment._money_display(balance_90_percent)} (90% of {self.payment._money_display(total_price)})",
                "who_pays": "Buyer",
                "payment_channel": "Platform escrow (M-Pesa, bank, card)",
                "action": "Buyer pays the remaining 90% balance after consents and stamp duty are complete.",
                "document_required": "Completion documents and transfer pack",
                "platform_role": "Hold balance in escrow until final registration",
                "payment_step": "completion_balance",
                "funds_held_by": "PLATFORM ESCROW",
                "disbursement_condition": "Released AFTER registration, with fee deducted",
            },
            {
                "stage": "7. Final Registration",
                "step_code": "registration",
                "money_required": "Registration fees (KES 5,000-10,000)",
                "who_pays": "Buyer",
                "payment_channel": "eCitizen",
                "action": "Buyer's advocate lodges documents at land registry. Registry issues new title in buyer's name.",
                "document_required": "New Title Deed in buyer's name",
                "platform_role": "Track registration, verify new title uploaded",
                "payment_step": "registration",
                "funds_held_by": "N/A (paid directly to eCitizen)",
                "critical_note": "Transaction NOT complete until new title issued.",
            },
            {
                "stage": "8. Platform Fee Deduction & Automatic Disbursement to Seller",
                "step_code": "disbursement",
                "money_required": f"Platform Fee: {self.payment._money_display(platform_fee)} ({self.platform_fee_percentage * 100}%)",
                "who_pays": "Platform deducts from escrow",
                "payment_channel": "Automatic bank transfer",
                "action": "Upon new title verification: (1) Platform deducts service fee, (2) Balance sent to seller, (3) Seller receives {self.payment._money_display(seller_net)}",
                "document_required": "New Title Deed (verified), disbursement confirmation",
                "platform_role": "Automated fee deduction and disbursement to seller",
                "payment_step": "release",
                "funds_held_by": "Seller (after disbursement)",
                "critical_note": f"Platform fee: {self.platform_fee_percentage * 100}% of sale price. Seller net: {self.payment._money_display(seller_net)}",
            },
            {
                "stage": "9. Transaction Complete",
                "step_code": "completed",
                "money_required": "None",
                "who_pays": "N/A",
                "payment_channel": "Email (automated)",
                "action": "The land transfer is complete, disbursement has been made, and the workflow is closed.",
                "document_required": "Completion confirmation",
                "platform_role": "Mark workflow complete and archive the file",
                "payment_step": "completed",
                "funds_held_by": "N/A",
            },
            {
                "stage": "10. Transaction Reports Sent to Both Parties",
                "step_code": "reports",
                "money_required": "None",
                "who_pays": "N/A",
                "payment_channel": "Email (automated)",
                "action": "Platform generates and emails comprehensive transaction reports to buyer and seller.",
                "document_required": "Transaction Report (PDF), Tax Compliance Report, Payment Receipts",
                "platform_role": "Generate and email reports automatically",
                "payment_step": "reports",
                "funds_held_by": "N/A",
                "reports_include": [
                    "Full payment history",
                    "Platform fee breakdown",
                    "Stamp duty verification (KRA receipt)",
                    "Legal documents checklist",
                    "New title deed copy",
                    "Timeline of all stages",
                    "Tax compliance summary",
                ],
            },
            {
                "stage": "11. Possession & Handover",
                "step_code": "handover",
                "money_required": "None",
                "who_pays": "N/A",
                "payment_channel": "N/A",
                "action": "Buyer takes physical possession. Keys, site handover note signed.",
                "document_required": "Handover certificate",
                "platform_role": "Store handover evidence, send final completion notice",
                "payment_step": "handover",
                "funds_held_by": "N/A",
            },
        ]

    def _get_lease_workflow(self):
        """Platform escrow workflow for agricultural leases"""
        total_rent = self.payment.amount
        platform_fee = total_rent * Decimal('0.05')  # 5% for leases
        landlord_net = total_rent - platform_fee
        
        return [
            {
                "stage": "1. Due Diligence & Search",
                "step_code": "search",
                "money_required": "Search fees",
                "who_pays": "Tenant",
                "payment_channel": "eCitizen",
                "action": "Official search to confirm landlord's ownership.",
                "document_required": "Official Search Certificate",
                "platform_role": "Store search result",
                "funds_held_by": "Government",
            },
            {
                "stage": "2. Lease Agreement & Deposit to Platform",
                "step_code": "lease_deposit",
                "money_required": f"{self.payment._money_display(total_rent)} (deposit + first rent)",
                "who_pays": "Tenant",
                "payment_channel": "Platform escrow",
                "action": "Signed lease agreement. Tenant pays deposit to platform escrow.",
                "document_required": "Signed Lease Agreement",
                "platform_role": "Hold deposit, store agreement",
                "funds_held_by": "PLATFORM ESCROW",
                "disbursement_condition": "Released upon handover, after fee deduction",
            },
            {
                "stage": "3. LCB Consent (if lease >2 years)",
                "step_code": "lcb_consent",
                "money_required": "Application fee",
                "who_pays": "Landlord",
                "payment_channel": "County government",
                "action": "Landlord applies for LCB consent.",
                "document_required": "LCB Consent Certificate",
                "platform_role": "Track application",
                "funds_held_by": "County government",
            },
            {
                "stage": "4. Registration (if lease >2 years)",
                "step_code": "registration",
                "money_required": "Registration fees",
                "who_pays": "As agreed",
                "payment_channel": "eCitizen",
                "action": "Register lease at land registry.",
                "document_required": "Registered lease",
                "platform_role": "Verify registration",
                "funds_held_by": "Government",
            },
            {
                "stage": "5. Platform Fee Deduction & Disbursement to Landlord",
                "step_code": "disbursement",
                "money_required": f"Platform Fee: {self.payment._money_display(platform_fee)} (5%)",
                "who_pays": "Platform deducts from escrow",
                "payment_channel": "Bank transfer to landlord",
                "action": "Upon handover: Platform deducts fee, sends {self.payment._money_display(landlord_net)} to landlord.",
                "document_required": "Handover certificate, disbursement confirmation",
                "platform_role": "Automated disbursement",
                "funds_held_by": "Landlord (after release)",
            },
            {
                "stage": "6. Transaction Reports Sent",
                "step_code": "reports",
                "money_required": "None",
                "who_pays": "N/A",
                "payment_channel": "Email",
                "action": "Platform sends lease transaction reports to both parties.",
                "document_required": "Lease Transaction Report",
                "platform_role": "Generate and email reports",
            },
            {
                "stage": "7. Ongoing Rent Payments",
                "step_code": "rent",
                "money_required": "Monthly/quarterly rent",
                "who_pays": "Tenant",
                "payment_channel": "Platform (optional) or direct",
                "action": "Tenant pays rent as per lease schedule.",
                "document_required": "Rent payment receipts",
                "platform_role": "Collect and remit rent (optional service)",
                "funds_held_by": "Platform (temporarily) → Landlord",
            },
        ]

    @property
    def platform_revenue_streams(self):
        """
        Platform earns fees for escrow and facilitation services.
        Fees are deducted BEFORE disbursement to seller.
        All fees are disclosed and legal as service charges.
        """
        platform_fee = self.platform_fee_amount
        platform_fee_percent = self.platform_fee_percentage * 100
        
        return {
            "fees_collected": [
                {
                    "label": "Escrow & Facilitation Fee",
                    "amount": self.payment._money_display(platform_fee),
                    "percentage": f"{platform_fee_percent}% of transaction value",
                    "deduction_timing": "Deducted from escrow BEFORE seller disbursement",
                    "legal_basis": "Service fee for escrow, document verification, and workflow management",
                    "charged_to": "Seller (deducted from proceeds)",
                },
                {
                    "label": "Transaction Report Generation",
                    "amount": "Included in facilitation fee",
                    "percentage": "0% additional",
                    "deduction_timing": "N/A",
                    "legal_basis": "Compliance and record-keeping",
                    "charged_to": "Included",
                },
            ],
            "disbursement_summary": {
                "total_collected_from_buyer": self.payment._money_display(self.payment.amount),
                "platform_fee_deducted": self.payment._money_display(platform_fee),
                "amount_paid_to_seller": self.payment._money_display(self.seller_net_amount),
                "fee_percentage": f"{platform_fee_percent}%",
            },
            "other_revenue": [
                {
                    "label": "Stamp Duty",
                    "amount": "Paid directly to KRA",
                    "detail": "Platform does NOT touch stamp duty funds",
                },
                {
                    "label": "Government Fees",
                    "amount": "Paid directly to eCitizen/county",
                    "detail": "Search, registration, LCB fees go directly to government",
                },
            ],
            "disclosure": "All fees disclosed in Terms of Service and Sale Agreement. Seller agrees to fee deduction before disbursement.",
        }
        
    @property
    def officer_payment_rules(self):
        """
        Define payment rules for various officers based on transaction type.
        """
        if self.payment.transaction_type == PaymentRequest.TransactionType.PURCHASE:
            return [
                {
                    "service": "Official Land Search",
                    "paid_by": "Buyer",
                    "payment_channel": "eCitizen / Ardhisasa",
                    "estimated_amount": self.payment._money_display(self.payment.official_search_fee),
                    "legal_requirement": "Mandatory for due diligence",
                    "platform_role": "Facilitate upload of search result",
                },
                {
                    "service": "Survey/Beacon Verification",
                    "paid_by": "Buyer",
                    "payment_channel": "Direct to licensed surveyor",
                    "estimated_amount": self.payment._money_display(self.payment.survey_search_fee),
                    "legal_requirement": "Strongly recommended",
                    "platform_role": "Connect with licensed surveyors",
                },
                {
                    "service": "LCB Consent",
                    "paid_by": "Seller",
                    "payment_channel": "County government",
                    "estimated_amount": self.payment._money_display(self.payment.lcb_fee_amount),
                    "legal_requirement": "Mandatory for agricultural land",
                    "platform_role": "Track application status",
                },
                {
                    "service": "Stamp Duty",
                    "paid_by": "Buyer",
                    "payment_channel": "KRA iTax (ONLY)",
                    "estimated_amount": "2% rural / 4% urban of property value",
                    "legal_requirement": "Mandatory for registration",
                    "platform_role": "Link to iTax, verify receipt",
                },
                {
                    "service": "10% Deposit & 90% Balance",
                    "paid_by": "Buyer",
                    "payment_channel": "Platform Escrow",
                    "estimated_amount": self.payment._money_display(self.payment.amount),
                    "legal_requirement": "Funds held in escrow pending registration",
                    "platform_role": "Hold in licensed escrow account",
                },
            ]
        return []
        
    @property
    def transaction_report_data(self):
        """Data structure for final transaction reports sent to both parties"""
        return {
            "report_generated_at": datetime.now().isoformat(),
            "transaction_id": self.payment.id,
            "property_details": {
                "title_number": getattr(self.payment.plot, 'title_number', 'N/A'),
                "parcel_number": getattr(self.payment.plot, 'parcel_number', 'N/A'),
                "location": getattr(self.payment.plot, 'location', 'N/A'),
                "size": getattr(self.payment.plot, 'size_acres', 'N/A'),
            },
            "parties": {
                "buyer": {
                    "name": self.payment.buyer.get_full_name() if self.payment.buyer else 'N/A',
                    "email": self.payment.buyer.email if self.payment.buyer else 'N/A',
                    "kra_pin": getattr(self.payment, 'buyer_kra_pin', 'N/A'),
                    "id_number": getattr(self.payment, 'buyer_id_number', 'N/A'),
                },
                "seller": {
                    "name": self.payment.seller.get_full_name() if self.payment.seller else 'N/A',
                    "email": self.payment.seller.email if self.payment.seller else 'N/A',
                    "kra_pin": getattr(self.payment, 'seller_kra_pin', 'N/A'),
                    "id_number": getattr(self.payment, 'seller_id_number', 'N/A'),
                },
            },
            "financial_summary": {
                "purchase_price": self.payment._money_display(self.payment.amount),
                "deposit_paid": self.payment._money_display(self.payment.amount * Decimal('0.1')),
                "balance_paid": self.payment._money_display(self.payment.amount * Decimal('0.9')),
                "platform_fee": self.payment._money_display(self.platform_fee_amount),
                "platform_fee_percentage": f"{self.platform_fee_percentage * 100}%",
                "seller_net_received": self.payment._money_display(self.seller_net_amount),
                "stamp_duty_paid": "Paid directly to KRA (receipt uploaded)",
                "government_fees": {
                    "official_search": self.payment._money_display(self.payment.official_search_fee),
                    "survey_fee": self.payment._money_display(self.payment.survey_search_fee),
                    "lcb_fee": self.payment._money_display(self.payment.lcb_fee_amount),
                    "registration_fee": "Paid via eCitizen",
                },
            },
            "documents_verified": self._get_verified_documents_list(),
            "timeline": self._get_transaction_timeline(),
            "legal_compliance": {
                "land_control_consent": "Obtained" if self._check_document_verified('LCB_CONSENT') else "N/A",
                "spousal_consent": "Obtained" if self._check_document_verified('SPOUSAL_CONSENT') else "N/A",
                "stamp_duty_paid": "Verified" if self._check_document_verified('STAMP_DUTY_RECEIPT') else "Pending",
                "new_title_issued": "Issued" if self._check_document_verified('NEW_TITLE_DEED') else "Pending",
            },
            "kra_tax_compliance": {
                "stamp_duty_receipt": "Uploaded and verified",
                "capital_gains_tax": "Seller responsible for filing",
                "withholding_tax": "Applicable if seller is non-resident",
                "advice": "Consult your tax advisor for annual tax returns",
            },
            "report_disclaimer": "This report is for record purposes only. Not a tax document. Keep for KRA audit trail.",
        }
    
    def _get_verified_documents_list(self):
        """Get list of verified documents for the transaction"""
        if not self._legal_transaction:
            return []
        
        from transactions.models import TransactionDocument
        
        documents = TransactionDocument.objects.filter(
            transaction=self._legal_transaction,
            status='verified'
        ).values_list('document_type', flat=True)
        
        doc_names = []
        doc_mapping = {
            'OFFICIAL_SEARCH': 'Official Search Certificate',
            'SURVEY_MAP': 'Survey/Beacon Report',
            'SALE_AGREEMENT': 'Signed Sale Agreement',
            'LCB_CONSENT': 'LCB Consent Certificate',
            'SPOUSAL_CONSENT': 'Spousal Consent Form',
            'RATES_CLEARANCE': 'Land Rates Clearance',
            'RENT_CLEARANCE': 'Land Rent Clearance',
            'STAMP_DUTY_RECEIPT': 'Stamp Duty Payment Receipt (KRA)',
            'TRANSFER_FORM': 'Transfer Form RL1',
            'NEW_TITLE_DEED': 'New Title Deed (Buyer)',
            'HANDOVER_NOTE': 'Handover Certificate',
        }
        
        for doc_type in documents:
            if doc_type in doc_mapping:
                doc_names.append(doc_mapping[doc_type])
        
        return doc_names
    
    def _check_document_verified(self, doc_type):
        """Check if a specific document type is verified"""
        if not self._legal_transaction:
            return False
        
        from transactions.models import TransactionDocument
        
        return TransactionDocument.objects.filter(
            transaction=self._legal_transaction,
            document_type=doc_type,
            status='verified'
        ).exists()
    
    def _get_transaction_timeline(self):
        """Get timeline of key transaction events"""
        timeline = []
        
        if self.payment.created_at:
            timeline.append({
                "date": self.payment.created_at.isoformat(),
                "event": "Transaction initiated",
                "stage": "Start",
            })
        
        if self._check_document_verified('OFFICIAL_SEARCH'):
            timeline.append({
                "date": "Date from model",
                "event": "Official search completed",
                "stage": "Due Diligence",
            })
        
        if self._check_document_verified('SALE_AGREEMENT'):
            timeline.append({
                "date": "Date from model",
                "event": "Sale agreement signed, deposit paid",
                "stage": "Agreement & Deposit",
            })
        
        if self._check_document_verified('STAMP_DUTY_RECEIPT'):
            timeline.append({
                "date": "Date from model",
                "event": "Stamp duty paid to KRA",
                "stage": "Taxation",
            })
        
        if self._check_document_verified('NEW_TITLE_DEED'):
            timeline.append({
                "date": "Date from model",
                "event": "New title issued, funds disbursed to seller",
                "stage": "Completion",
            })
        
        return timeline

    @property
    def stamp_duty_status(self):
        """Track stamp duty payment status (paid directly to KRA)"""
        stamp_duty_receipt = self._check_document_verified('STAMP_DUTY_RECEIPT')
        
        return {
            "required": True,
            "payment_channel": "KRA iTax ONLY",
            "platform_collects": False,
            "receipt_uploaded": stamp_duty_receipt,
            "receipt_verified": stamp_duty_receipt,
            "instructions": "Pay directly to KRA via iTax (M-Pesa, bank, card) and upload receipt",
            "kra_link": "https://itax.kra.go.ke",
            "penalty": "50% penalty + interest for underpayment or late payment",
            "stamp_duty_rate": "2% rural / 4% urban of property value",
        }

    @property
    def disbursement_schedule(self):
        """Automatic disbursement triggers and schedule with fee deduction"""
        registration_complete = self._check_document_verified('NEW_TITLE_DEED')
        
        return {
            "total_held_in_escrow": self.payment._money_display(self.payment.amount),
            "platform_fee": {
                "amount": self.payment._money_display(self.platform_fee_amount),
                "percentage": f"{self.platform_fee_percentage * 100}%",
                "deduction_timing": "Before seller disbursement",
            },
            "seller_payout": {
                "amount": self.payment._money_display(self.seller_net_amount),
                "trigger": "After new title deed verified",
                "status": "Ready for disbursement" if registration_complete else "Pending registration",
                "auto_release": True,
            },
            "disbursement_method": "Automated bank transfer to seller's registered account",
            "disbursement_timeline": "1-3 business days after registration confirmation",
            "transaction_report": {
                "status": "Sent automatically after disbursement",
                "recipients": ["buyer_email", "seller_email"],
                "format": "PDF + Email summary",
            },
        }

    @property
    def escrow_summary(self):
        """Summary of funds currently held in platform escrow for this transaction"""
        total_price = self.payment.amount
        deposit_paid = self.payment.metadata.get('deposit_paid', False)
        balance_paid = self.payment.metadata.get('balance_paid', False)
        disbursed = self.payment.metadata.get('disbursed', False)
        
        current_holdings = Decimal('0')
        if not disbursed:
            if deposit_paid:
                current_holdings += total_price * Decimal('0.1')
            if balance_paid:
                current_holdings += total_price * Decimal('0.9')
        
        return {
            "total_escrowed": self.payment._money_display(current_holdings),
            "deposit_received": deposit_paid,
            "balance_received": balance_paid,
            "disbursed_to_seller": disbursed,
            "disbursement_trigger": "New title deed verification required",
            "platform_fee_reserved": self.payment._money_display(self.platform_fee_amount) if not disbursed else "Deducted",
            "seller_net_pending": self.payment._money_display(self.seller_net_amount) if not disbursed else "Paid",
            "escrow_license": "Held under [Platform Name] Escrow License",
            "funds_protection": "Funds held in regulated trust account",
        }

    @property
    def legal_status_summary(self):
        """Generate legal status summary with escrow-specific information"""
        if not self._legal_transaction:
            if self.payment.transaction_type == PaymentRequest.TransactionType.PURCHASE:
                return {
                    "status": "legal_workspace_required",
                    "message": "Legal transaction workspace required for land transfer.",
                    "action_required": True,
                    "action": "Create legal transaction",
                }
            return {
                "status": "not_required",
                "message": "No legal transaction required.",
                "action_required": False,
            }
        
        can_advance, message = self._legal_transaction.can_advance_to_next_stage()
        
        if self._legal_transaction.stage == 'completed':
            return {
                "status": "completed",
                "message": "Transaction fully completed. All funds disbursed, reports delivered, handover confirmed.",
                "action_required": False,
                "progress": 100,
            }
        
        if self._legal_transaction.stage == 'disbursement':
            return {
                "status": "disbursed",
                "message": f"Funds disbursed to seller. Platform fee of {self.payment._money_display(self.platform_fee_amount)} deducted.",
                "action_required": False,
                "progress": 95,
            }
        
        missing_docs = self.missing_legal_documents
        if missing_docs:
            return {
                "status": "documents_pending",
                "message": f"Documents required: {', '.join(missing_docs)}",
                "action_required": True,
                "missing_docs": missing_docs,
                "progress": self.legal_transaction_progress,
            }
        
        return {
            "status": "ready",
            "message": "Legal requirements met. Proceed to next step.",
            "action_required": False,
            "progress": self.legal_transaction_progress,
        }

    @property
    def registration_checklist(self):
        """Pre-registration checklist - required before funds can be disbursed"""
        return {
            "required_for_disbursement": [
                "✓ New Title Deed issued in buyer's name",
                "✓ Title uploaded and verified on platform",
                "✓ Stamp duty payment verified (KRA receipt)",
                "✓ All consents and clearances on file",
                "✓ No pending encumbrances",
            ],
            "disbursement_process": {
                "step_1": "Verify new title deed",
                "step_2": f"Deduct platform fee ({self.platform_fee_percentage * 100}% - {self.payment._money_display(self.platform_fee_amount)})",
                "step_3": f"Disburse balance ({self.payment._money_display(self.seller_net_amount)}) to seller",
                "step_4": "Send transaction reports to buyer and seller",
                "step_5": "Confirm handover",
            },
            "estimated_timeline": "7-90 days (depends on land registry)",
            "funds_security": "Funds remain in escrow until all conditions met",
            "platform_fee_disclosure": f"Platform fee of {self.platform_fee_percentage * 100}% deducted before seller payment",
        }

    @property
    def combined_workflow_summary(self):
        """Complete workflow summary with escrow, fee deduction, and reporting"""
        legal_status = self.legal_status_summary
        current_step = self.payment.current_assigned_step
        payment_step_name = current_step.display_title if current_step else "Complete"
        
        return {
            "payment_stage": payment_step_name,
            "legal_stage": self.legal_transaction_stage,
            "legal_progress": self.legal_transaction_progress,
            "legal_status": legal_status,
            "legal_workspace_url": self.legal_workspace_url,
            "can_proceed_to_payment": self.can_proceed_to_payment,
            "escrow_summary": self.escrow_summary,
            "stamp_duty_status": self.stamp_duty_status,
            "disbursement_schedule": self.disbursement_schedule,
            "platform_revenue": self.platform_revenue_streams,
            "transaction_report": self.transaction_report_data,
            "platform_model": "Platform holds escrow funds, deducts fee, disburses to seller after registration",
            "stamp_duty_model": "Buyer pays KRA directly, platform only verifies receipt",
            "reporting": "Automated transaction reports emailed to both parties after disbursement",
            "fee_summary": f"Platform fee: {self.platform_fee_percentage * 100}% ({self.payment._money_display(self.platform_fee_amount)}) deducted from seller proceeds",
        }
    
    def generate_and_send_reports(self):
        """
        Method to generate and send transaction reports to both parties.
        Called automatically after fund disbursement.
        """
        report_data = self.transaction_report_data
        
        return {
            "buyer_report": {
                "to": report_data['parties']['buyer']['email'],
                "subject": f"Transaction Complete - {report_data['transaction_id']} - Your Property Purchase Report",
                "attachments": ["transaction_report.pdf", "stamp_duty_receipt.pdf", "new_title_deed.pdf"],
                "key_information": [
                    "Purchase completed successfully",
                    "New title deed issued in your name",
                    "Stamp duty paid to KRA (receipt attached)",
                    "Funds disbursed to seller after title verification",
                    "Platform fee paid by seller (not buyer)",
                ],
            },
            "seller_report": {
                "to": report_data['parties']['seller']['email'],
                "subject": f"Transaction Complete - {report_data['transaction_id']} - Funds Disbursed",
                "attachments": ["transaction_report.pdf", "disbursement_confirmation.pdf"],
                "key_information": [
                    f"Transaction completed, funds disbursed",
                    f"Gross amount: {report_data['financial_summary']['purchase_price']}",
                    f"Platform fee deducted: {report_data['financial_summary']['platform_fee']}",
                    f"Net amount received: {report_data['financial_summary']['seller_net_received']}",
                    "KRA stamp duty paid by buyer (not deducted from your payment)",
                    "Remember to file Capital Gains Tax with KRA",
                ],
            },
            "compliance_attachments": {
                "kra_reminder": "Seller must file CGT within 30 days of transfer",
                "buyer_reminder": "Keep title deed and stamp duty receipt for your records",
                "both_parties": "Retain this report for KRA audit trail (minimum 5 years)",
            },
        }
