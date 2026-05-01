# listings/tasks.py

import logging

from celery import shared_task
from django.contrib.contenttypes.models import ContentType
from django.utils import timezone

from listings.models import Plot
from verification.models import VerificationStatus

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=60, name="verification.tasks.run_ardhisasa_verification")
def run_ardhisasa_verification(self, plot_id, verification_id=None):
    """
    Celery task to run Ardhisasa verification asynchronously.
    Notifications are queued via the deferred notification system after the DB is updated.
    """
    logger.info("Starting Ardhisasa verification task for plot %s", plot_id)

    try:
        plot = Plot.objects.get(id=plot_id)
    except Plot.DoesNotExist:
        logger.error("Plot %s not found", plot_id)
        return {"success": False, "error": "Plot not found"}

    try:
        content_type = ContentType.objects.get_for_model(Plot)
        if verification_id:
            verification = VerificationStatus.objects.get(id=verification_id)
        else:
            verification = VerificationStatus.objects.get(
                content_type=content_type,
                object_id=plot.id,
            )
    except VerificationStatus.DoesNotExist:
        logger.error("VerificationStatus not found for plot %s", plot_id)
        return {"success": False, "error": "VerificationStatus not found"}

    try:
        from verification.services.ardhisasa_integration import ArdhisasaService
        service = ArdhisasaService(use_mock=True)
        result = service.verify_plot_title(plot)

        if result["success"]:
            verification_data = result.get("verification_data", {})
            search_result = verification_data.get("search_result", {})
            # DB update first — synchronous
            verification.update_stage(
                "title_search_completed",
                {
                    "search_reference": search_result.get("search_reference"),
                    "title_number": verification_data.get("title_number") or search_result.get("title_number"),
                    "parcel_number": search_result.get("parcel_number"),
                    "owner_name": search_result.get("owner_name"),
                    "search_result": search_result,
                    "ownership_result": verification_data.get("ownership_result"),
                    "encumbrance_result": verification_data.get("encumbrance_result"),
                    "decision": verification_data.get("decision"),
                },
            )
            logger.info("Ardhisasa verification successful for plot %s", plot_id)
            return {"success": True, "plot_id": plot_id}
        else:
            # DB update first — synchronous
            verification.stage_details["ardhisasa_error"] = result["error"]
            verification.stage_details["ardhisasa_failure"] = result.get("decision")
            VerificationStatus.objects.filter(pk=verification.pk).update(
                current_stage="rejected",
                rejected_at=timezone.now(),
                stage_details=verification.stage_details,
            )
            logger.error("Ardhisasa verification failed for plot %s: %s", plot_id, result["error"])
            return {"success": False, "plot_id": plot_id, "error": result["error"]}

    except Exception as exc:
        logger.error("Error in Ardhisasa verification for plot %s: %s", plot_id, exc, exc_info=True)
        raise self.retry(exc=exc)
