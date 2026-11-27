from django.apps import AppConfig


class ConsultationsConfig(AppConfig):
    name = "consultations"
    verbose_name = "Consultations API"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        from . import schema  # noqa: F401  (registers the OpenAPI API-key scheme)
