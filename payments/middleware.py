import logging

from django.core.cache import cache

from .lease_lifecycle import process_lease_lifecycle


logger = logging.getLogger(__name__)


class LeaseLifecycleHeartbeatMiddleware:
    """
    Run the lease lifecycle processor opportunistically during app traffic.

    This is a lightweight safety net for expiry flips and queue notices between
    scheduled command runs.
    """

    CACHE_KEY = "payments:lease_lifecycle:heartbeat"
    THROTTLE_SECONDS = 300

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if cache.add(self.CACHE_KEY, "1", self.THROTTLE_SECONDS):
            try:
                process_lease_lifecycle()
            except Exception:
                logger.exception("Lease lifecycle heartbeat failed")
        return self.get_response(request)
