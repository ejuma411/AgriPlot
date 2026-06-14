import logging
from datetime import datetime

from django.core.cache import cache
from django.utils import timezone

from .lease_lifecycle import process_lease_lifecycle
from .models import PaymentRequest, PaymentClosingStep

logger = logging.getLogger(__name__)


class LeaseLifecycleHeartbeatMiddleware:
    """
    Run the lease lifecycle processor opportunistically during app traffic.

    This is a lightweight safety net for expiry flips and queue notices between
    scheduled command runs.
    
    Extended to also handle:
    - Automatic fund disbursement checks for purchase transactions
    - Stamp duty verification reminders
    - Transaction report generation for completed deals
    """

    CACHE_KEY = "payments:lease_lifecycle:heartbeat"
    THROTTLE_SECONDS = 300  # 5 minutes

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if cache.add(self.CACHE_KEY, "1", self.THROTTLE_SECONDS):
            try:
                # Process lease lifecycle (existing)
                process_lease_lifecycle()
                
                # Process purchase escrow checks
                self._process_escrow_checks()
                
                # Process pending disbursements
                self._process_pending_disbursements()
                
                # Process stamp duty reminders
                self._process_stamp_duty_reminders()
                
                # Process report generation for completed transactions
                self._process_pending_reports()
                
            except Exception:
                logger.exception("Lease lifecycle heartbeat failed")
        
        return self.get_response(request)
    
    def _process_escrow_checks(self):
        """
        Check for purchase transactions that have completed registration
        but haven't been disbursed yet. Trigger automatic disbursement.
        """
        # Find purchase transactions with registration complete but not disbursed
        ready_for_disbursement = PaymentRequest.objects.filter(
            transaction_type=PaymentRequest.TransactionType.PURCHASE,
            status=PaymentRequest.Status.IN_ESCROW,  # Still in escrow
            disbursed_at__isnull=True,  # Not yet disbursed
        )
        
        for payment in ready_for_disbursement:
            # Check if registration step is completed
            registration_step = payment.closing_steps.filter(
                code="registration",
                status=PaymentClosingStep.Status.COMPLETED
            ).first()
            
            # Check if stamp duty is verified
            stamp_duty_step = payment.closing_steps.filter(
                code="stamp_duty",
                status=PaymentClosingStep.Status.COMPLETED
            ).first()
            
            # Check if both deposit and balance are in escrow
            deposit_paid = payment.metadata.get('deposit_paid', False)
            balance_paid = payment.metadata.get('balance_paid', False)
            
            if (registration_step and stamp_duty_step and 
                deposit_paid and balance_paid and 
                not payment.disbursed_at):
                
                logger.info(
                    f"Middleware: Found payment {payment.internal_reference} ready for disbursement. "
                    f"Registration complete, stamp duty verified, funds in escrow. Triggering disbursement."
                )
                
                try:
                    # Trigger disbursement
                    payment.apply_transition(
                        "disburse_to_seller", 
                        actor=None  # System action
                    )
                    logger.info(f"Middleware: Successfully triggered disbursement for {payment.internal_reference}")
                except Exception as e:
                    logger.error(
                        f"Middleware: Failed to disburse funds for {payment.internal_reference}: {str(e)}"
                    )
    
    def _process_pending_disbursements(self):
        """
        Process payments that have been marked for disbursement but not yet completed.
        This handles edge cases where external bank transfer might be pending.
        """
        # Find payments that have been released but not fully disbursed
        pending_disbursements = PaymentRequest.objects.filter(
            status=PaymentRequest.Status.RELEASED,
            disbursed_at__isnull=True,
        ).exclude(
            transaction_type=PaymentRequest.TransactionType.PURCHASE
        )  # Purchases handled separately in _process_escrow_checks
        
        for payment in pending_disbursements:
            logger.info(
                f"Middleware: Processing pending disbursement for {payment.internal_reference}"
            )
            
            try:
                # Calculate platform fee
                platform_fee = payment.platform_fee_amount
                seller_amount = payment.seller_net_amount
                
                # Mark as disbursed
                payment.disbursed_at = timezone.now()
                payment.platform_fee_deducted_at = timezone.now()
                payment.save(update_fields=['disbursed_at', 'platform_fee_deducted_at', 'updated_at'])
                
                logger.info(
                    f"Middleware: Disbursed funds for {payment.internal_reference}: "
                    f"Platform fee: {platform_fee}, Seller receives: {seller_amount}"
                )
                
                # Update disbursement records
                self._update_disbursement_records(payment, platform_fee, seller_amount)
                
            except Exception as e:
                logger.error(
                    f"Middleware: Failed to process disbursement for {payment.internal_reference}: {str(e)}"
                )
    
    def _process_stamp_duty_reminders(self):
        """
        Send reminders for pending stamp duty payments.
        Stamp duty must be paid directly to KRA via iTax.
        """
        # Find purchase transactions that are at stamp duty stage
        pending_stamp_duty = PaymentRequest.objects.filter(
            transaction_type=PaymentRequest.TransactionType.PURCHASE,
            status__in=[
                PaymentRequest.Status.PAID,
                PaymentRequest.Status.IN_ESCROW,
                PaymentRequest.Status.PARTIALLY_RELEASED,
            ],
            stamp_duty_receipt_verified_at__isnull=True,
        )
        
        for payment in pending_stamp_duty:
            # Check if the current step is stamp duty
            current_step = payment.current_assigned_step
            if current_step and current_step.code == "stamp_duty":
                # Check if we've sent a reminder recently
                last_reminder = payment.metadata.get('stamp_duty_last_reminder_at')
                if last_reminder:
                    # Parse datetime from ISO string
                    try:
                        last_reminder_dt = datetime.fromisoformat(last_reminder)
                        if timezone.is_naive(last_reminder_dt):
                            last_reminder_dt = timezone.make_aware(last_reminder_dt)
                    except (ValueError, TypeError):
                        last_reminder_dt = None
                    
                    # Only send reminder every 7 days
                    if last_reminder_dt and (timezone.now() - last_reminder_dt).days < 7:
                        continue
                
                # Send reminder notification
                self._send_stamp_duty_reminder(payment)
                
                # Update last reminder timestamp
                payment.metadata['stamp_duty_last_reminder_at'] = timezone.now().isoformat()
                payment.save(update_fields=['metadata', 'updated_at'])
                
                logger.info(
                    f"Middleware: Sent stamp duty reminder for {payment.internal_reference}"
                )
    
    def _process_pending_reports(self):
        """
        Generate and send transaction reports for completed transactions
        that haven't had reports sent yet.
        """
        from notifications.notification_service import NotificationService
        
        # Find completed payments without reports sent
        pending_reports = PaymentRequest.objects.filter(
            disbursed_at__isnull=False,
            reports_sent_at__isnull=True,
        )
        
        for payment in pending_reports:
            logger.info(
                f"Middleware: Generating transaction reports for {payment.internal_reference}"
            )
            
            try:
                # Generate and send reports
                NotificationService.send_transaction_completion_reports(payment)
                
                # Mark reports as sent
                payment.reports_sent_at = timezone.now()
                payment.save(update_fields=['reports_sent_at', 'updated_at'])
                
                logger.info(
                    f"Middleware: Transaction reports sent for {payment.internal_reference}"
                )
                
            except Exception as e:
                logger.error(
                    f"Middleware: Failed to send reports for {payment.internal_reference}: {str(e)}"
                )
    
    def _update_disbursement_records(self, payment, platform_fee, seller_amount):
        """Update PaymentDisbursement records to RELEASED status"""
        from .models import PaymentDisbursement
        
        # Update platform fee disbursement
        platform_disbursement = payment.disbursements.filter(code="platform_fee").first()
        if platform_disbursement and platform_disbursement.status != PaymentDisbursement.Status.RELEASED:
            platform_disbursement.status = PaymentDisbursement.Status.RELEASED
            platform_disbursement.released_at = timezone.now()
            platform_disbursement.save(update_fields=['status', 'released_at', 'updated_at'])
            logger.info(f"Platform fee disbursement recorded: KES {platform_fee:,.2f}")
        
        # Update seller disbursement
        seller_disbursement = payment.disbursements.filter(code="seller_disbursement").first()
        if seller_disbursement and seller_disbursement.status != PaymentDisbursement.Status.RELEASED:
            seller_disbursement.status = PaymentDisbursement.Status.RELEASED
            seller_disbursement.released_at = timezone.now()
            seller_disbursement.save(update_fields=['status', 'released_at', 'updated_at'])
            logger.info(f"Seller disbursement recorded: KES {seller_amount:,.2f}")
    
    def _send_stamp_duty_reminder(self, payment):
        """Send reminder to buyer to pay stamp duty to KRA"""
        from notifications.notification_service import NotificationService
        
        if payment.buyer:
            # Calculate estimated stamp duty
            estimated_duty = payment.purchase_stamp_duty_estimate
            rate = "2%" if payment.plot and payment.plot.market_zone == "rural" else "4%"
            
            NotificationService.create_notification(
                user=payment.buyer,
                notification_type="stamp_duty_reminder",
                title="Stamp Duty Payment Required",
                message=(
                    f"Please pay stamp duty for {payment.title} directly to KRA via iTax. "
                    f"Estimated amount: KES {estimated_duty:,.2f} ({rate} of property value). "
                    f"After payment, upload the receipt on AgriPlot for verification."
                ),
            )
            
            # Send email reminder
            NotificationService.send_email(
                recipient=payment.buyer.email,
                subject=f"Stamp Duty Payment Required - {payment.title}",
                template="notifications/emails/stamp_duty_reminder",
                context={
                    "payment": payment,
                    "estimated_duty": estimated_duty,
                    "rate": rate,
                    "kra_link": "https://itax.kra.go.ke",
                }
            )


class EscrowAuditMiddleware:
    """
    Middleware to log all escrow-related actions for audit purposes.
    This helps track fund movements for compliance.
    """
    
    def __init__(self, get_response):
        self.get_response = get_response
    
    def __call__(self, request):
        response = self.get_response(request)
        
        # Log escrow-related actions after response
        if hasattr(request, 'user') and request.user.is_authenticated:
            self._log_escrow_action(request)
        
        return response
    
    def _log_escrow_action(self, request):
        """Log escrow-related actions from the request"""
        # Check if this request modified escrow funds
        escrow_paths = [
            '/payments/',
            '/api/payments/',
            '/escrow/',
        ]
        
        if any(path in request.path for path in escrow_paths):
            if request.method in ['POST', 'PUT', 'PATCH', 'DELETE']:
                logger.info(
                    f"Escrow audit: User {request.user.username} ({request.user.id}) "
                    f"made {request.method} request to {request.path}"
                )


class TransactionComplianceMiddleware:
    """
    Middleware to ensure transaction compliance:
    - Verify stamp duty receipts are not stale
    - Check for incomplete transactions
    - Flag suspicious patterns
    """
    
    CACHE_KEY = "payments:compliance:check"
    THROTTLE_SECONDS = 3600  # 1 hour
    
    def __init__(self, get_response):
        self.get_response = get_response
    
    def __call__(self, request):
        if cache.add(self.CACHE_KEY, "1", self.THROTTLE_SECONDS):
            try:
                self._check_stale_stamp_duty_receipts()
                self._check_abandoned_transactions()
            except Exception:
                logger.exception("Transaction compliance check failed")
        
        return self.get_response(request)
    
    def _check_stale_stamp_duty_receipts(self):
        """
        Check for stamp duty receipts that are about to expire.
        Stamp duty assessments are valid for 30 days only.
        """
        from datetime import timedelta
        
        # Find payments with stamp duty step pending for > 25 days
        stale_deadline = timezone.now() - timedelta(days=25)
        
        stale_payments = PaymentRequest.objects.filter(
            transaction_type=PaymentRequest.TransactionType.PURCHASE,
            created_at__lte=stale_deadline,
            stamp_duty_receipt_verified_at__isnull=True,
            status__in=[
                PaymentRequest.Status.PAID,
                PaymentRequest.Status.IN_ESCROW,
            ]
        )
        
        for payment in stale_payments:
            # Check if stamp duty step is still pending
            stamp_duty_step = payment.closing_steps.filter(code="stamp_duty").first()
            if stamp_duty_step and stamp_duty_step.status != PaymentClosingStep.Status.COMPLETED:
                logger.warning(
                    f"Compliance: Stamp duty pending for {payment.internal_reference} for over 25 days. "
                    f"Created at: {payment.created_at}"
                )
                
                # Send escalation notification
                self._send_compliance_alert(payment, "stamp_duty_stale")
    
    def _check_abandoned_transactions(self):
        """
        Check for transactions that have been abandoned for too long.
        """
        from datetime import timedelta
        
        # Transactions with no activity for 90 days
        abandoned_deadline = timezone.now() - timedelta(days=90)
        
        abandoned_payments = PaymentRequest.objects.filter(
            updated_at__lte=abandoned_deadline,
            status__in=[
                PaymentRequest.Status.PENDING,
                PaymentRequest.Status.PAID,
                PaymentRequest.Status.IN_ESCROW,
            ],
            disbursed_at__isnull=True,
        )
        
        for payment in abandoned_payments:
            logger.warning(
                f"Compliance: Abandoned transaction detected for {payment.internal_reference}. "
                f"Last updated: {payment.updated_at}. Status: {payment.status}"
            )
            
            # Send alert to finance admin
            self._send_compliance_alert(payment, "abandoned_transaction")
    
    def _send_compliance_alert(self, payment, alert_type):
        """Send compliance alert to finance admins"""
        from notifications.notification_service import NotificationService
        from .permissions import FINANCE_ADMIN_GROUP
        from django.contrib.auth.models import Group
        
        # Get finance admins
        finance_admins = Group.objects.get(name=FINANCE_ADMIN_GROUP).users.all()
        
        alert_messages = {
            "stamp_duty_stale": (
                f"Stamp duty payment pending for over 25 days for {payment.internal_reference}. "
                f"Buyer: {payment.buyer.email if payment.buyer else 'N/A'}. "
                f"Amount: KES {payment.amount:,.2f}"
            ),
            "abandoned_transaction": (
                f"Transaction {payment.internal_reference} has been inactive for over 90 days. "
                f"Status: {payment.status}. Last updated: {payment.updated_at}. "
                f"Consider cancellation or follow-up."
            ),
        }
        
        message = alert_messages.get(alert_type, f"Compliance alert for {payment.internal_reference}")
        
        for admin in finance_admins:
            NotificationService.create_notification(
                user=admin,
                notification_type="compliance_alert",
                title=f"Compliance Alert: {alert_type.replace('_', ' ').title()}",
                message=message,
            )