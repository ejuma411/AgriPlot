from payments.models import PaymentClosingStep, PaymentRequest
from payments.permissions import step_requires_admin_action, user_is_finance_admin


def payment_admin_nav(request):
    user = getattr(request, "user", None)
    if not user_is_finance_admin(user):
        return {
            "show_payment_admin_nav": False,
            "payment_admin_task_count": 0,
        }

    payment_queryset = (
        PaymentRequest.objects.prefetch_related("closing_steps")
        .filter(
            transaction_type__in=[
                PaymentRequest.TransactionType.PURCHASE,
                PaymentRequest.TransactionType.LEASE,
            ]
        )
        .exclude(
            status__in=[
                PaymentRequest.Status.REFUNDED,
                PaymentRequest.Status.CANCELLED,
                PaymentRequest.Status.FAILED,
            ]
        )
    )

    task_count = 0
    for payment in payment_queryset:
        for step in payment.closing_steps.exclude(
            status=PaymentClosingStep.Status.COMPLETED
        ):
            if step_requires_admin_action(step):
                task_count += 1

    return {
        "show_payment_admin_nav": True,
        "payment_admin_task_count": task_count,
    }
