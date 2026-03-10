from django.apps import AppConfig


class RegistryMockConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "registry_mock"
    verbose_name = "Mock Land Registry"
