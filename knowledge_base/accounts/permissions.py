"""App key check (X-Api-Key) and staff-only access."""
from django.conf import settings
from rest_framework import exceptions, permissions

from consultations.models import ApiClient

from .models import is_staff_user


class HasAppKey(permissions.BasePermission):
    """The request comes from a registered app: header X-Api-Key: nzr_… (python manage.py create_api_client)."""
    message = "the app key is missing or not valid (header X-Api-Key)"

    def has_permission(self, request, view):
        client = getattr(request._request, "api_client", None)
        if client is None:
            key = (request.headers.get("X-Api-Key") or "").strip()
            client = ApiClient.authenticate(key) if key else None
            request._request.api_client = client          # also read by the audit log
        if client is None and settings.NAZRIA_REQUIRE_APP_KEY:
            # 403 (not 401): a login would not help, the app itself is not recognised
            raise exceptions.PermissionDenied(self.message, code="app_key_invalid")
        return True


class IsStaff(permissions.BasePermission):
    """Hakeem or admin."""
    message = "staff only"

    def has_permission(self, request, view):
        return is_staff_user(request.user)
