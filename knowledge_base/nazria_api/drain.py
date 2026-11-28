"""Read the rest of a request body that the view never read (an upload refused with 401, 403, 413…).

gunicorn closes the connection after each response. When the API answered before reading an upload (for example a
pulse video sent with an expired login token), the unread bytes make that close a TCP reset, and a reverse proxy
that is still sending the body (Apache's mod_proxy) reports "502 Bad Gateway" instead of the API's real answer. The
app then cannot see the 401 that tells it to refresh its token. Reading and discarding the rest of the body (at most
DATA_UPLOAD_HARD_LIMIT, after the proxy has already received all of it) lets the real answer through.
"""
from __future__ import annotations

from django.conf import settings

CHUNK = 64 * 1024


class DrainUnreadBodyMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if request.method in ("POST", "PUT", "PATCH") and not getattr(request, "_read_started", False):
            try:
                length = int(request.META.get("CONTENT_LENGTH") or 0)
            except ValueError:
                length = 0
            limit = getattr(settings, "NAZRIA_DRAIN_MAX_BYTES", 128 * 1024 * 1024)
            stream = getattr(request, "_stream", None)
            if stream is not None and 0 < length <= limit:
                try:
                    while stream.read(CHUNK):
                        pass
                except OSError:            # the client went away: nothing left to protect
                    pass
        return response
