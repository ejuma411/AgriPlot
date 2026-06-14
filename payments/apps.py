from django.apps import AppConfig
from django.db.models.signals import post_migrate


class PaymentsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "payments"
    verbose_name = "Payment & Escrow Management"

    def ready(self):
        """
        Initialize signals and register startup tasks.
        Signals handle:
        - Wallet creation for new users
        - Payment status changes (escrow, disbursement)
        - Closing step completion (registration, stamp duty)
        - Automatic fund disbursement triggers
        """
        # Import signals to register signal handlers
        import payments.signals
        
        # Register post-migration setup tasks
        post_migrate.connect(self._post_migration_setup, sender=self)
        
        # Log that payments app is ready
        import logging
        logger = logging.getLogger(__name__)
        logger.info("Payments app ready: Escrow, disbursement, and stamp duty signals registered")
    
    def _post_migration_setup(self, **kwargs):
        """
        Run setup tasks after migrations are complete.
        This ensures:
        - Required groups (Finance Admin, Escrow Admin) exist
        - Default closing step templates are loaded
        - Any pending disbursements are queued
        """
        try:
            self._ensure_admin_groups()
            self._queue_pending_disbursements()
            self._log_setup_completion()
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Post-migration setup failed: {e}")
    
    def _ensure_admin_groups(self):
        """Ensure required admin groups exist in the system"""
        from django.contrib.auth.models import Group, Permission
        from django.contrib.contenttypes.models import ContentType
        
        # Required groups for payment management
        groups_config = {
            "Finance Admin": {
                "description": "Can view payments, verify stamp duty receipts, manage escrow",
                "permissions": [
                    ("view_paymentrequest", "payments", "paymentrequest"),
                    ("change_paymentrequest", "payments", "paymentrequest"),
                    ("view_paymentdisbursement", "payments", "paymentdisbursement"),
                    ("change_paymentdisbursement", "payments", "paymentdisbursement"),
                ]
            },
            "Escrow Admin": {
                "description": "Can authorize fund disbursements and platform fee deductions",
                "permissions": [
                    ("view_paymentrequest", "payments", "paymentrequest"),
                    ("change_paymentrequest", "payments", "paymentrequest"),
                    ("view_paymentdisbursement", "payments", "paymentdisbursement"),
                    ("change_paymentdisbursement", "payments", "paymentdisbursement"),
                    ("view_banktransferrequest", "payments", "banktransferrequest"),
                    ("change_banktransferrequest", "payments", "banktransferrequest"),
                ]
            },
            "Legal Admin": {
                "description": "Can verify legal documents and closing steps",
                "permissions": [
                    ("view_paymentrequest", "payments", "paymentrequest"),
                    ("view_paymentclosingstep", "payments", "paymentclosingstep"),
                    ("change_paymentclosingstep", "payments", "paymentclosingstep"),
                    ("view_transactiondocument", "transactions", "transactiondocument"),
                    ("change_transactiondocument", "transactions", "transactiondocument"),
                ]
            },
        }
        
        for group_name, config in groups_config.items():
            group, created = Group.objects.get_or_create(name=group_name)
            if created:
                group.description = config["description"]
                group.save()
            
            # Assign permissions
            for perm_codename, app_label, model_name in config["permissions"]:
                try:
                    content_type = ContentType.objects.get(app_label=app_label, model=model_name)
                    permission = Permission.objects.get(
                        codename=perm_codename,
                        content_type=content_type
                    )
                    group.permissions.add(permission)
                except (ContentType.DoesNotExist, Permission.DoesNotExist):
                    # Skip if model/permission doesn't exist yet (might not be migrated)
                    pass
            
            if created:
                import logging
                logger = logging.getLogger(__name__)
                logger.info(f"Created admin group: {group_name}")
    
    def _queue_pending_disbursements(self):
        """
        Check for any payments that should have been disbursed
        but weren't due to system downtime or missed signals.
        """
        from django.utils import timezone
        from .models import PaymentRequest, PaymentClosingStep
        
        # Find purchase transactions with registration complete but not disbursed
        pending_disbursements = PaymentRequest.objects.filter(
            transaction_type=PaymentRequest.TransactionType.PURCHASE,
            status=PaymentRequest.Status.IN_ESCROW,
            disbursed_at__isnull=True,
        )
        
        for payment in pending_disbursements:
            # Check if registration step is completed
            registration_step = payment.closing_steps.filter(
                code="registration",
                status=PaymentClosingStep.Status.COMPLETED
            ).exists()
            
            # Check if stamp duty is verified
            stamp_duty_step = payment.closing_steps.filter(
                code="stamp_duty",
                status=PaymentClosingStep.Status.COMPLETED
            ).exists()
            
            # Check if both deposit and balance are in escrow
            deposit_paid = payment.metadata.get('deposit_paid', False)
            balance_paid = payment.metadata.get('balance_paid', False)
            
            if registration_step and stamp_duty_step and deposit_paid and balance_paid:
                import logging
                logger = logging.getLogger(__name__)
                logger.info(
                    f"Startup: Found pending disbursement for {payment.internal_reference}. "
                    f"Queueing for processing."
                )
                
                try:
                    # Queue for background processing or trigger immediately
                    # For now, we'll just log - actual processing will happen in middleware
                    payment.metadata['pending_disbursement_queued'] = True
                    payment.metadata['pending_disbursement_queued_at'] = timezone.now().isoformat()
                    payment.save(update_fields=['metadata'])
                except Exception as e:
                    logger.error(f"Failed to queue disbursement for {payment.internal_reference}: {e}")
    
    def _log_setup_completion(self):
        """Log that setup is complete with current statistics"""
        import logging
        logger = logging.getLogger(__name__)
        
        try:
            from .models import PaymentRequest
            
            # Get some statistics for startup log
            total_payments = PaymentRequest.objects.count()
            active_escrow = PaymentRequest.objects.filter(
                status__in=['paid', 'in_escrow', 'partially_released'],
                disbursed_at__isnull=True
            ).count()
            
            completed_payments = PaymentRequest.objects.filter(
                disbursed_at__isnull=False
            ).count()
            
            logger.info(
                f"Payments app setup complete: "
                f"Total payments: {total_payments}, "
                f"Active escrow: {active_escrow}, "
                f"Completed: {completed_payments}"
            )
        except Exception as e:
            logger.error(f"Failed to log setup statistics: {e}")


class PaymentsAppReady:
    """
    Helper class to check if payments app is ready.
    Used by other apps that depend on payments functionality.
    """
    _is_ready = False
    
    @classmethod
    def mark_ready(cls):
        cls._is_ready = True
    
    @classmethod
    def is_ready(cls):
        return cls._is_ready