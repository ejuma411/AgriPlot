from django.apps import AppConfig


class SecurityConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'security'
    verbose_name = 'Security & Compliance'

    def ready(self):
        # Import signals only when app is ready
        try:
            from . import signals
        except ImportError:
            pass