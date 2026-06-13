from dataclasses import dataclass


FINANCE_ADMIN_GROUP = "Finance Admin"
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
)


@dataclass(frozen=True)
class PaymentDecision:
    allowed: bool
    reason: str = ""


def user_is_finance_admin(user):
    if not getattr(user, "is_authenticated", False):
        return False
    if user.is_superuser:
        return True
    return user.groups.filter(name=FINANCE_ADMIN_GROUP).exists()


def user_is_legal_participant(user, legal_transaction):
    """Check if user is a participant in the legal transaction"""
    if not legal_transaction:
        return False
    if user_is_finance_admin(user):
        return True
    return user == legal_transaction.buyer or user == legal_transaction.seller


def user_can_view_legal_transaction(user, legal_transaction):
    """Check if user can view the legal transaction"""
    if not legal_transaction:
        return False
    if user_is_finance_admin(user):
        return True
    return user == legal_transaction.buyer or user == legal_transaction.seller


def user_can_upload_legal_document(user, legal_transaction):
    """Check if user can upload documents to legal transaction"""
    if not legal_transaction:
        return False
    if user_is_finance_admin(user):
        return True
    return user == legal_transaction.buyer or user == legal_transaction.seller


def user_can_advance_legal_stage(user, legal_transaction):
    """Check if user can advance legal stage"""
    if not legal_transaction:
        return False
    if user_is_finance_admin(user):
        return True
    # Both buyer and seller can advance after all requirements are met
    return user == legal_transaction.buyer or user == legal_transaction.seller


def user_can_verify_legal_document(user, legal_transaction):
    """Check if user can verify legal documents (admin only)"""
    return user_is_finance_admin(user)


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


def describe_payment_actor(user, payment):
    if not getattr(user, "is_authenticated", False):
        return "Guest"
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
    if user_is_finance_admin(user):
        return "Finance admin / Legal reviewer"
    if legal_transaction and user == legal_transaction.buyer:
        return "Buyer"
    if legal_transaction and user == legal_transaction.seller:
        return "Seller"
    return "Viewer"


def step_allowed_actor_labels(payment, step):
    if step_requires_admin_action(step):
        return ["AgriPlot admin / appointed advocate"]

    if step.code in {"due_diligence", "stamp_duty", "completion_docs", "registration", "payment_security"}:
        return ["Buyer / tenant"]
    if step.code in {"offer", "commitment"}:
        return ["Buyer / seller", "Buyer advocate", "Seller advocate"]
    if step.code == "handover":
        return ["Seller / landowner"]
    if step.code in {"agreement", "lease_registration", "soil_health_baseline"}:
        return ["Buyer / tenant", "Seller / landowner"]
    if step.code == "lcb_consent":
        if payment.transaction_type == payment.TransactionType.LEASE:
            return ["Seller / landowner"]
        return ["Buyer / tenant"]
    return [step.responsible_party_label or "Assigned stakeholder"]


def user_can_update_specific_closing_step(user, payment, step):
    if not getattr(user, "is_authenticated", False):
        return PaymentDecision(False, "You need to sign in to update this step.")
    if user_is_finance_admin(user):
        return PaymentDecision(True)

    # Check legal transaction requirements first
    try:
        legal_tx = payment.legal_transaction
        if legal_tx and payment.transaction_type == payment.TransactionType.PURCHASE:
            # Map payment step to required legal stage
            step_to_legal_stage = {
                "due_diligence": "due_diligence",
                "offer": "commitment",
                "commitment": "commitment",
                "agreement": "contracts",
                "lcb_consent": "statutory_consents",
                "stamp_duty": "taxation",
                "registration": "registration",
            }
            
            required_legal_stage = step_to_legal_stage.get(step.code)
            if required_legal_stage:
                from transactions.models import Transaction
                stage_order = ['due_diligence', 'commitment', 'contracts', 'statutory_consents', 'taxation', 'registration']
                
                if legal_tx.stage in stage_order and required_legal_stage in stage_order:
                    current_idx = stage_order.index(legal_tx.stage)
                    required_idx = stage_order.index(required_legal_stage)
                    
                    if current_idx < required_idx:
                        return PaymentDecision(
                            False,
                            f"Cannot update '{step.display_title}' yet. Legal transaction must first complete "
                            f"'{dict(Transaction.Stage.choices).get(required_legal_stage)}' stage. "
                            f"Current legal stage: '{dict(Transaction.Stage.choices).get(legal_tx.stage)}'."
                        )
    except Exception:
        pass

    if step_requires_admin_action(step):
        return PaymentDecision(
            False,
            f"'{step.display_title}' can only be confirmed by AgriPlot admin or the appointed advocate / official handling this filing.",
        )

    active_step = payment.current_assigned_step
    if active_step and active_step.pk != step.pk and step.status != step.Status.COMPLETED:
        return PaymentDecision(
            False,
            f"This step is read-only for now. The only open task is '{active_step.display_title}'.",
        )

    actor_is_buyer = user == payment.buyer
    actor_is_seller = user == payment.seller

    lcb_allowed = actor_is_buyer
    if payment.transaction_type == payment.TransactionType.LEASE:
        lcb_allowed = actor_is_seller

    allowed_map = {
        "due_diligence": actor_is_buyer,
        "offer": actor_is_buyer or actor_is_seller,
        "commitment": actor_is_buyer or actor_is_seller,
        "agreement": actor_is_buyer or actor_is_seller,
        "lcb_consent": lcb_allowed,
        "stamp_duty": actor_is_buyer,
        "completion_docs": actor_is_buyer,
        "registration": actor_is_buyer,
        "payment_security": actor_is_buyer,
        "lease_registration": actor_is_buyer or actor_is_seller,
        "soil_health_baseline": actor_is_buyer or actor_is_seller,
        "handover": actor_is_seller,
    }
    if allowed_map.get(step.code, False):
        return PaymentDecision(True)

    actor_label = describe_payment_actor(user, payment)
    allowed_labels = ", ".join(step_allowed_actor_labels(payment, step))
    return PaymentDecision(
        False,
        f"You are signed in as {actor_label.lower()}. '{step.display_title}' is currently reserved for {allowed_labels.lower()} or a finance admin.",
    )


def user_can_start_inline_step_checkout(user, payment, step):
    if not getattr(user, "is_authenticated", False):
        return PaymentDecision(False, "You need to sign in before starting checkout.")
    if step.code != "payment_security":
        return PaymentDecision(False, "Inline checkout is only available on the security deposit step.")
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
            f"You are signed in as {actor_label.lower()}. Only the buyer / tenant can start the security-deposit checkout.",
        )
    return PaymentDecision(True)


def user_can_transition_payment(user, payment, action):
    if not getattr(user, "is_authenticated", False):
        return PaymentDecision(False, "You need to sign in to update payments.")

    actor_is_finance = user_is_finance_admin(user)
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
        "release",
        "refund",
        "fail",
    }

    if action in finance_actions:
        if actor_is_finance:
            return PaymentDecision(True)
        return PaymentDecision(False, "Only a finance admin can perform this payment action.")

    if action in participant_actions:
        if participant_actions[action] or actor_is_finance:
            return PaymentDecision(True)
        return PaymentDecision(False, "You are not allowed to perform this payment action.")

    return PaymentDecision(False, "Unsupported payment action.")


def user_can_advance_payment_step(user, payment, step):
    """
    Check if user can advance a payment step.
    This integrates with legal transaction requirements.
    """
    if not getattr(user, "is_authenticated", False):
        return PaymentDecision(False, "You need to sign in to advance steps.")
    
    if user_is_finance_admin(user):
        return PaymentDecision(True)
    
    # Check legal transaction requirements
    try:
        legal_tx = payment.legal_transaction
        if legal_tx and payment.transaction_type == payment.TransactionType.PURCHASE:
            # Legal must be at required stage
            step_to_legal_stage = {
                "due_diligence": "due_diligence",
                "offer": "commitment",
                "commitment": "commitment",
                "agreement": "contracts",
                "lcb_consent": "statutory_consents",
                "stamp_duty": "taxation",
                "registration": "registration",
            }
            
            required_legal_stage = step_to_legal_stage.get(step.code)
            if required_legal_stage:
                from transactions.models import Transaction
                stage_order = ['due_diligence', 'commitment', 'contracts', 'statutory_consents', 'taxation', 'registration']
                
                if legal_tx.stage in stage_order and required_legal_stage in stage_order:
                    current_idx = stage_order.index(legal_tx.stage)
                    required_idx = stage_order.index(required_legal_stage)
                    
                    if current_idx < required_idx:
                        return PaymentDecision(
                            False,
                            f"Cannot advance payment step '{step.display_title}'. Legal transaction must first reach "
                            f"'{dict(Transaction.Stage.choices).get(required_legal_stage)}' stage."
                        )
    except Exception:
        pass
    
    # Check if user has permission for this step
    decision = user_can_update_specific_closing_step(user, payment, step)
    if not decision.allowed:
        return decision
    
    # Check if all required legal documents are verified
    try:
        legal_tx = payment.legal_transaction
        if legal_tx and payment.transaction_type == payment.TransactionType.PURCHASE:
            from transactions.models import TransactionDocument
            
            # Map payment step to required legal documents
            step_to_docs = {
                "due_diligence": ["OFFICIAL_SEARCH", "SURVEY_MAP"],
                "offer": ["LETTER_OF_OFFER"],
                "commitment": ["LETTER_OF_OFFER"],
                "agreement": ["SALE_AGREEMENT"],
                "lcb_consent": ["LCB_CONSENT", "SPOUSAL_CONSENT"],
                "stamp_duty": ["STAMP_DUTY_RECEIPT", "VALUATION_REPORT"],
                "registration": ["NEW_TITLE_DEED", "TRANSFER_FORM"],
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
                    missing_docs.append(dict(TransactionDocument.DocType.choices).get(doc_type, doc_type))
            
            if missing_docs:
                return PaymentDecision(
                    False,
                    f"Cannot advance payment step. Missing verified legal documents: {', '.join(missing_docs)}. "
                    "Please upload and verify these documents in the Legal Workspace first."
                )
    except Exception:
        pass
    
    return PaymentDecision(True)
