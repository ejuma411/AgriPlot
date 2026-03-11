import logging
import sys
import threading

from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone

from accounts.models import Agent, LandownerProfile
from verification.services.ardhisasa_integration import ArdhisasaService
from verification.services.ardhisasa_service import ArdhisasaVerificationService
from notifications.notification_service import NotificationService
from verification.models import VerificationStatus
from verification.verification_service import VerificationService

logger = logging.getLogger(__name__)

_processing_verification = set()


@receiver(post_save, sender=LandownerProfile)
@receiver(post_save, sender=Agent)
def start_verification(sender, instance, created, **kwargs):
    if not created:
        return

    content_type = ContentType.objects.get_for_model(instance)
    verification = VerificationStatus.objects.create(
        content_type=content_type,
        object_id=instance.id,
        document_uploaded_at=timezone.now(),
    )

    if "test" in sys.argv:
        return

    def run_verification():
        service = ArdhisasaVerificationService(verification)
        service.start_verification()

    transaction.on_commit(
        lambda: threading.Thread(target=run_verification, daemon=True).start()
    )


@receiver(post_save, sender=VerificationStatus)
def trigger_ardhisasa_verification(sender, instance, created, **kwargs):
    verification_id = f"{instance.content_type_id}_{instance.object_id}"
    if verification_id in _processing_verification:
        logger.debug("Skipping recursive call for verification %s", verification_id)
        return

    if instance.content_type.model != "plot":
        return

    try:
        plot = instance.content_object
        if not plot:
            return
    except Exception:
        return

    should_start = False
    if created and instance.current_stage == "document_uploaded":
        should_start = True
        logger.info("New plot %s created, will start Ardhisasa verification", plot.id)
    elif instance.current_stage == "api_verification_started":
        should_start = True
        logger.info("Plot %s moved to API verification stage", plot.id)

    if not should_start:
        return

    try:
        _processing_verification.add(verification_id)
        logger.info("Running Ardhisasa verification directly for plot %s", plot.id)
        service = ArdhisasaService(use_mock=True)
        result = service.verify_plot_title(plot)

        if result.get("success"):
            verification_data = result.get("verification_data", {})
            search_result = verification_data.get("search_result", {})
            instance.stage_details["title_search"] = {
                "search_reference": search_result.get("search_reference"),
                "title_number": verification_data.get("title_number")
                or search_result.get("title_number"),
                "owner_name": search_result.get("owner_name"),
                "parcel_number": search_result.get("parcel_number"),
            }
            instance.stage_details["ardhisasa_checks"] = {
                "ownership_result": verification_data.get("ownership_result"),
                "encumbrance_result": verification_data.get("encumbrance_result"),
                "decision": verification_data.get("decision"),
            }

            VerificationStatus.objects.filter(pk=instance.pk).update(
                current_stage="title_search_completed",
                title_search_at=timezone.now(),
                stage_details=instance.stage_details,
            )
            logger.info("Ardhisasa verification completed for plot %s", plot.id)

            try:
                logger.info("Triggering post-API assignment for plot %s", plot.id)
                VerificationService.after_api_verification(plot, assigned_by=None)
            except Exception as assign_err:
                logger.error(
                    "Post-API task assignment failed for plot %s: %s",
                    plot.id,
                    assign_err,
                )

            try:
                NotificationService.notify_plot_stage(
                    plot, "title_search_completed", instance.stage_details.get("title_search", {})
                )
            except Exception as notify_err:
                logger.error("Stage notification failed for plot %s: %s", plot.id, notify_err)
        else:
            instance.stage_details["ardhisasa_error"] = result.get("error")
            instance.stage_details["ardhisasa_failure"] = result.get("decision")
            VerificationStatus.objects.filter(pk=instance.pk).update(
                current_stage="rejected",
                rejected_at=timezone.now(),
                stage_details=instance.stage_details,
            )
            logger.error(
                "Ardhisasa verification failed for plot %s: %s",
                plot.id,
                result.get("error"),
            )
    finally:
        _processing_verification.discard(verification_id)
