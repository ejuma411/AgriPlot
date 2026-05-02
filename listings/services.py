import logging
from django.utils import timezone
from django.contrib.contenttypes.models import ContentType
from .models import Plot
from verification.models import VerificationStatus
from security.utils import log_audit

logger = logging.getLogger(__name__)
audit_logger = logging.getLogger('listings.audit')

class PlotCreationService:
    @staticmethod
    def execute_post_creation_workflow(plot, plot_form, request_user, request=None):
        """
        Executes the business logic required after a plot is initially saved.
        """
        try:
            uploaded_docs = []
            if plot.title_deed: uploaded_docs.append('title_deed')
            if plot.survey_map: uploaded_docs.append('survey_map')
            if plot.spousal_consent_doc: uploaded_docs.append('spousal_consent_doc')
            if plot.official_search: uploaded_docs.append('official_search')
            if plot.rates_clearance: uploaded_docs.append('rates_clearance')
            if plot.rent_clearance: uploaded_docs.append('rent_clearance')
            if plot.landowner_id_doc: uploaded_docs.append('landowner_id_doc')
            if plot.kra_pin: uploaded_docs.append('kra_pin')
            if plot.soil_report: uploaded_docs.append('soil_report')

            if request:
                audit_logger.info(f"User {request_user.username} created plot ID {plot.id}")
                log_audit(request, 'create_plot', object_type='Plot', object_id=plot.id)

            content_type = ContentType.objects.get_for_model(Plot)
            verification, created = VerificationStatus.objects.get_or_create(
                content_type=content_type,
                object_id=plot.id,
                defaults={
                    'current_stage': 'document_uploaded',
                    'document_uploaded_at': timezone.now(),
                    'stage_details': {
                        'created_by': request_user.username,
                        'created_by_id': request_user.id,
                        'created_at': timezone.now().isoformat(),
                        'plot_title': plot.title,
                        'plot_id': plot.id,
                        'county': plot.county,
                        'subcounty': plot.subcounty,
                        'documents_uploaded': uploaded_docs,
                        'registry_check': getattr(plot_form, "registry_result", None) or {}
                    }
                }
            )

            if created:
                logger.info(f"✅ Verification status created for plot {plot.id}")
                from verification.verification_service import VerificationService
                from notifications.notification_service import NotificationService
                VerificationService.create_verification_tasks(plot, initiated_by=request_user)
                NotificationService.notify_plot_submitted(plot)
                try:
                    VerificationService.initiate_ardhisasa_verification(plot.id)
                except Exception as api_err:
                    logger.warning(f"Ardhisasa verification failed for plot {plot.id}: {api_err}")
            else:
                logger.info(f"ℹ️ Verification status already exists for plot {plot.id}")

            if plot.listing_type in ['sale', 'both']:
                try:
                    from .utils import suggest_price
                    suggest_price(plot)
                except Exception as price_err:
                    logger.warning(f"Pricing suggestion failed for plot {plot.id}: {price_err}")
            
            return True, "Success"
        except Exception as e:
            logger.error(f"Error in PlotCreationService for plot {plot.id}: {e}", exc_info=True)
            return False, str(e)
