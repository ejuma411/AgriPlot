import logging


class SecurityContextDefaultsFilter(logging.Filter):
    """Ensure security log records always have user/ip fields for formatting."""

    def filter(self, record):
        if not hasattr(record, "user"):
            record.user = "anonymous"
        if not hasattr(record, "ip"):
            record.ip = "-"
        return True
