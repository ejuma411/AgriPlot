from decimal import Decimal
from django.urls import reverse
from django.conf import settings
from .models import PaymentRequest, PaymentCertificate, PaymentClosingStep


class PaymentPresenter:
    """
    Presenter for PaymentRequest that extracts presentation logic out of the model.
    Integrates with Legal Transaction for complete workflow visibility.
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
        """Check if there's an associated legal transaction"""
        return self._legal_transaction is not None

    @property
    def legal_transaction_stage(self):
        """Get current legal transaction stage"""
        if self._legal_transaction:
            return self._legal_transaction.get_stage_display()
        return "No legal transaction linked"

    @property
    def legal_transaction_progress(self):
        """Get legal transaction progress percentage"""
        if not self._legal_transaction:
            return 0
        
        stage_order = [
            'due_diligence',
            'commitment',
            'contracts',
            'statutory_consents',
            'taxation',
            'registration',
            'completed',
        ]
        
        current_stage = self._legal_transaction.stage
        if current_stage in stage_order:
            current_index = stage_order.index(current_stage)
            return int((current_index / len(stage_order)) * 100)
        return 0

    @property
    def legal_workspace_url(self):
        """URL to the legal workspace"""
        if self._legal_transaction:
            return reverse('transactions:detail', kwargs={'pk': self._legal_transaction.pk})
        return None

    @property
    def missing_legal_documents(self):
        """Get list of missing legal documents for current stage"""
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
        """Check if all legal requirements for current stage are met"""
        if not self._legal_transaction:
            # If no legal transaction exists for purchase, it should be created
            if self.payment.transaction_type == PaymentRequest.TransactionType.PURCHASE:
                return False
            return True
        
        can_advance, _ = self._legal_transaction.can_advance_to_next_stage()
        return can_advance

    @property
    def can_proceed_to_payment(self):
        """
        Check if payment can proceed for current stage.
        Requires legal documents to be verified first.
        """
        # Map payment stage to required legal stage
        payment_to_legal_map = {
            'due_diligence': 'due_diligence',
            'offer': 'commitment',
            'commitment': 'commitment',
            'agreement': 'contracts',
            'lcb_consent': 'statutory_consents',
            'completion_docs': 'statutory_consents',
            'stamp_duty': 'taxation',
            'registration': 'registration',
        }
        
        # Get current payment step from metadata
        current_step_code = self.payment.metadata.get('current_step_code', 'due_diligence')
        required_legal_stage = payment_to_legal_map.get(current_step_code)
        
        if required_legal_stage and self._legal_transaction:
            # Legal must be at or beyond required stage
            stage_order = ['due_diligence', 'commitment', 'contracts', 'statutory_consents', 'taxation', 'registration']
            
            if self._legal_transaction.stage in stage_order and required_legal_stage in stage_order:
                current_idx = stage_order.index(self._legal_transaction.stage)
                required_idx = stage_order.index(required_legal_stage)
                return current_idx >= required_idx and self.legal_requirements_met
        
        return self.legal_requirements_met

    @property
    def search_result_summary(self):
        search_result = getattr(self.payment.plot, "search_result", None) if self.payment.plot else None
        if not search_result:
            return "Registry search result is still pending upload."
        if search_result.encumbrances:
            return f"Registered interests noted: {search_result.encumbrances}"
        if search_result.verified:
            return "Registry search is verified and no encumbrances were recorded."
        return "Search result is on file but still awaiting final verification."

    @property
    def transaction_stage_matrix(self):
        if self.payment.transaction_type == PaymentRequest.TransactionType.PURCHASE:
            stamp_duty = self.payment._money_display(self.payment.purchase_stamp_duty_estimate)
            return [
                {
                    "stage": "1. Due Diligence",
                    "legal_stage": "due_diligence",
                    "money_required": (
                        f"{self.payment._money_display(self.payment.official_search_fee)} official search + "
                        f"{self.payment._money_display(self.payment.survey_search_fee)} survey search"
                    ),
                    "form_document": "Official search request, survey search request, seller KYC pack",
                    "required_information": "Title number, parcel number, buyer name, seller ID/KRA PIN, and plot location details.",
                    "who_provides": "Buyer initiates and pays; seller uploads title and identity support.",
                    "who_files": "AgriPlot coordinates the registry/survey request and stores the result in the transaction room.",
                    "system_output": "Encumbrance-free certificate draft, verified due-diligence pack, and payment acknowledgment.",
                    "legal_required_docs": ["OFFICIAL_SEARCH", "SURVEY_MAP"],
                    "payment_step": "due_diligence",
                },
                {
                    "stage": "2. Letter of Offer",
                    "legal_stage": "commitment",
                    "money_required": "Letter of offer and reservation terms",
                    "form_document": "Letter of offer / reservation terms and escrow acknowledgment",
                    "required_information": "Offer price, deposit amount, buyer and seller details, payment reference, and reservation expiry.",
                    "who_provides": "Buyer signs and funds the escrow; seller or agent accepts the commercial terms.",
                    "who_files": "AgriPlot records the commitment and issues proof-of-funds to the seller side.",
                    "system_output": "Buyer payment acknowledgment and seller proof-of-funds notice.",
                    "legal_required_docs": ["LETTER_OF_OFFER"],
                    "payment_step": "offer",
                },
                {
                    "stage": "3. Agreement & 10% Deposit",
                    "legal_stage": "contracts",
                    "money_required": f"{self.payment._money_display(self.payment.agreement_deposit_amount)} agreement deposit into escrow",
                    "form_document": "Sale Agreement and advocate details",
                    "required_information": "Purchase price, completion period, parties, advocates, title details, deposit handling, and default remedies.",
                    "who_provides": "Seller advocate drafts; buyer and seller review and sign.",
                    "who_files": "Signed agreement is uploaded in AgriPlot by the responsible advocate or admin.",
                    "system_output": "Signed-agreement certificate and the first escrow release trigger.",
                    "legal_required_docs": ["SALE_AGREEMENT"],
                    "payment_step": "agreement",
                },
                {
                    "stage": "4. Statutory Consents",
                    "legal_stage": "statutory_consents",
                    "money_required": f"{self.payment._money_display(self.payment.lcb_fee_amount)} estimated LCB / consent filing fees",
                    "form_document": "LCB consent, spousal consent, and other transfer clearances",
                    "required_information": "Consent reference, meeting date, land-control details, spouse/family approvals where applicable.",
                    "who_provides": "Seller leads statutory consent preparation with advocate support.",
                    "who_files": "AgriPlot or the advocate uploads the approval pack into the closing tracker.",
                    "system_output": "Consent clearance certificate showing the transfer is legally ready to continue.",
                    "legal_required_docs": ["LCB_CONSENT", "SPOUSAL_CONSENT"],
                    "payment_step": "lcb_consent",
                },
                {
                    "stage": "5. Completion Docs & 90% Balance",
                    "legal_stage": "statutory_consents",
                    "money_required": f"{self.payment._money_display(self.payment.completion_balance_amount)} balance release",
                    "form_document": "Completion pack, transfer forms, title bundle, and payout acknowledgment",
                    "required_information": "Original title, seller ID/KRA copies, signed transfer forms, release reference, and completion balance details.",
                    "who_provides": "Buyer advocate checks the pack; seller side releases the completion documents.",
                    "who_files": "Buyer advocate or AgriPlot admin uploads the completion evidence before the balance is released.",
                    "system_output": "Completion certificate and the release trigger for the remaining balance.",
                    "legal_required_docs": ["NEW_TITLE_DEED", "TRANSFER_FORM"],
                    "payment_step": "completion_docs",
                },
                {
                    "stage": "6. Valuation & Stamp Duty",
                    "legal_stage": "taxation",
                    "money_required": f"{stamp_duty} stamp duty and tax clearance",
                    "form_document": "Government valuation, stamp duty receipt, and CGT / tax evidence",
                    "required_information": "Official market value, assessed stamp duty, payment receipt, transfer reference, and KRA identifiers.",
                    "who_provides": "Buyer pays duty; seller handles seller-side tax obligations and supporting documents.",
                    "who_files": "Buyer advocate or AgriPlot admin uploads the valuation and receipts.",
                    "system_output": "Tax clearance acknowledgment and a ready-to-register transfer pack.",
                    "legal_required_docs": ["STAMP_DUTY_RECEIPT", "VALUATION_REPORT", "CGT_RECEIPT"],
                    "payment_step": "stamp_duty",
                },
                {
                    "stage": "7. Transfer & Registration",
                    "legal_stage": "registration",
                    "money_required": (
                        f"{self.payment._money_display(self.payment.transfer_fee_amount + self.payment.title_fee_amount)} registry filing fees"
                    ),
                    "form_document": "Transfer instrument, original title, signed completion bundle, fresh registry proof",
                    "required_information": "Signed transfer forms, original title, seller ID/PIN, buyer ID/PIN, completion balance reference, and final registry evidence.",
                    "who_provides": "Seller signs transfer forms; buyer advocate lodges the registration set.",
                    "who_files": "Advocate or AgriPlot admin uploads registry proof after transfer.",
                    "system_output": "Completion notice, final payout release, and digital certified title-copy record for the buyer.",
                    "legal_required_docs": ["NEW_TITLE_DEED", "TRANSFER_FORM"],
                    "payment_step": "registration",
                },
            ]

        if self.payment.transaction_type == PaymentRequest.TransactionType.LEASE:
            return [
                {
                    "stage": "1. Lease Application & Intent",
                    "legal_stage": "commitment",
                    "money_required": f"{self.payment._money_display(self.payment.amount)} commitment or first lease payment",
                    "form_document": "Lease offer / application and intended-use disclosure",
                    "required_information": "Requested term, intended use, start date, end date, and renewal expectations.",
                    "who_provides": "Tenant applies; landlord or agent reviews.",
                    "who_files": "AgriPlot opens the lease tracker and records the intent.",
                    "system_output": "Lease application acknowledgment and occupancy tracker entry.",
                    "legal_required_docs": [],
                    "payment_step": None,
                },
                {
                    "stage": "2. LCB & Family Consents",
                    "legal_stage": "statutory_consents",
                    "money_required": f"{self.payment._money_display(self.payment.lcb_fee_amount)} consent filing estimate for agricultural land",
                    "form_document": "LCB consent pack and any spousal/family approvals",
                    "required_information": "Consent reference, board date, spouses or family sign-off, and plot details.",
                    "who_provides": "Landlord side prepares statutory approvals.",
                    "who_files": "Seller, advocate, or admin uploads the consent evidence into AgriPlot.",
                    "system_output": "Consent-readiness certificate before occupation.",
                    "legal_required_docs": ["LCB_CONSENT"],
                    "payment_step": None,
                },
                {
                    "stage": "3. Deposit & Escrow",
                    "legal_stage": "contracts",
                    "money_required": f"{self.payment._money_display(self.payment.lease_security_deposit or self.payment.amount)} security deposit or rent commitment",
                    "form_document": "Escrow receipt and payment acknowledgment",
                    "required_information": "Tenant identity, lease reference, amount paid, payment method, and due date.",
                    "who_provides": "Tenant pays through AgriPlot.",
                    "who_files": "System-generated from payment confirmation.",
                    "system_output": "Tenant payment acknowledgment and landlord proof-of-funds notice.",
                    "legal_required_docs": [],
                    "payment_step": "payment_security",
                },
                {
                    "stage": "4. Digital Lease Agreement",
                    "legal_stage": "contracts",
                    "money_required": "Advocate or drafting costs if applicable",
                    "form_document": "Digitally confirmed lease agreement",
                    "required_information": "Term, notice period, good husbandry clause, subject-to-sale clause, and exit obligations.",
                    "who_provides": "Tenant and landlord both confirm digitally.",
                    "who_files": "AgriPlot stores the generated agreement and confirmation timestamps.",
                    "system_output": "Lease agreement certificate and compliance baseline.",
                    "legal_required_docs": ["SALE_AGREEMENT"],
                    "payment_step": "agreement",
                },
                {
                    "stage": "5. Registry & Soil Baseline",
                    "legal_stage": "taxation",
                    "money_required": (
                        f"{self.payment._money_display(self.payment.soil_baseline_fee_amount)} soil baseline / officer fee"
                    ),
                    "form_document": "Registry protection proof and soil baseline report",
                    "required_information": "Lease term, registry filing evidence, soil status, and entry condition notes.",
                    "who_provides": "AgriPlot-appointed officer or approved professional uploads the baseline and registry evidence.",
                    "who_files": "Professional report is uploaded before handover.",
                    "system_output": "Soil baseline certificate and long-lease protection evidence where required.",
                    "legal_required_docs": ["VALUATION_REPORT"],
                    "payment_step": None,
                },
                {
                    "stage": "6. Handover & Occupation",
                    "legal_stage": "registration",
                    "money_required": "No extra money unless handover services were ordered",
                    "form_document": "Possession note / handover acknowledgment",
                    "required_information": "Access date, site condition, boundaries, keys or access points, and outstanding obligations.",
                    "who_provides": "Landlord or agent meets the tenant for handover.",
                    "who_files": "AgriPlot stores the signed handover note and activates the lease status.",
                    "system_output": "Active occupancy notice, public lease status card, and next-lease waitlist visibility.",
                    "legal_required_docs": [],
                    "payment_step": "handover",
                },
                {
                    "stage": "7. Renewal or Exit",
                    "legal_stage": "completed",
                    "money_required": "Renewal fee only if a new term is agreed",
                    "form_document": "Renewal confirmation or exit soil report",
                    "required_information": "Renewal election, final notice date, soil exit result, and handback status.",
                    "who_provides": "Current tenant responds to reminders; landlord confirms renewal or exit.",
                    "who_files": "AgriPlot records reminders, exit proof, or renewal confirmation.",
                    "system_output": "Renewal notice trail, tenancy termination record, and automatic release for the next tenant if not renewed.",
                    "legal_required_docs": [],
                    "payment_step": None,
                },
            ]
        return []

    @property
    def officer_payment_rules(self):
        common_release = "Funds are held by AgriPlot and only released after the report or statutory evidence is uploaded and accepted."
        if self.payment.transaction_type == PaymentRequest.TransactionType.PURCHASE:
            return [
                {
                    "officer": "Registry / Lands Officer",
                    "paid_by": "Buyer",
                    "fee": self.payment._money_display(self.payment.official_search_fee),
                    "purpose": "Official search and registry proof.",
                    "release_rule": common_release,
                    "legal_requirement": "Required for due diligence stage",
                },
                {
                    "officer": "Survey Office / Licensed Surveyor",
                    "paid_by": "Buyer",
                    "fee": self.payment._money_display(self.payment.survey_search_fee),
                    "purpose": "Survey search, beacon alignment, or map verification.",
                    "release_rule": common_release,
                    "legal_requirement": "Required for due diligence stage",
                },
                {
                    "officer": "Land Control Board / Consent Processing",
                    "paid_by": "Seller",
                    "fee": self.payment._money_display(self.payment.lcb_fee_amount),
                    "purpose": "Consent-processing and statutory readiness costs.",
                    "release_rule": "Released after consent evidence and board reference are uploaded.",
                    "legal_requirement": "Mandatory for agricultural land under Cap 302",
                },
                {
                    "officer": "Government Valuer / Tax Workflow",
                    "paid_by": "Buyer",
                    "fee": self.payment._money_display(self.payment.purchase_stamp_duty_estimate),
                    "purpose": "Valuation-linked tax clearance and stamp-duty processing.",
                    "release_rule": "Released once the government valuation and tax receipt are captured.",
                    "legal_requirement": "2% rural / 4% urban stamp duty",
                },
            ]
        if self.payment.transaction_type == PaymentRequest.TransactionType.LEASE:
            return [
                {
                    "officer": "Land Control Board / Consent Processing",
                    "paid_by": "Landlord",
                    "fee": self.payment._money_display(self.payment.lcb_fee_amount),
                    "purpose": "Agricultural-lease consent processing.",
                    "release_rule": "Released after the consent pack is uploaded.",
                    "legal_requirement": "Required for agricultural lease",
                },
                {
                    "officer": "Extension Officer / Soil Professional",
                    "paid_by": "Tenant or buyer of baseline service",
                    "fee": self.payment._money_display(self.payment.soil_baseline_fee_amount),
                    "purpose": "Soil baseline and exit-condition support.",
                    "release_rule": common_release,
                    "legal_requirement": "Recommended for agricultural leases",
                },
                {
                    "officer": "Registry / Lawyer",
                    "paid_by": "Parties as agreed",
                    "fee": "Varies by lease term",
                    "purpose": "Registry protection for leases exceeding two years.",
                    "release_rule": "Released after filing proof is uploaded and the step is approved.",
                    "legal_requirement": "Required for leases > 2 years",
                },
            ]
        return []

    @property
    def platform_revenue_streams(self):
        return [
            {
                "label": "Escrow facilitation fee",
                "amount": self.payment._money_display(self.payment.platform_fee_amount),
                "detail": "AgriPlot earns this when the transaction completes and money is released through the platform workflow.",
            },
            {
                "label": "Verification markup",
                "amount": self.payment._money_display(self.payment.verification_markup_amount),
                "detail": "Markup on search and survey coordination that pays for the digital report packaging and platform handling.",
            },
            {
                "label": "Agent subscriptions / featured listings",
                "amount": "External to this deal",
                "detail": "Recurring revenue for broker tools and listing visibility, not deducted from this transaction automatically.",
            },
        ]

    @property
    def legal_status_summary(self):
        """Generate a summary of legal status for display in payment workspace"""
        if not self._legal_transaction:
            if self.payment.transaction_type == PaymentRequest.TransactionType.PURCHASE:
                confirmed_statuses = {
                    PaymentRequest.Status.PAID,
                    PaymentRequest.Status.IN_ESCROW,
                    PaymentRequest.Status.PARTIALLY_RELEASED,
                    PaymentRequest.Status.RELEASED,
                }
                if self.payment.status in confirmed_statuses:
                    message = "Legal workspace is being linked from the confirmed payment. Refresh after the transaction sync completes."
                else:
                    message = "Complete the initial payment to open the legal workspace."
                return {
                    "status": "pending",
                    "message": message,
                    "action_required": True,
                }
            return {
                "status": "not_required",
                "message": "No legal transaction required for this payment type.",
                "action_required": False,
            }
        
        can_advance, message = self._legal_transaction.can_advance_to_next_stage()
        
        if self._legal_transaction.stage == 'completed':
            return {
                "status": "completed",
                "message": "All legal requirements have been satisfied. Transaction is complete.",
                "action_required": False,
                "progress": 100,
            }
        
        missing_docs = self.missing_legal_documents
        if missing_docs:
            return {
                "status": "pending",
                "message": f"Legal documents pending: {', '.join(missing_docs)}",
                "action_required": True,
                "missing_docs": missing_docs,
                "progress": self.legal_transaction_progress,
            }
        
        return {
            "status": "ready",
            "message": "Legal requirements for current stage are met. Ready to proceed with payment.",
            "action_required": False,
            "progress": self.legal_transaction_progress,
        }

    @property
    def combined_workflow_summary(self):
        """Combine payment and legal workflow status for dashboard display"""
        legal_status = self.legal_status_summary
        
        # Get current payment step
        current_step = self.payment.current_assigned_step
        payment_step_name = current_step.display_title if current_step else "Complete"
        
        return {
            "payment_stage": payment_step_name,
            "legal_stage": self.legal_transaction_stage,
            "legal_progress": self.legal_transaction_progress,
            "legal_status": legal_status,
            "legal_workspace_url": self.legal_workspace_url,
            "can_proceed_to_payment": self.can_proceed_to_payment,
        }
