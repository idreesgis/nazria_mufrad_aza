"""Writes one AuditEvent per request to /api/ and /admin/ (static files and docs are skipped).

Views name what happened with ``audit(request, action, object_type, object_id, **details)``; without that the
action is the URL name and the HTTP method. Logging never breaks a request: a failure is logged and ignored."""
from __future__ import annotations

import logging
import time
import uuid

from django.conf import settings
from django.urls import resolve, Resolver404

log = logging.getLogger("audit")
_SKIP_PREFIXES = ("/api/docs", "/api/schema", "/static/", "/admin/jsi18n")


def client_ip(request) -> str | None:
    if getattr(settings, "NAZRIA_TRUST_PROXY", False):
        fwd = request.META.get("HTTP_X_FORWARDED_FOR", "")
        if fwd:
            return fwd.split(",")[0].strip() or None
    return request.META.get("REMOTE_ADDR") or None


def audit(request, action: str, object_type: str = "", object_id=None, **details) -> None:
    """Name the event of this request (call it from a view; the last call wins)."""
    r = getattr(request, "_request", request)
    r.audit = {"action": action, "object_type": object_type or "",
               "object_id": "" if object_id is None else str(object_id), "details": details}


class AuditMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.request_id = uuid.uuid4()
        t0 = time.monotonic()
        response = self.get_response(request)
        response["X-Request-ID"] = str(request.request_id)
        path = request.path
        if (path.startswith("/api/") or path.startswith("/admin/")) and not path.startswith(_SKIP_PREFIXES):
            try:
                self._write(request, response, int((time.monotonic() - t0) * 1000))
            except Exception as e:                       # noqa: BLE001 - auditing must not break the request
                log.error("audit write failed: %s", type(e).__name__)
        return response

    @staticmethod
    def _write(request, response, duration_ms: int) -> None:
        from accounts.models import role_of

        from .models import AuditEvent
        info = getattr(request, "audit", None) or {}
        user = getattr(request, "audit_user", None)
        if user is None:
            u = getattr(request, "user", None)
            user = u if u is not None and u.is_authenticated else None
        action = info.get("action")
        if not action:
            try:
                name = resolve(request.path_info).url_name or "unknown"
            except Resolver404:
                name = "not_found"
            prefix = "admin" if request.path.startswith("/admin/") else "api"
            action = f"{prefix}.{name}.{request.method.lower()}"[:60]
        AuditEvent.objects.create(
            request_id=request.request_id, actor=user, actor_type=role_of(user) if user else "anonymous",
            api_client=getattr(request, "api_client", None), action=action[:60],
            object_type=info.get("object_type", ""), object_id=info.get("object_id", ""),
            method=request.method[:8], path=request.path[:255], status_code=response.status_code,
            duration_ms=duration_ms, ip=client_ip(request), user_agent=request.META.get("HTTP_USER_AGENT", "")[:255],
            details=info.get("details") or {})
