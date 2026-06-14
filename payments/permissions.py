from dataclasses import dataclass
from decimal import Decimal


FINANCE_ADMIN_GROUP = "Finance Admin"
ESCROW_ADMIN_GROUP = "Escrow Admin"  # Manages fund disbursement
LEGAL_ADMIN_GROUP = "Legal Admin"    # Manages legal document verification

ADMIN_STEP_KEYWORDS = (
    "admin",
    "registrar",
    "operations",
    "lawyer",
    "valuer",
    "government",
    "officer",
    "surveyor",
    "registry",
    "advocate",      # Advocate verification
    "kra",           # KRA stamp duty verification
    "lands",         # Lands registry
)


@dataclass(frozen=True)
class PaymentDecision:
    allowed: bool
    reason: str = ""


def user_is_finance_admin(user):
    """Check if user is a finance admin (oversees payments but not escrow release)"""
    if not getattr(user, "is_authenticated", False):
        return False
    if user.is_superuser:
        return True
    return user.groups.filter(name=FINANCE_ADMIN_GROUP).exists()


def user_is_escrow_admin(user):
    """Check if user can authorize escrow fund releases (senior finance role)"""
    if not getattr(user, "is_authenticated", False):
        return False
    if user.is_superuser:
        return True
    return user.groups.filter(name=ESCROW_ADMIN_GROUP).exists() or user_is_finance_admin(user)


def user_is_legal_admin(user):
    """Check if user can verify legal documents (advocates, legal team)"""
    if not getattr(user, "is_authenticated", False):
        return False
    if user.is_superuser:
        return True
    return user.groups.filter(name=LEGAL_ADMIN_GROUP).exists() or user_is_finance_admin(user)


def user_is_advocate_for_transaction(user, legal_transaction):
    """Check if user is the assigned advocate for this transaction"""
    if not legal_transaction:
        return False
    assigned_advocate = getattr(legal_transaction, 'assigned_advocate', None)
    return assigned_advocate and user == assigned_advocate


def user_is_legal_participant(user, legal_transaction):
    """Check if user is a participant in the legal transaction"""
    if not legal_transaction:
        return False
    if user_is_legal_admin(user):
        return True
    if user_is_advocate_for_transaction(user, legal_transaction):
        return True
    return user == legal_transaction.buyer or user == legal_transaction.seller


def user_can_view_legal_transaction(user, legal_transaction):
    """Check if user can view the legal transaction"""
    if not legal_transaction:
        return False
    if user_is_legal_admin(user):
        return True
    if user_is_advocate_for_transaction(user, legal_transaction):
        return True
    return user == legal_transaction.buyer or user == legal_transaction.seller


def user_can_upload_legal_document(user, legal_transaction):
    """Check if user can upload documents to legal transaction"""
    if not legal_transaction:
        return False
    if user_is_legal_admin(user):
        return True
    if user_is_advocate_for_transaction(user, legal_transaction):
        return True
    return user == legal_transaction.buyer or user == legal_transaction.seller


def user_can_advance_legal_stage(user, legal_transaction):
    """Check if user can advance legal stage"""
    if not legal_transaction:
        return False
    if user_is_legal_admin(user):
        return True
    if user_is_advocate_for_transaction(user, legal_transaction):
        return True
    # Both buyer and seller can advance after all requirements are met
    return user == legal_transaction.buyer or user == legal_transaction.seller


def user_can_verify_legal_document(user, legal_transaction, document_type=None):
    """
    Check if user can verify legal documents.
    Different documents require different verifiers:
    - Official documents: Legal admin only
    - Advocate documents: Assigned advocate
    - KRA receipts: Finance or legal admin
    """
    if not legal_transaction:
        return False
    
    # KRA stamp duty receipts can be verified by finance admin
    if document_type == 'STAMP_DUTY_RECEIPT':
        return user_is_finance_admin(user) or user_is_legal_admin(user)
    
    # New title deed verification requires legal admin or advocate
    if document_type == 'NEW_TITLE_DEED':
        return user_is_legal_admin(user) or user_is_advocate_for_transaction(user, legal_transaction)
    
    # All other legal documents require legal admin or assigned advocate
    return user_is_legal_admin(user) or user_is_advocate_for_transaction(user, legal_transaction)


def user_can_authorize_escrow_disbursement(user, payment):
    """Check if user can authorize escrow fund release (critical security)"""
    if not getattr(user, "is_authenticated", False):
        return PaymentDecision(False, "You need to sign in to authorize disbursement.")
    
    if user_is_escrow_admin(user):
        return PaymentDecision(True)
    
    return PaymentDecision(
        False, 
        "Only escrow administrators can authorize fund disbursement. This is a security measure to protect both parties."
    )


def user_is_payment_participant(user, payment):
    if not getattr(user, "is_authenticated", False):
        return False
    if user_is_finance_admin(user):
        return True
    return user == payment.buyer or user == payment.seller


def user_can_create_payment(user):
    if not getattr(user, "is_authenticated", False):
        return PaymentDecision(False, "You need to sign in before creating payment requests.")
    if user_is_finance_admin(user):
        return PaymentDecision(True)

    profile = getattr(user, "profile", None)
    if profile and profile.role in {"buyer", "agent", "landowner", "admin"}:
        return PaymentDecision(True)
    return PaymentDecision(False, "Your account is not approved for payment request creation.")


def user_can_view_payment(user, payment):
    if user_is_payment_participant(user, payment):
        return PaymentDecision(True)
    if user_is_legal_admin(user):
        return PaymentDecision(True)
    return PaymentDecision(False, "You do not have access to this payment.")


def user_can_add_milestone(user, payment):
    if not getattr(user, "is_authenticated", False):
        return PaymentDecision(False, "You need to sign in to add milestones.")
    if user_is_finance_admin(user):
        return PaymentDecision(True)
    if user == payment.seller:
        return PaymentDecision(True)
    return PaymentDecision(False, "Only the seller or a finance admin can add milestones.")


def user_can_open_dispute(user, payment):
    if not getattr(user, "is_authenticated", False):
        return PaymentDecision(False, "You need to sign in to open disputes.")
    if user_is_payment_participant(user, payment):
        return PaymentDecision(True)
    return PaymentDecision(False, "Only payment participants or finance admins can open disputes.")


def user_can_update_closing_steps(user, payment):
    if not getattr(user, "is_authenticated", False):
        return PaymentDecision(False, "You need to sign in to update closing steps.")
    if user_is_finance_admin(user):
        return PaymentDecision(True)
    if user == payment.seller:
        return PaymentDecision(True)
    return PaymentDecision(
        False,
        "Only the seller or a finance admin can update the legal closing checklist.",
    )


def step_requires_admin_action(step):
    owner_label = (step.responsible_party_label or "").lower()
    return any(keyword in owner_label for keyword in ADMIN_STEP_KEYWORDS)


def step_requires_escrow_admin(step):
    """Check if step requires escrow admin authorization (funds release)"""
    return step.code in ["disbursement", "release", "funds_release"]


def step_requires_kra_verification(step):
    """Check if step requires KRA stamp duty verification"""
    return step.code == "stamp_duty"


def step_is_agreement_step(step):
    """Check if step is the agreement step (requires both parties)"""
    return step.code == "agreement"


def describe_payment_actor(user, payment):
    if not getattr(user, "is_authenticated", False):
        return "Guest"
    if user_is_escrow_admin(user):
        return "Escrow administrator"
    if user_is_finance_admin(user):
        return "Finance admin"
    if user == payment.buyer:
        return "Buyer / tenant"
    if user == payment.seller:
        return "Seller / landowner"
    return "Viewer"


def describe_legal_actor(user, legal_transaction):
    """Describe user's role in legal transaction"""
    if not getattr(user, "is_authenticated", False):
        return "Guest"
    if user_is_legal_admin(user):
        return "Legal admin / Document verifier"
    if user_is_finance_admin(user):
        return "Finance admin / Stamp duty verifier"
    if user_is_advocate_for_transaction(user, legal_transaction):
        return "Assigned advocate"
    if legal_transaction and user == legal_transaction.buyer:
        return "Buyer"
    if legal_transaction and user == legal_transaction.seller:
        return "Seller"
    return "Viewer"


def step_allowed_actor_labels(payment, step):
    """Get allowed actors for a specific step"""
    if step_requires_escrow_admin(step):
        return ["Escrow administrator", "Finance admin"]
    
    if step_requires_admin_action(step):
        return ["AgriPlot admin", "appointed advocate", "legal admin"]
    
    if step.code == "stamp_duty":
        return ["Buyer (pays directly to KRA)", "Finance admin (verifies receipt)"]
    
    if step.code == "due_diligence":
        return ["Buyer / tenant"]
    
    if step.code == "offer":
        return ["Buyer / tenant"]
    
    if step.code == "agreement":
        return ["Both Parties (buyer and seller)", "Their advocates"]
    
    if step.code == "completion_docs":
        return ["Both advocates"]
    
    if step.code == "registration":
        return ["Buyer advocate"]
    
    if step.code == "handover":
        return ["Seller / landowner"]
    
    if step.code == "lcb_consent":
        if payment.transaction_type == payment.TransactionType.LEASE:
            return ["Seller / landowner"]
        return ["Seller / landowner (obtains consent)"]
    
    if step.code == "disbursement":
        return ["Platform (automatic)", "Escrow admin (authorization)"]
    
    return [step.responsible_party_label or "Assigned stakeholder"]


def user_can_update_specific_closing_step(user, payment, step):
    """
    Check if user can update a specific closing step.
    Integrates with legal transaction requirements, escrow rules, and stamp duty.
    """
    if not getattr(user, "is_authenticated", False):
        return PaymentDecision(False, "You need to sign in to update this step.")
    
    # Escrow admin can handle disbursement steps
    if step_requires_escrow_admin(step):
        if user_is_escrow_admin(user):
            return PaymentDecision(True)
        return PaymentDecision(False, "Only escrow administrators can authorize fund disbursement.")
    
    # Finance admin can handle most steps
    if user_is_finance_admin(user):
        return PaymentDecision(True)
    
    # Check legal transaction requirements for purchase
    try:
        legal_tx = payment.legal_transaction
        if legal_tx and payment.transaction_type == payment.TransactionType.PURCHASE:
            # Map payment step to required legal stage
            step_to_legal_stage = {
                "due_diligence": "due_diligence",
                "offer": "offer_agreement",
                "agreement": "deposit",
                "lcb_consent": "statutory_consents",
                "stamp_duty": "stamp_duty",
                "completion_docs": "completion",
                "registration": "registration",
            }
            
            required_legal_stage = step_to_legal_stage.get(step.code)
            if required_legal_stage:
                from transactions.models import Transaction
                stage_order = [
                    'due_diligence', 
                    'offer_agreement', 
                    'deposit', 
                    'statutory_consents', 
                    'stamp_duty', 
                    'completion', 
                    'registration', 
                    'funds_disbursed',
                    'completed'
                ]
                
                if legal_tx.stage in stage_order and required_legal_stage in stage_order:
                    current_idx = stage_order.index(legal_tx.stage)
                    required_idx = stage_order.index(required_legal_stage)
                    
                    if current_idx < required_idx:
                        stage_display = dict(Transaction.Stage.choices).get(required_legal_stage, required_legal_stage)
                        return PaymentDecision(
                            False,
                            f"Cannot update '{step.display_title}' yet. Legal transaction must first complete "
                            f"'{stage_display}' stage. "
                            f"Current legal stage: '{dict(Transaction.Stage.choices).get(legal_tx.stage, legal_tx.stage)}'."
                        )
    except Exception:
        pass

    # Check if step requires admin action (advocate, government, etc.)
    if step_requires_admin_action(step):
        # Check if user is the assigned advocate for this transaction
        try:
            legal_tx = payment.legal_transaction
            if legal_tx and user_is_advocate_for_transaction(user, legal_tx):
                # Advocates can update certain admin steps
                advocate_allowed_steps = ["agreement", "lcb_consent", "registration", "completion_docs"]
                if step.code in advocate_allowed_steps:
                    return PaymentDecision(True)
        except Exception:
            pass
        
        return PaymentDecision(
            False,
            f"'{step.display_title}' can only be confirmed by AgriPlot admin, legal admin, or the appointed advocate handling this filing.",
        )

    # Check if this is the current active step
    active_step = payment.current_assigned_step
    if active_step and active_step.pk != step.pk and step.status != step.Status.COMPLETED:
        return PaymentDecision(
            False,
            f"This step is read-only for now. The only open task is '{active_step.display_title}'.",
        )

    actor_is_buyer = user == payment.buyer
    actor_is_seller = user == payment.seller

    # Special handling for LCB consent (different for purchase vs lease)
    lcb_allowed = actor_is_seller  # Seller obtains LCB consent
    if payment.transaction_type == payment.TransactionType.LEASE:
        lcb_allowed = actor_is_seller  # Landlord obtains consent

    # Permission map for standard steps (updated for new workflow)
    allowed_map = {
        "due_diligence": actor_is_buyer,
        "offer": actor_is_buyer,  # Buyer issues offer
        "agreement": actor_is_buyer or actor_is_seller,  # Both parties confirm
        "lcb_consent": lcb_allowed,
        "stamp_duty": actor_is_buyer,  # Buyer pays KRA directly
        "completion_docs": actor_is_buyer or actor_is_seller,  # Both advocates exchange
        "registration": actor_is_buyer or actor_is_seller,  # Buyer advocate registers
        "payment_security": actor_is_buyer,
        "lease_registration": actor_is_buyer or actor_is_seller,
        "soil_health_baseline": actor_is_buyer or actor_is_seller,
        "handover": actor_is_seller,
        "reports": True,  # System-generated, not user action
        "disbursement": False,  # Automatic or escrow admin only
    }
    
    if allowed_map.get(step.code, False):
        return PaymentDecision(True)

    actor_label = describe_payment_actor(user, payment)
    allowed_labels = ", ".join(step_allowed_actor_labels(payment, step))
    return PaymentDecision(
        False,
        f"You are signed in as {actor_label.lower()}. '{step.display_title}' is currently reserved for {allowed_labels.lower()}.",
    )


def user_can_start_inline_step_checkout(user, payment, step):
    if not getattr(user, "is_authenticated", False):
        return PaymentDecision(False, "You need to sign in before starting checkout.")
    
    if step.code not in {"payment_security", "agreement"}:
        return PaymentDecision(False, "Inline checkout is only available on payment steps.")
    
    if step.status == step.Status.COMPLETED:
        return PaymentDecision(False, "This checkout step is already complete.")
    
    active_step = payment.current_assigned_step
    if active_step and active_step.pk != step.pk:
        return PaymentDecision(
            False,
            f"Inline checkout is locked until the current open task '{active_step.display_title}' is complete.",
        )
    
    if user != payment.buyer:
        actor_label = describe_payment_actor(user, payment)
        return PaymentDecision(
            False,
            f"You are signed in as {actor_label.lower()}. Only the buyer can make payments.",
        )
    
    return PaymentDecision(True)


def user_can_transition_payment(user, payment, action):
    """
    Check if user can transition payment state.
    Actions: submit, cancel, dispute, mark_paid, move_escrow, partial_release, 
    release, refund, fail, disburse_to_seller
    """
    if not getattr(user, "is_authenticated", False):
        return PaymentDecision(False, "You need to sign in to update payments.")

    actor_is_finance = user_is_finance_admin(user)
    actor_is_escrow = user_is_escrow_admin(user)
    actor_is_buyer = user == payment.buyer
    actor_is_seller = user == payment.seller

    participant_actions = {
        "submit": actor_is_buyer,
        "cancel": actor_is_buyer,
        "dispute": actor_is_buyer or actor_is_seller,
    }
    
    finance_actions = {
        "mark_paid",
        "move_escrow",
        "partial_release",
        "fail",
    }
    
    escrow_actions = {
        "release",
        "refund",
        "disburse_to_seller",
    }

    if action in escrow_actions:
        if actor_is_escrow:
            # Check if all conditions met for disbursement
            if action == "disburse_to_seller":
                # Verify new title deed is uploaded and verified
                try:
                    legal_tx = payment.legal_transaction
                    if legal_tx:
                        from transactions.models import TransactionDocument
                        new_title_verified = TransactionDocument.objects.filter(
                            transaction=legal_tx,
                            document_type='NEW_TITLE_DEED',
                            status='verified'
                        ).exists()
                        
                        if not new_title_verified:
                            return PaymentDecision(
                                False,
                                "Cannot disburse funds to seller. New title deed must be uploaded and verified first."
                            )
                except Exception:
                    pass
            return PaymentDecision(True)
        return PaymentDecision(False, "Only escrow administrators can perform fund release actions.")

    if action in finance_actions:
        if actor_is_finance:
            return PaymentDecision(True)
        return PaymentDecision(False, "Only a finance admin can perform this payment action.")

    if action in participant_actions:
        if participant_actions[action]:
            return PaymentDecision(True)
        return PaymentDecision(False, "You are not allowed to perform this payment action.")

    return PaymentDecision(False, "Unsupported payment action.")


def user_can_advance_payment_step(user, payment, step):
    """
    Check if user can advance a payment step.
    Integrates with legal transaction requirements, document verification, and escrow rules.
    """
    if not getattr(user, "is_authenticated", False):
        return PaymentDecision(False, "You need to sign in to advance steps.")
    
    # Escrow admin can advance disbursement steps
    if step_requires_escrow_admin(step) and user_is_escrow_admin(user):
        return PaymentDecision(True)
    
    if user_is_finance_admin(user):
        return PaymentDecision(True)
    
    # Check legal transaction requirements for purchase
    try:
        legal_tx = payment.legal_transaction
        if legal_tx and payment.transaction_type == payment.TransactionType.PURCHASE:
            # Legal must be at required stage
            step_to_legal_stage = {
                "due_diligence": "due_diligence",
                "offer": "offer_agreement",
                "agreement": "deposit",
                "lcb_consent": "statutory_consents",
                "stamp_duty": "stamp_duty",
                "completion_docs": "completion",
                "registration": "registration",
            }
            
            required_legal_stage = step_to_legal_stage.get(step.code)
            if required_legal_stage:
                from transactions.models import Transaction
                stage_order = [
                    'due_diligence', 
                    'offer_agreement', 
                    'deposit', 
                    'statutory_consents', 
                    'stamp_duty', 
                    'completion', 
                    'registration', 
                    'funds_disbursed',
                    'completed'
                ]
                
                if legal_tx.stage in stage_order and required_legal_stage in stage_order:
                    current_idx = stage_order.index(legal_tx.stage)
                    required_idx = stage_order.index(required_legal_stage)
                    
                    if current_idx < required_idx:
                        stage_display = dict(Transaction.Stage.choices).get(required_legal_stage, required_legal_stage)
                        return PaymentDecision(
                            False,
                            f"Cannot advance payment step '{step.display_title}'. Legal transaction must first reach "
                            f"'{stage_display}' stage."
                        )
    except Exception:
        pass
    
    # Check if user has permission for this step
    decision = user_can_update_specific_closing_step(user, payment, step)
    if not decision.allowed:
        return decision
    
    # Special check for stamp duty: Verify KRA payment receipt
    if step.code == "stamp_duty":
        try:
            legal_tx = payment.legal_transaction
            if legal_tx:
                from transactions.models import TransactionDocument
                stamp_duty_receipt = TransactionDocument.objects.filter(
                    transaction=legal_tx,
                    document_type='STAMP_DUTY_RECEIPT',
                    status='verified'
                ).exists()
                
                if not stamp_duty_receipt:
                    return PaymentDecision(
                        False,
                        "Cannot advance to stamp duty step. Please pay stamp duty directly to KRA via iTax "
                        "and upload the payment receipt for verification."
                    )
        except Exception:
            pass
    
    # Check if all required legal documents are verified for this step
    try:
        legal_tx = payment.legal_transaction
        if legal_tx and payment.transaction_type == payment.TransactionType.PURCHASE:
            from transactions.models import TransactionDocument
            
            # Map payment step to required legal documents
            step_to_docs = {
                "due_diligence": ["OFFICIAL_SEARCH", "SURVEY_MAP"],
                "offer": ["LETTER_OF_OFFER"],
                "agreement": ["SALE_AGREEMENT"],
                "lcb_consent": ["LCB_CONSENT", "SPOUSAL_CONSENT", "LAND_RATES", "LAND_RENT"],
                "stamp_duty": ["STAMP_DUTY_RECEIPT"],
                "completion_docs": ["TRANSFER_FORM", "ORIGINAL_TITLE_DEED"],
                "registration": ["NEW_TITLE_DEED"],
            }
            
            required_docs = step_to_docs.get(step.code, [])
            missing_docs = []
            
            for doc_type in required_docs:
                has_doc = TransactionDocument.objects.filter(
                    transaction=legal_tx,
                    document_type=doc_type,
                    status='verified'
                ).exists()
                if not has_doc:
                    doc_name = dict(TransactionDocument.DocType.choices).get(doc_type, doc_type)
                    missing_docs.append(doc_name)
            
            if missing_docs:
                return PaymentDecision(
                    False,
                    f"Cannot advance payment step. Missing verified legal documents: {', '.join(missing_docs)}. "
                    "Please upload and verify these documents in the Legal Workspace first."
                )
    except Exception:
        pass
    
    # Special check for registration: Verify new title deed before allowing
    if step.code == "registration":
        try:
            legal_tx = payment.legal_transaction
            if legal_tx:
                from transactions.models import TransactionDocument
                new_title = TransactionDocument.objects.filter(
                    transaction=legal_tx,
                    document_type='NEW_TITLE_DEED',
                    status='verified'
                ).exists()
                
                if not new_title:
                    return PaymentDecision(
                        False,
                        "Cannot complete registration step. New title deed must be issued by the land registry "
                        "and uploaded for verification first."
                    )
        except Exception:
            pass
    
    return PaymentDecision(True)


def user_can_verify_stamp_duty_receipt(user, payment):
    """
    Special permission for verifying KRA stamp duty receipts.
    This is critical because platform never touches stamp duty funds.
    """
    if not getattr(user, "is_authenticated", False):
        return PaymentDecision(False, "You need to sign in to verify stamp duty receipts.")
    
    # Finance admin can verify KRA receipts
    if user_is_finance_admin(user):
        return PaymentDecision(True)
    
    # Legal admin can also verify
    if user_is_legal_admin(user):
        return PaymentDecision(True)
    
    return PaymentDecision(
        False,
        "Only finance or legal administrators can verify KRA stamp duty receipts."
    )


def user_can_authorize_platform_fee_deduction(user, payment):
    """
    Check if user can authorize platform fee deduction before disbursement.
    Platform fee is deducted from seller's proceeds BEFORE final payment.
    """
    if not getattr(user, "is_authenticated", False):
        return PaymentDecision(False, "You need to sign in to authorize fee deduction.")
    
    if user_is_escrow_admin(user):
        return PaymentDecision(True)
    
    return PaymentDecision(
        False,
        "Only escrow administrators can authorize platform fee deduction."
    )


def get_user_accessible_payments(user):
    """
    Returns a queryset of payments the user can access.
    Used for dashboard filtering.
    """
    from django.db import models
    from .models import PaymentRequest
    
    if not user.is_authenticated:
        return PaymentRequest.objects.none()
    
    if user_is_finance_admin(user) or user_is_escrow_admin(user):
        return PaymentRequest.objects.all()
    
    return PaymentRequest.objects.filter(
        models.Q(buyer=user) | models.Q(seller=user)
    )