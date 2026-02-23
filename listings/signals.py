from django.db.models.signals import post_save
from django.dispatch import receiver
from django.contrib.auth.models import User
from .models import *
from .services.ardhisasa_service import ArdhisasaVerificationService
from django.contrib.contenttypes.models import ContentType
import threading

@receiver(post_save, sender=User)
def create_profile(sender, instance, created, **kwargs):
    if created:
        Profile.objects.create(user=instance)


@receiver(post_save, sender=LandownerProfile)
@receiver(post_save, sender=Agent)
def start_verification(sender, instance, created, **kwargs):
    """
    Automatically start verification when documents are submitted
    """
    if created:  # Only for new registrations
        # Create verification tracking
        content_type = ContentType.objects.get_for_model(instance)
        verification = VerificationStatus.objects.create(
            content_type=content_type,
            object_id=instance.id,
            document_uploaded_at=timezone.now()
        )
        
        # Start API verification in background thread
        def run_verification():
            service = ArdhisasaVerificationService(verification)
            service.start_verification()
        
        thread = threading.Thread(target=run_verification)
        thread.start()



# listings/signals.py

from django.db.models.signals import post_save
from django.dispatch import receiver
from django.contrib.contenttypes.models import ContentType
import logging
from .models import VerificationStatus, Plot
from .services.ardhisasa_integration import ArdhisasaService

logger = logging.getLogger(__name__)

# Global flag to prevent recursion
_processing_verification = set()

@receiver(post_save, sender=VerificationStatus)
def trigger_ardhisasa_verification(sender, instance, created, **kwargs):
    """
    Automatically trigger Ardhisasa verification when a plot reaches
    the 'document_uploaded' stage or when explicitly started
    """
    # Generate a unique ID for this verification to prevent recursion
    verification_id = f"{instance.content_type_id}_{instance.object_id}"
    
    # If we're already processing this verification, skip
    if verification_id in _processing_verification:
        logger.debug(f"Skipping recursive call for verification {verification_id}")
        return
    
    # Only run for Plot objects
    if instance.content_type.model != 'plot':
        return
    
    # Get the plot
    try:
        plot = instance.content_object
        if not plot:
            return
    except:
        return
    
    # Check if we should start Ardhisasa verification
    should_start = False
    
    # Case 1: New verification status created for a plot
    if created and instance.current_stage == 'document_uploaded':
        should_start = True
        logger.info(f"New plot {plot.id} created, will start Ardhisasa verification")
    
    # Case 2: Stage explicitly updated to api_verification_started
    elif instance.current_stage == 'api_verification_started':
        should_start = True
        logger.info(f"Plot {plot.id} moved to API verification stage")
    
    if should_start:
        try:
            # Add to processing set to prevent recursion
            _processing_verification.add(verification_id)
            
            # Run directly (no Celery)
            logger.info(f"Running Ardhisasa verification directly for plot {plot.id}")
            service = ArdhisasaService(use_mock=True)
            result = service.verify_plot_title(plot)
            
            if result.get('success'):
                # Use update() instead of save() to avoid triggering signals again
                instance.current_stage = 'title_search_completed'
                instance.title_search_at = timezone.now()
                instance.stage_details['title_search'] = {
                    'search_reference': result.get('search_data', {}).get('search_reference'),
                    'title_number': result.get('search_data', {}).get('title_number'),
                    'owner_name': result.get('search_data', {}).get('owner_name')
                }
                # Use update() to bypass signals
                VerificationStatus.objects.filter(pk=instance.pk).update(
                    current_stage='title_search_completed',
                    title_search_at=timezone.now(),
                    stage_details=instance.stage_details
                )
                logger.info(f"✅ Ardhisasa verification completed for plot {plot.id}")
            else:
                instance.stage_details['ardhisasa_error'] = result.get('error')
                VerificationStatus.objects.filter(pk=instance.pk).update(
                    stage_details=instance.stage_details
                )
                logger.error(f"❌ Ardhisasa verification failed for plot {plot.id}: {result.get('error')}")
        finally:
            # Always remove from processing set
            _processing_verification.discard(verification_id)


