"""Verifying a Google ID token sent by the Android app (Google Sign-In / Credential Manager).

The app asks Google for an ID token with the server's **Web client ID** as ``serverClientId`` and sends it to
``POST /api/v1/auth/google/``. The server checks it with Google's public keys (fetched from www.googleapis.com and
cached), so no Google client secret is needed on the server and the token is never stored or logged.
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass

from django.conf import settings

log = logging.getLogger("accounts.google")


class GoogleTokenInvalid(Exception):
    """The token is not a valid, unexpired Google ID token for this app."""


class GoogleUnavailable(Exception):
    """Google's public keys could not be fetched (network)."""


@dataclass(frozen=True)
class GoogleIdentity:
    sub: str                # stable Google user id
    email: str
    email_verified: bool
    name: str


def client_ids() -> list[str]:
    return list(settings.NAZRIA_GOOGLE_CLIENT_IDS)


def enabled() -> bool:
    return bool(client_ids())


_request = None
_request_lock = threading.Lock()


def _transport():
    """One cached HTTP transport per process: Google's certificates are cached by their Cache-Control header."""
    global _request
    with _request_lock:
        if _request is None:
            import requests
            from google.auth.transport.requests import Request
            session = requests.Session()
            try:
                import cachecontrol                                   # optional: caches the certificates
                session = cachecontrol.CacheControl(session)
            except ImportError:
                pass
            _request = Request(session=session)
        return _request


def verify_google_token(token: str) -> GoogleIdentity:
    """Signature, expiry, issuer (accounts.google.com) and audience (one of NAZRIA_GOOGLE_CLIENT_IDS)."""
    from google.auth import exceptions as gexc
    from google.oauth2 import id_token

    ids = client_ids()
    try:
        info = id_token.verify_oauth2_token(token, _transport(), audience=ids, clock_skew_in_seconds=10)
    except gexc.TransportError as e:
        log.error("google certificates unavailable: %s", type(e).__name__)
        raise GoogleUnavailable() from None
    except (ValueError, gexc.GoogleAuthError) as e:
        log.info("google token rejected: %s", type(e).__name__)
        raise GoogleTokenInvalid() from None
    if info.get("aud") not in ids or not info.get("sub"):
        raise GoogleTokenInvalid()
    return GoogleIdentity(sub=str(info["sub"]), email=str(info.get("email") or ""),
                          email_verified=bool(info.get("email_verified")), name=str(info.get("name") or "")[:150])


# tests replace this (accounts.google.set_verifier)
_verifier = verify_google_token


def verify(token: str) -> GoogleIdentity:
    return _verifier(token)


def set_verifier(fn) -> None:
    global _verifier
    _verifier = fn or verify_google_token
