"""OpenAPI description of the API-key header, so generated clients (e.g. for Android) send it."""
from drf_spectacular.extensions import OpenApiAuthenticationExtension


class ApiKeyScheme(OpenApiAuthenticationExtension):
    target_class = "consultations.authentication.ApiKeyAuthentication"
    name = "ApiKey"

    def get_security_definition(self, auto_schema):
        return {"type": "apiKey", "in": "header", "name": "Authorization",
                "description": 'Value: "Api-Key nzr_…" (create keys with: python manage.py create_api_client NAME)'}
