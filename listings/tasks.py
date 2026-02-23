# listings/tasks.py

from celery import shared_task
import logging
from .services.ardhisasa_integration import ArdhisasaService
from .models import Plot, VerificationStatus
from django.contrib.contenttypes.models import ContentType

logger = logging.getLogger(__name__)

@shared_task
def run_ardhisasa_verification(plot_id, verification_id=None):
    """
    Celery task to run Ardhisasa verification asynchronously
    """
    logger.info(f"Starting Ardhisasa verification task for plot {plot_id}")
    
    try:
        plot = Plot.objects.get(id=plot_id)
        
        # Get verification status
        content_type = ContentType.objects.get_for_model(Plot)
        if verification_id:
            verification = VerificationStatus.objects.get(id=verification_id)
        else:
            verification = VerificationStatus.objects.get(
                content_type=content_type,
                object_id=plot.id
            )
        
        # Run verification
        service = ArdhisasaService(use_mock=True)
        result = service.verify_plot_title(plot)
        
        if result['success']:
            verification.update_stage('title_search_completed', {
                'search_reference': result['search_data'].get('search_reference'),
                'title_number': result['search_data'].get('title_number'),
                'parcel_number': result['search_data'].get('parcel_number'),
                'owner_name': result['search_data'].get('owner_name'),
                'search_result': result['search_data']
            })
            logger.info(f"✅ Ardhisasa verification successful for plot {plot_id}")
            return {'success': True, 'plot_id': plot_id}
        else:
            verification.stage_details['ardhisasa_error'] = result['error']
            verification.save()
            logger.error(f"❌ Ardhisasa verification failed for plot {plot_id}: {result['error']}")
            return {'success': False, 'plot_id': plot_id, 'error': result['error']}
            
    except Plot.DoesNotExist:
        logger.error(f"Plot {plot_id} not found")
        return {'success': False, 'error': 'Plot not found'}
    except Exception as e:
        logger.error(f"Error in Ardhisasa verification: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}