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


def user_can_update_specific_closing_step(user, payment, step):
    if not getattr(user, "is_authenticated", False):
        return PaymentDecision(False, "You need to sign in to update this step.")
    if user_is_finance_admin(user):
        return PaymentDecision(True)

    if step_requires_admin_action(step):
        return PaymentDecision(
            False,
            f"'{step.display_title}' is handled by AgriPlot admin or an appointed official and will appear in the admin task queue.",
        )

    active_step = payment.current_assigned_step
    if active_step and active_step.pk != step.pk and step.status != step.Status.COMPLETED:
        return PaymentDecision(
            False,
            f"Finish the current assigned step first: {active_step.display_title}.",
        )

    actor_is_buyer = user == payment.buyer
    actor_is_seller = user == payment.seller

    lcb_allowed = actor_is_buyer
    if payment.transaction_type == payment.TransactionType.LEASE:
        lcb_allowed = actor_is_seller

    allowed_map = {
        "due_diligence": actor_is_buyer,
        "offer": actor_is_buyer,
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

    return PaymentDecision(
        False,
        f"Only the assigned stakeholder or a finance admin can update '{step.title}'.",
    )


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
