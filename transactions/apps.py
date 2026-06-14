from django.apps import AppConfig
from django.db.models.signals import post_migrate
import logging

logger = logging.getLogger(__name__)


class TransactionsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "transactions"
    verbose_name = "Legal Transactions & Conveyancing"

    def ready(self):
        """
        Initialize signals and register startup tasks for the transactions app.
        
        Signals handle:
        - Auto-creation of legal transactions from payment requests
        - Syncing legal stage advancements to payment workflow
        - Document verification triggering payment step completion
        - Auto-disbursement when registration completes
        - Stamp duty verification from KRA iTax receipts
        """
        # Import signals to register signal handlers
        from . import signals
        
        # Register post-migration setup tasks
        post_migrate.connect(self._post_migration_setup, sender=self)
        
        # Log that transactions app is ready
        logger.info("Transactions app ready: Legal conveyancing signals registered")
    
    def _post_migration_setup(self, **kwargs):
        """
        Run setup tasks after migrations are complete.
        This ensures:
        - Required document types are documented
        - Legal stage templates are loaded
        - Any pending transactions are synced with payments
        """
        try:
            self._ensure_legal_stage_documentation()
            self._sync_pending_transactions()
            self._log_setup_completion()
        except Exception as e:
            logger.error(f"Post-migration setup failed for transactions: {e}")
    
    def _ensure_legal_stage_documentation(self):
        """
        Ensure that legal stage documentation is available.
        This creates a system record of required documents per stage.
        """
        from .models import Transaction, TransactionDocument
        
        # Document requirements per stage (for reference/documentation)
        stage_requirements = {
            Transaction.Stage.DUE_DILIGENCE: [
                TransactionDocument.DocType.OFFICIAL_SEARCH,
                TransactionDocument.DocType.SURVEY_MAP,
            ],
            Transaction.Stage.COMMITMENT: [
                TransactionDocument.DocType.LETTER_OF_OFFER,
            ],
            Transaction.Stage.CONTRACTS: [
                TransactionDocument.DocType.SALE_AGREEMENT,
            ],
            Transaction.Stage.STATUTORY_CONSENTS: [
                TransactionDocument.DocType.LCB_CONSENT,
                TransactionDocument.DocType.SPOUSAL_CONSENT,
            ],
            Transaction.Stage.TAXATION: [
                TransactionDocument.DocType.STAMP_DUTY_RECEIPT,
                TransactionDocument.DocType.VALUATION_REPORT,
            ],
            Transaction.Stage.REGISTRATION: [
                TransactionDocument.DocType.ORIGINAL_TITLE_DEED,
                TransactionDocument.DocType.TRANSFER_FORM,
                TransactionDocument.DocType.ID_DOCUMENT,
                TransactionDocument.DocType.KRA_PIN,
                TransactionDocument.DocType.PASSPORT_PHOTO,
                TransactionDocument.DocType.RATES_CLEARANCE,
                TransactionDocument.DocType.RENT_CLEARANCE,
                TransactionDocument.DocType.NEW_TITLE_DEED,
            ],
            Transaction.Stage.DISBURSEMENT: [
                TransactionDocument.DocType.NEW_TITLE_DEED,  # Final verification
            ],
        }
        
        logger.info(f"Legal stage requirements loaded for {len(stage_requirements)} stages")
        
        # Optionally store in cache for quick access
        from django.core.cache import cache
        cache.set('transactions:stage_requirements', stage_requirements, timeout=86400)  # 24 hours
    
    def _sync_pending_transactions(self):
        """
        Check for any transactions that should be synced with their payments.
        This handles cases where signals might have been missed during downtime.
        """
        from django.db import transaction
        from .models import Transaction
        from payments.models import PaymentRequest
        
        # Find transactions with payment requests that might be out of sync
        transactions_to_sync = Transaction.objects.filter(
            payment_request__isnull=False
        ).select_related('payment_request')
        
        synced_count = 0
        for legal_tx in transactions_to_sync:
            payment = legal_tx.payment_request
            
            if not payment:
                continue
            
            with transaction.atomic():
                updated = False
                
                # Sync deposit amount
                if payment.metadata.get('deposit_paid') and legal_tx.deposit_paid != payment.amount:
                    legal_tx.deposit_paid = payment.metadata.get('deposit_paid_amount', 0)
                    updated = True
                
                # Sync balance amount
                if payment.metadata.get('balance_paid') and legal_tx.balance_paid != payment.amount:
                    legal_tx.balance_paid = payment.metadata.get('balance_paid_amount', 0)
                    updated = True
                
                # Sync escrow timestamps
                if payment.deposit_received_at and not legal_tx.deposit_held_in_escrow_at:
                    legal_tx.deposit_held_in_escrow_at = payment.deposit_received_at
                    updated = True
                
                if payment.balance_received_at and not legal_tx.balance_held_in_escrow_at:
                    legal_tx.balance_held_in_escrow_at = payment.balance_received_at
                    updated = True
                
                # Sync disbursement
                if payment.disbursed_at and not legal_tx.disbursed_at:
                    legal_tx.disbursed_at = payment.disbursed_at
                    legal_tx.platform_fee_amount = payment.platform_fee_amount
                    legal_tx.seller_net_amount = payment.seller_net_amount
                    
                    if legal_tx.stage == Transaction.Stage.REGISTRATION:
                        legal_tx.stage = Transaction.Stage.DISBURSEMENT
                    
                    updated = True
                
                # Sync stamp duty verification
                if payment.stamp_duty_receipt_verified_at and not legal_tx.stamp_duty_receipt_verified_at:
                    legal_tx.stamp_duty_receipt_verified_at = payment.stamp_duty_receipt_verified_at
                    legal_tx.stamp_duty_receipt_number = payment.metadata.get('stamp_duty_receipt_number', '')
                    legal_tx.stamp_duty_verified_by = payment.stamp_duty_verified_by
                    updated = True
                
                if updated:
                    legal_tx.save(update_fields=[
                        'deposit_paid', 'balance_paid',
                        'deposit_held_in_escrow_at', 'balance_held_in_escrow_at',
                        'disbursed_at', 'platform_fee_amount', 'seller_net_amount',
                        'stage', 'stamp_duty_receipt_verified_at',
                        'stamp_duty_receipt_number', 'stamp_duty_verified_by',
                        'updated_at'
                    ])
                    synced_count += 1
        
        if synced_count > 0:
            logger.info(f"Synced {synced_count} pending transactions with payment data")
    
    def _log_setup_completion(self):
        """Log that setup is complete with current statistics"""
        try:
            from .models import Transaction
            
            total_transactions = Transaction.objects.count()
            active_transactions = Transaction.objects.exclude(
                stage__in=[Transaction.Stage.COMPLETED, Transaction.Stage.CANCELLED]
            ).count()
            completed_transactions = Transaction.objects.filter(
                stage=Transaction.Stage.COMPLETED
            ).count()
            
            logger.info(
                f"Transactions app setup complete: "
                f"Total: {total_transactions}, "
                f"Active: {active_transactions}, "
                f"Completed: {completed_transactions}"
            )
        except Exception as e:
            logger.error(f"Failed to log setup statistics: {e}")


class TransactionsAppReady:
    """
    Helper class to check if transactions app is ready.
    Used by other apps that depend on transactions functionality.
    """
    _is_ready = False
    
    @classmethod
    def mark_ready(cls):
        cls._is_ready = True
    
    @classmethod
    def is_ready(cls):
        return cls._is_ready