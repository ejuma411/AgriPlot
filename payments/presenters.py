from decimal import Decimal
from .models import PaymentRequest, PaymentCertificate, PaymentClosingStep

class PaymentPresenter:
    """
    Presenter for PaymentRequest that extracts presentation logic out of the model.
    """
    def __init__(self, payment_request: PaymentRequest):
        self.payment = payment_request

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
                    "money_required": (
                        f"{self.payment._money_display(self.payment.official_search_fee)} official search + "
                        f"{self.payment._money_display(self.payment.survey_search_fee)} survey search"
                    ),
                    "form_document": "Official search request, survey search request, seller KYC pack",
                    "required_information": "Title number, parcel number, buyer name, seller ID/KRA PIN, and plot location details.",
                    "who_provides": "Buyer initiates and pays; seller uploads title and identity support.",
                    "who_files": "AgriPlot coordinates the registry/survey request and stores the result in the transaction room.",
                    "system_output": "Encumbrance-free certificate draft, verified due-diligence pack, and payment acknowledgment.",
                },
                {
                    "stage": "2. Commitment",
                    "money_required": f"{self.payment._money_display(self.payment.agreement_deposit_amount)} agreement deposit into escrow",
                    "form_document": "Letter of offer / reservation terms and escrow acknowledgment",
                    "required_information": "Offer price, deposit amount, buyer and seller details, payment reference, and reservation expiry.",
                    "who_provides": "Buyer signs and funds the escrow; seller or agent accepts the commercial terms.",
                    "who_files": "AgriPlot records the commitment and issues proof-of-funds to the seller side.",
                    "system_output": "Buyer payment acknowledgment and seller proof-of-funds notice.",
                },
                {
                    "stage": "3. Agreement",
                    "money_required": "Advocate fees and any agreed document-preparation costs",
                    "form_document": "Sale Agreement and advocate details",
                    "required_information": "Purchase price, completion period, parties, advocates, title details, deposit handling, and default remedies.",
                    "who_provides": "Seller advocate drafts; buyer and seller review and sign.",
                    "who_files": "Signed agreement is uploaded in AgriPlot by the responsible advocate or admin.",
                    "system_output": "Signed-agreement certificate and the first escrow release trigger.",
                },
                {
                    "stage": "4. Consents",
                    "money_required": f"{self.payment._money_display(self.payment.lcb_fee_amount)} estimated LCB / consent filing fees",
                    "form_document": "LCB consent, spousal consent, and other transfer clearances",
                    "required_information": "Consent reference, meeting date, land-control details, spouse/family approvals where applicable.",
                    "who_provides": "Seller leads statutory consent preparation with advocate support.",
                    "who_files": "AgriPlot or the advocate uploads the approval pack into the closing tracker.",
                    "system_output": "Consent clearance certificate showing the transfer is legally ready to continue.",
                },
                {
                    "stage": "5. Taxation",
                    "money_required": f"{stamp_duty} stamp duty + registry transfer fees",
                    "form_document": "Government valuation, stamp duty receipt, KRA/eCitizen confirmations",
                    "required_information": "Official market value, assessed stamp duty, payment receipt, transfer reference, and KRA identifiers.",
                    "who_provides": "Buyer pays duty; seller handles seller-side tax obligations and supporting documents.",
                    "who_files": "Buyer advocate or AgriPlot admin uploads the valuation and receipts.",
                    "system_output": "Tax clearance acknowledgment and a ready-to-register completion pack.",
                },
                {
                    "stage": "6. Transfer & Registration",
                    "money_required": (
                        f"{self.payment._money_display(self.payment.transfer_fee_amount + self.payment.title_fee_amount)} registry filing fees + "
                        f"{self.payment._money_display(self.payment.completion_balance_amount)} balance release"
                    ),
                    "form_document": "Transfer instrument, original title, signed completion bundle, fresh registry proof",
                    "required_information": "Signed transfer forms, original title, seller ID/PIN, buyer ID/PIN, completion balance reference, and final registry evidence.",
                    "who_provides": "Seller signs transfer forms; buyer advocate lodges the registration set.",
                    "who_files": "Advocate or AgriPlot admin uploads registry proof after transfer.",
                    "system_output": "Completion notice, final payout release, and digital certified title-copy record for the buyer.",
                },
            ]

        if self.payment.transaction_type == PaymentRequest.TransactionType.LEASE:
            return [
                {
                    "stage": "1. Lease Application & Intent",
                    "money_required": f"{self.payment._money_display(self.payment.amount)} commitment or first lease payment",
                    "form_document": "Lease offer / application and intended-use disclosure",
                    "required_information": "Requested term, intended use, start date, end date, and renewal expectations.",
                    "who_provides": "Tenant applies; landlord or agent reviews.",
                    "who_files": "AgriPlot opens the lease tracker and records the intent.",
                    "system_output": "Lease application acknowledgment and occupancy tracker entry.",
                },
                {
                    "stage": "2. LCB & Family Consents",
                    "money_required": f"{self.payment._money_display(self.payment.lcb_fee_amount)} consent filing estimate for agricultural land",
                    "form_document": "LCB consent pack and any spousal/family approvals",
                    "required_information": "Consent reference, board date, spouses or family sign-off, and plot details.",
                    "who_provides": "Landlord side prepares statutory approvals.",
                    "who_files": "Seller, advocate, or admin uploads the consent evidence into AgriPlot.",
                    "system_output": "Consent-readiness certificate before occupation.",
                },
                {
                    "stage": "3. Deposit & Escrow",
                    "money_required": f"{self.payment._money_display(self.payment.lease_security_deposit or self.payment.amount)} security deposit or rent commitment",
                    "form_document": "Escrow receipt and payment acknowledgment",
                    "required_information": "Tenant identity, lease reference, amount paid, payment method, and due date.",
                    "who_provides": "Tenant pays through AgriPlot.",
                    "who_files": "System-generated from payment confirmation.",
                    "system_output": "Tenant payment acknowledgment and landlord proof-of-funds notice.",
                },
                {
                    "stage": "4. Digital Lease Agreement",
                    "money_required": "Advocate or drafting costs if applicable",
                    "form_document": "Digitally confirmed lease agreement",
                    "required_information": "Term, notice period, good husbandry clause, subject-to-sale clause, and exit obligations.",
                    "who_provides": "Tenant and landlord both confirm digitally.",
                    "who_files": "AgriPlot stores the generated agreement and confirmation timestamps.",
                    "system_output": "Lease agreement certificate and compliance baseline.",
                },
                {
                    "stage": "5. Registry & Soil Baseline",
                    "money_required": (
                        f"{self.payment._money_display(self.payment.soil_baseline_fee_amount)} soil baseline / officer fee"
                    ),
                    "form_document": "Registry protection proof and soil baseline report",
                    "required_information": "Lease term, registry filing evidence, soil status, and entry condition notes.",
                    "who_provides": "AgriPlot-appointed officer or approved professional uploads the baseline and registry evidence.",
                    "who_files": "Professional report is uploaded before handover.",
                    "system_output": "Soil baseline certificate and long-lease protection evidence where required.",
                },
                {
                    "stage": "6. Handover & Occupation",
                    "money_required": "No extra money unless handover services were ordered",
                    "form_document": "Possession note / handover acknowledgment",
                    "required_information": "Access date, site condition, boundaries, keys or access points, and outstanding obligations.",
                    "who_provides": "Landlord or agent meets the tenant for handover.",
                    "who_files": "AgriPlot stores the signed handover note and activates the lease status.",
                    "system_output": "Active occupancy notice, public lease status card, and next-lease waitlist visibility.",
                },
                {
                    "stage": "7. Renewal or Exit",
                    "money_required": "Renewal fee only if a new term is agreed",
                    "form_document": "Renewal confirmation or exit soil report",
                    "required_information": "Renewal election, final notice date, soil exit result, and handback status.",
                    "who_provides": "Current tenant responds to reminders; landlord confirms renewal or exit.",
                    "who_files": "AgriPlot records reminders, exit proof, or renewal confirmation.",
                    "system_output": "Renewal notice trail, tenancy termination record, and automatic release for the next tenant if not renewed.",
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
                },
                {
                    "officer": "Survey Office / Licensed Surveyor",
                    "paid_by": "Buyer",
                    "fee": self.payment._money_display(self.payment.survey_search_fee),
                    "purpose": "Survey search, beacon alignment, or map verification.",
                    "release_rule": common_release,
                },
                {
                    "officer": "Land Control Board / Consent Processing",
                    "paid_by": "Seller",
                    "fee": self.payment._money_display(self.payment.lcb_fee_amount),
                    "purpose": "Consent-processing and statutory readiness costs.",
                    "release_rule": "Released after consent evidence and board reference are uploaded.",
                },
                {
                    "officer": "Government Valuer / Tax Workflow",
                    "paid_by": "Buyer",
                    "fee": self.payment._money_display(self.payment.purchase_stamp_duty_estimate),
                    "purpose": "Valuation-linked tax clearance and stamp-duty processing.",
                    "release_rule": "Released once the government valuation and tax receipt are captured.",
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
                },
                {
                    "officer": "Extension Officer / Soil Professional",
                    "paid_by": "Tenant or buyer of baseline service",
                    "fee": self.payment._money_display(self.payment.soil_baseline_fee_amount),
                    "purpose": "Soil baseline and exit-condition support.",
                    "release_rule": common_release,
                },
                {
                    "officer": "Registry / Lawyer",
                    "paid_by": "Parties as agreed",
                    "fee": "Varies by lease term",
                    "purpose": "Registry protection for leases exceeding two years.",
                    "release_rule": "Released after filing proof is uploaded and the step is approved.",
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
