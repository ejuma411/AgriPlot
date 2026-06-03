from django.db.models.signals import pre_save, post_save
from django.contrib.auth import get_user_model
from django.dispatch import receiver
from django.db.models import F
from decimal import Decimal
from .models import Wallet, WalletTransaction

User = get_user_model()

@receiver(post_save, sender=User)
def create_user_wallet(sender, instance, created, **kwargs):
    """Auto-create wallet for new users"""
    if created:
        Wallet.objects.get_or_create(user=instance, defaults={"balance": Decimal("0.00")})


@receiver(post_save, sender=WalletTransaction)
def sync_wallet_balance(sender, instance, created, **kwargs):
    """Keep the stored wallet balance aligned with successful transactions."""
    if instance.status != WalletTransaction.STATUS_SUCCESS:
        return
    if not created and getattr(instance, "_previous_status", None) == WalletTransaction.STATUS_SUCCESS:
        return

    delta = instance.amount if instance.type == WalletTransaction.TYPE_CREDIT else -instance.amount
    Wallet.objects.filter(pk=instance.wallet_id).update(balance=F("balance") + delta)


@receiver(pre_save, sender=WalletTransaction)
def capture_previous_transaction_status(sender, instance, **kwargs):
    """Remember the prior status so balance updates only happen on success transitions."""
    if not instance.pk:
        instance._previous_status = None
        return
    instance._previous_status = (
        WalletTransaction.objects.filter(pk=instance.pk)
        .values_list("status", flat=True)
        .first()
    )
