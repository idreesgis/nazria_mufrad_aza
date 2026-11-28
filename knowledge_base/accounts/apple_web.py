"""Sign in with Apple on Android: Apple has no Android SDK, so the app opens Apple's web page in a browser tab and the
server passes the result back to the app.

1. The app makes a random ``nonce`` (kept on the phone) and a random ``state``, and opens
   ``GET /api/v1/auth/apple/start/?nonce=<sha256(nonce), hex>&state=<state>`` in a Custom Tab.
2. The server sends the browser to Apple (``response_type=code id_token``, ``response_mode=form_post``), with the
   nonce hash and its own signed state.
3. Apple posts the result to ``/api/v1/auth/apple/callback/`` (``NAZRIA_PUBLIC_URL``, which Apple requires to be
   HTTPS). The server checks its signed state and opens ``org.nazria.app://auth/apple?...`` with the ID token, the
   app's state and, on the first sign-in only, the name Apple sends.
4. The app checks its state and posts ``id_token`` + the raw ``nonce`` to ``/api/v1/auth/social/apple/``. The token
   is useless without the raw nonce, so another app that catches the redirect cannot sign in with it.

These two routes are opened by a browser, so they need no app key, and they never log in, store or log a token.
"""
from __future__ import annotations

import json
import re
from html import escape
from urllib.parse import urlencode

from django.core import signing
from django.http import HttpResponse, HttpResponseBadRequest
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from audit.middleware import audit

from . import social

APP_REDIRECT = "org.nazria.app://auth/apple"
AUTHORIZE_URL = "https://appleid.apple.com/auth/authorize"
STATE_SALT = "nazria.apple-web"
STATE_MAX_AGE_S = 600
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_APP_STATE = re.compile(r"^[A-Za-z0-9_-]{16,128}$")


def _service_id() -> str:
    return social.client_ids("apple")[0].split(",")[0].strip()


def _page(target: str, title: str = "Nazria") -> HttpResponse:
    """A tiny page that hands the result to the app (a link as well, in case the browser blocks the automatic
    switch)."""
    t = escape(target, quote=True)
    html = (f"<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width'>"
            f"<meta http-equiv='refresh' content='0;url={t}'><title>{escape(title)}</title></head>"
            f"<body style='font-family:sans-serif;text-align:center;padding:48px 16px'>"
            f"<p><a href='{t}' style='font-size:20px'>Open Nazria · نظریہ کھولیں · افتح نظرية</a></p></body></html>")
    r = HttpResponse(html)
    r["Cache-Control"] = "no-store"
    r["Referrer-Policy"] = "no-referrer"
    r["Content-Security-Policy"] = "default-src 'none'; style-src 'unsafe-inline'"
    return r


@require_GET
def start(request):
    if not social.enabled("apple") or not social.apple_callback_url():
        return HttpResponse("Sign in with Apple is not set up on this server.", status=503, content_type="text/plain")
    nonce = (request.GET.get("nonce") or "").lower()
    app_state = request.GET.get("state") or ""
    if not _HEX64.match(nonce) or not _APP_STATE.match(app_state):
        return HttpResponseBadRequest("nonce (sha-256 hex) and state are required", content_type="text/plain")
    state = signing.dumps({"s": app_state}, salt=STATE_SALT)
    params = {"client_id": _service_id(), "redirect_uri": social.apple_callback_url(),
              "response_type": "code id_token", "response_mode": "form_post", "scope": "name email",
              "state": state, "nonce": nonce}
    audit(request, "auth.apple_web_start")
    r = HttpResponse(status=302)
    r["Location"] = f"{AUTHORIZE_URL}?{urlencode(params)}"
    r["Cache-Control"] = "no-store"
    return r


@csrf_exempt            # Apple posts here from appleid.apple.com; the signed state stands in for the CSRF token
@require_POST
def callback(request):
    try:
        app_state = signing.loads(request.POST.get("state") or "", salt=STATE_SALT, max_age=STATE_MAX_AGE_S)["s"]
    except (signing.BadSignature, KeyError, TypeError):
        audit(request, "auth.apple_web_failed", reason="state")
        return HttpResponseBadRequest("This sign-in has expired. Start again in the app.", content_type="text/plain")
    error = request.POST.get("error") or ""
    id_token = request.POST.get("id_token") or ""
    if error or not id_token:
        audit(request, "auth.apple_web_failed", reason=(error or "no_token")[:40])
        return _page(f"{APP_REDIRECT}?{urlencode({'state': app_state, 'error': (error or 'no_token')[:40]})}")
    name = ""
    try:                                       # only on the first sign-in: {"name": {"firstName", "lastName"}}
        user = json.loads(request.POST.get("user") or "{}")
        n = user.get("name") or {}
        name = " ".join(x for x in [n.get("firstName"), n.get("lastName")] if x)[:150]
    except (ValueError, AttributeError):
        pass
    audit(request, "auth.apple_web_return")
    q = {"state": app_state, "id_token": id_token, **({"name": name} if name else {})}
    return _page(f"{APP_REDIRECT}?{urlencode(q)}")
