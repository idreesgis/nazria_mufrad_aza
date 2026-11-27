"""Rate limits per logged-in user (per client IP for anonymous requests)."""
from rest_framework import throttling

from audit.middleware import client_ip


class UserRateThrottle(throttling.SimpleRateThrottle):
    scope = "user"

    def get_cache_key(self, request, view):
        user = getattr(request, "user", None)
        ident = f"u{user.pk}" if user is not None and user.is_authenticated else f"ip{client_ip(request._request)}"
        return self.cache_format % {"scope": self.scope, "ident": ident}


class AuthRateThrottle(throttling.SimpleRateThrottle):
    """Register / login / refresh: per IP, against password guessing."""
    scope = "auth"

    def get_cache_key(self, request, view):
        return self.cache_format % {"scope": self.scope, "ident": client_ip(request._request)}


class ExplanationRateThrottle(UserRateThrottle):
    scope = "explanation"


class PulseRateThrottle(UserRateThrottle):
    scope = "pulse"
