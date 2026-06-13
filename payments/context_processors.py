from payments.models import PaymentRequest
from django.db.models import Q, Sum


def wallet_balance(request):
    """Add wallet balance to template context"""
    if request.user.is_authenticated:
        try:
            from .wallet_service import WalletService
            balance = WalletService.get_balance(request.user)
            return {
                'wallet_balance': balance['balance'],
                'wallet_available_balance': balance['available_balance'],
                'wallet_account_number': balance['account_number'],
            }
        except Exception as e:
            # Log error but don't break the page
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Wallet balance error: {e}")
            return {}
    return {}



def payment_notifications(request):
    """
    Context processor for payment-related notifications in the navbar.
    Shows pending payments and document verification status.
    """
    if not request.user.is_authenticated:
        return {}
    
    try:
        notifications = []
        
        # Check for payments awaiting action
        pending_payments = PaymentRequest.objects.filter(
            Q(buyer=request.user) | Q(seller=request.user),
            status='pending'
        ).count()
        
        if pending_payments > 0:
            notifications.append({
                'type': 'pending_payment',
                'message': f'You have {pending_payments} pending payment(s)',
                'url': '/payments/dashboard/',
                'icon': 'fa-credit-card',
            })
        
        # Check for unverified documents (if legal transaction exists)
        try:
            from transactions.models import Transaction
            legal_txs = Transaction.objects.filter(
                Q(buyer=request.user) | Q(seller=request.user),
                payment_request__isnull=False
            )
            
            for tx in legal_txs:
                pending_docs = tx.documents.filter(status='pending').count()
                if pending_docs > 0:
                    notifications.append({
                        'type': 'pending_documents',
                        'message': f'Legal documents awaiting verification for transaction #{tx.id}',
                        'url': f'/transactions/{tx.id}/',
                        'icon': 'fa-file-alt',
                    })
        except Exception:
            pass
        
        return {'payment_notifications': notifications[:5]}
        
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Payment notifications context processor error: {e}")
        return {}