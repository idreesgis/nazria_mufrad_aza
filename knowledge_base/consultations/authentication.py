"""API-key authentication and per-client throttling for the Android app.

Send the key as ``Authorization: Api-Key nzr_…`` (or ``X-Api-Key: nzr_…``). Create keys with
``python manage.py create_api_client <name>``; revoke them in the admin (uncheck "active")."""
from __future__ import annotations

from rest_framework import authentication, exceptions, permissions, throttling

from .models import ApiClient


class ClientPrincipal:
    """request.user for API-key requests (there are no patient accounts)."""
    is_authenticated = True
    is_anonymous = False
    is_staff = False

    def __init__(self, client: ApiClient):
        self.client = client
        self.pk = self.id = client.pk

    def __str__(self) -> str:
        return f"api-client:{self.client.name}"


class ApiKeyAuthentication(authentication.BaseAuthentication):
    keyword = "Api-Key"

    def authenticate(self, request):
        header = authentication.get_authorization_header(request).decode("latin-1").strip()
        key = None
        if header:
            scheme, _, value = header.partition(" ")
            if scheme.lower() != self.keyword.lower():
                return None
            key = value.strip()
        else:
            key = (request.headers.get("X-Api-Key") or "").strip() or None
        if not key:
            return None
        client = ApiClient.authenticate(key)
        if client is None:
            raise exceptions.AuthenticationFailed("invalid or inactive API key")
        return ClientPrincipal(client), client

    def authenticate_header(self, request):
        return self.keyword


class HasApiClient(permissions.BasePermission):
    message = "an API key is required (Authorization: Api-Key …)"

    def has_permission(self, request, view):
        return isinstance(request.auth, ApiClient)


class ClientRateThrottle(throttling.SimpleRateThrottle):
    """Per API client (per IP for unauthenticated requests)."""
    scope = "client"

    def get_cache_key(self, request, view):
        ident = f"c{request.auth.pk}" if isinstance(request.auth, ApiClient) else self.get_ident(request)
        return self.cache_format % {"scope": self.scope, "ident": ident}


class ExplanationRateThrottle(ClientRateThrottle):
    """AI explanations cost money and provider quota: a lower limit per client."""
    scope = "explanation"
