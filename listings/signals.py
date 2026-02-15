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