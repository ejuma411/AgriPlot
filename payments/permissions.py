from dataclasses import dataclass


FINANCE_ADMIN_GROUP = "Finance Admin"


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
