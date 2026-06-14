from payments.models import PaymentRequest, PaymentClosingStep
from django.db.models import Q, Count, Sum, Case, When, Value, IntegerField
from django.utils import timezone
from datetime import timedelta


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
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Wallet balance error: {e}")
            return {}
    return {}


def payment_notifications(request):
    """
    Context processor for payment-related notifications in the navbar.
    Shows pending payments, escrow status, document verification, and stamp duty reminders.
    """
    if not request.user.is_authenticated:
        return {}
    
    try:
        notifications = []
        
        # 1. Check for payments awaiting action (pending payment)
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
                'priority': 1,
            })
        
        # 2. Check for payments that need stamp duty payment (KRA iTax)
        stamp_duty_pending = PaymentRequest.objects.filter(
            buyer=request.user,
            transaction_type=PaymentRequest.TransactionType.PURCHASE,
            status__in=['paid', 'in_escrow'],
            stamp_duty_receipt_verified_at__isnull=True
        )
        
        for payment in stamp_duty_pending:
            # Check if stamp duty step is the current step
            current_step = payment.current_assigned_step
            if current_step and current_step.code == 'stamp_duty':
                estimated_duty = payment.purchase_stamp_duty_estimate
                notifications.append({
                    'type': 'stamp_duty_required',
                    'message': f'Stamp duty payment required for {payment.title}. Pay directly to KRA via iTax (estimated: KES {estimated_duty:,.2f})',
                    'url': f'/payments/{payment.pk}/step/stamp_duty/',
                    'icon': 'fa-landmark',
                    'priority': 2,
                })
                break  # Only show one stamp duty notification
        
        # 3. Check for payments pending completion documents upload
        completion_docs_pending = PaymentRequest.objects.filter(
            seller=request.user,
            transaction_type=PaymentRequest.TransactionType.PURCHASE,
            status__in=['paid', 'in_escrow'],
            closing_steps__code='completion_docs',
            closing_steps__status=PaymentClosingStep.Status.PENDING
        ).distinct()
        
        for payment in completion_docs_pending[:3]:
            current_step = payment.current_assigned_step
            if current_step and current_step.code == 'completion_docs':
                notifications.append({
                    'type': 'completion_docs_required',
                    'message': f'Upload completion documents for {payment.title} (Title Deed, Transfer Forms)',
                    'url': f'/payments/{payment.pk}/step/completion_docs/',
                    'icon': 'fa-folder-open',
                    'priority': 3,
                })
        
        # 4. Check for payments pending fund disbursement (registration complete)
        pending_disbursement = PaymentRequest.objects.filter(
            Q(buyer=request.user) | Q(seller=request.user),
            transaction_type=PaymentRequest.TransactionType.PURCHASE,
            status='in_escrow',
            disbursed_at__isnull=True,
            closing_steps__code='registration',
            closing_steps__status=PaymentClosingStep.Status.COMPLETED
        ).distinct()
        
        for payment in pending_disbursement:
            if payment.seller == request.user:
                platform_fee = payment.platform_fee_amount
                seller_amount = payment.seller_net_amount
                notifications.append({
                    'type': 'pending_disbursement',
                    'message': f'Registration complete! Funds ready for disbursement. You will receive KES {seller_amount:,.2f} (after {payment.platform_fee_percentage * 100}% platform fee)',
                    'url': f'/payments/{payment.pk}/',
                    'icon': 'fa-money-bill-wave',
                    'priority': 4,
                })
            elif payment.buyer == request.user:
                notifications.append({
                    'type': 'pending_disbursement',
                    'message': f'Registration complete! Funds are being disbursed to the seller. Transaction report will be emailed to you.',
                    'url': f'/payments/{payment.pk}/',
                    'icon': 'fa-check-circle',
                    'priority': 4,
                })
        
        # 5. Check for payments pending handover
        handover_pending = PaymentRequest.objects.filter(
            seller=request.user,
            transaction_type=PaymentRequest.TransactionType.PURCHASE,
            status='released',
            disbursed_at__isnull=False,
            closing_steps__code='handover',
            closing_steps__status=PaymentClosingStep.Status.PENDING
        ).distinct()
        
        for payment in handover_pending[:2]:
            notifications.append({
                'type': 'handover_pending',
                'message': f'Arrange handover for {payment.title} to complete the transaction',
                'url': f'/payments/{payment.pk}/step/handover/',
                'icon': 'fa-handshake',
                'priority': 5,
            })
        
        # 6. Check for lease handover pending
        lease_handover = PaymentRequest.objects.filter(
            seller=request.user,
            transaction_type=PaymentRequest.TransactionType.LEASE,
            status__in=['paid', 'in_escrow'],
            closing_steps__code='handover',
            closing_steps__status=PaymentClosingStep.Status.PENDING
        ).distinct()
        
        for payment in lease_handover[:2]:
            notifications.append({
                'type': 'lease_handover_pending',
                'message': f'Complete handover for lease: {payment.title}',
                'url': f'/payments/{payment.pk}/step/handover/',
                'icon': 'fa-key',
                'priority': 6,
            })
        
        # 7. Check for unverified documents (if legal transaction exists)
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
                        'message': f'Legal documents awaiting verification for transaction #{tx.id} ({pending_docs} pending)',
                        'url': f'/transactions/{tx.id}/',
                        'icon': 'fa-file-alt',
                        'priority': 7,
                    })
        except Exception:
            pass
        
        # 8. Check for transaction reports ready
        reports_ready = PaymentRequest.objects.filter(
            Q(buyer=request.user) | Q(seller=request.user),
            disbursed_at__isnull=False,
            reports_sent_at__isnull=True
        ).count()
        
        if reports_ready > 0:
            notifications.append({
                'type': 'reports_ready',
                'message': f'Transaction report(s) are being prepared and will be emailed to you shortly',
                'url': '/payments/dashboard/',
                'icon': 'fa-file-pdf',
                'priority': 8,
            })
        
        # 9. Check for expired escrow holds (for admins)
        if request.user.is_staff or request.user.groups.filter(name='Finance Admin').exists():
            expired_escrow = PaymentRequest.objects.filter(
                status='in_escrow',
                created_at__lte=timezone.now() - timedelta(days=180),  # 6 months
                disbursed_at__isnull=True
            ).count()
            
            if expired_escrow > 0:
                notifications.append({
                    'type': 'expired_escrow',
                    'message': f'⚠️ {expired_escrow} payment(s) have been in escrow for over 6 months. Review required.',
                    'url': '/admin/payments/paymentrequest/',
                    'icon': 'fa-exclamation-triangle',
                    'priority': 0,  # Highest priority
                })
        
        # Sort notifications by priority
        notifications.sort(key=lambda x: x.get('priority', 99))
        
        # Count total unread notifications
        notification_count = len(notifications)
        
        return {
            'payment_notifications': notifications[:10],  # Limit to 10
            'payment_notification_count': notification_count,
        }
        
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Payment notifications context processor error: {e}")
        return {}


def escrow_summary(request):
    """
    Context processor for escrow summary dashboard.
    Shows total funds held in escrow for finance admins.
    """
    if not request.user.is_authenticated:
        return {}
    
    # Only show for finance admins or staff
    is_finance_admin = request.user.groups.filter(name='Finance Admin').exists() or request.user.is_staff
    
    if not is_finance_admin:
        return {}
    
    try:
        # Calculate total escrow holdings
        escrow_payments = PaymentRequest.objects.filter(
            status__in=['paid', 'in_escrow', 'partially_released'],
            disbursed_at__isnull=True
        )
        
        total_escrow_held = escrow_payments.aggregate(
            total=Sum('amount')
        )['total'] or 0
        
        # Count payments awaiting disbursement
        ready_for_disbursement = PaymentRequest.objects.filter(
            transaction_type=PaymentRequest.TransactionType.PURCHASE,
            status='in_escrow',
            disbursed_at__isnull=True,
            closing_steps__code='registration',
            closing_steps__status=PaymentClosingStep.Status.COMPLETED
        ).count()
        
        # Count pending stamp duty verifications
        pending_stamp_duty = PaymentRequest.objects.filter(
            transaction_type=PaymentRequest.TransactionType.PURCHASE,
            stamp_duty_receipt_verified_at__isnull=True,
            closing_steps__code='stamp_duty',
            closing_steps__status=PaymentClosingStep.Status.IN_PROGRESS
        ).count()
        
        return {
            'total_escrow_held': total_escrow_held,
            'escrow_payment_count': escrow_payments.count(),
            'ready_for_disbursement_count': ready_for_disbursement,
            'pending_stamp_duty_count': pending_stamp_duty,
        }
        
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Escrow summary context processor error: {e}")
        return {}


def platform_fees_summary(request):
    """
    Context processor for platform fees summary (for admin dashboard).
    Shows total platform fees earned.
    """
    if not request.user.is_authenticated:
        return {}
    
    # Only show for finance admins or staff
    is_finance_admin = request.user.groups.filter(name='Finance Admin').exists() or request.user.is_staff
    
    if not is_finance_admin:
        return {}
    
    try:
        # Calculate total platform fees earned from completed transactions
        completed_payments = PaymentRequest.objects.filter(
            disbursed_at__isnull=False,
            platform_fee_deducted_at__isnull=False
        )
        
        # Aggregate total platform fees
        # Note: platform_fee_amount is a property, so we need to calculate manually
        total_fees = 0
        for payment in completed_payments:
            total_fees += float(payment.platform_fee_amount)
        
        # Get current month's fees
        start_of_month = timezone.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        monthly_payments = completed_payments.filter(
            platform_fee_deducted_at__gte=start_of_month
        )
        
        monthly_fees = 0
        for payment in monthly_payments:
            monthly_fees += float(payment.platform_fee_amount)
        
        return {
            'total_platform_fees_earned': total_fees,
            'monthly_platform_fees': monthly_fees,
            'completed_transactions_count': completed_payments.count(),
        }
        
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Platform fees summary context processor error: {e}")
        return {}


def user_payment_statistics(request):
    """
    Context processor for user-specific payment statistics.
    Shows user's transaction history summary.
    """
    if not request.user.is_authenticated:
        return {}
    
    try:
        # Payments where user is buyer
        buyer_payments = PaymentRequest.objects.filter(buyer=request.user)
        
        # Payments where user is seller
        seller_payments = PaymentRequest.objects.filter(seller=request.user)
        
        # Calculate statistics
        statistics = {
            'total_purchases': buyer_payments.filter(
                transaction_type=PaymentRequest.TransactionType.PURCHASE
            ).count(),
            'total_leases': buyer_payments.filter(
                transaction_type=PaymentRequest.TransactionType.LEASE
            ).count(),
            'total_sales': seller_payments.filter(
                transaction_type=PaymentRequest.TransactionType.PURCHASE,
                disbursed_at__isnull=False
            ).count(),
            'total_leases_as_landlord': seller_payments.filter(
                transaction_type=PaymentRequest.TransactionType.LEASE,
                disbursed_at__isnull=False
            ).count(),
            'active_purchases': buyer_payments.filter(
                transaction_type=PaymentRequest.TransactionType.PURCHASE,
                status__in=['paid', 'in_escrow', 'partially_released'],
                disbursed_at__isnull=True
            ).count(),
            'active_leases': buyer_payments.filter(
                transaction_type=PaymentRequest.TransactionType.LEASE,
                status__in=['paid', 'in_escrow', 'partially_released'],
                disbursed_at__isnull=True
            ).count(),
        }
        
        return {
            'user_payment_stats': statistics,
        }
        
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"User payment statistics context processor error: {e}")
        return {}