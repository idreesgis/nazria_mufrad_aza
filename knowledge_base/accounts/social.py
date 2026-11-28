"""Social sign-in (Google, Facebook, Apple, Microsoft) through django-allauth.

The phone signs in with the provider's own SDK and sends the result to ``POST /api/v1/auth/social/<provider>/``:

=========  ==================================  ==========================================================
provider   the app sends                        checked by
=========  ==================================  ==========================================================
google     ``id_token`` (Credential Manager)    allauth: Google's keys, audience = one of our client IDs
facebook   ``access_token`` (Facebook SDK)      allauth: Facebook's debug_token (needs the app secret)
apple      ``id_token`` + ``nonce``             allauth: Apple's keys, audience = our Service ID; here: the
                                                nonce, which only the phone that started the sign-in knows
microsoft  ``id_token`` (AppAuth + PKCE)        ``social_providers.MicrosoftTokenProvider``
=========  ==================================  ==========================================================

allauth also stores the links (``socialaccount.SocialAccount``: provider + the provider's stable user id). Accounts
are never joined by e-mail address: a provider account belongs to a Nazria account only after it was used to create
it or was linked by its logged-in owner. Provider tokens are never stored or logged.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
from dataclasses import dataclass, field

import requests
from django.conf import settings
from django.core import signing
from django.core.exceptions import ValidationError

from allauth.socialaccount.adapter import DefaultSocialAccountAdapter

log = logging.getLogger("accounts.social")

PROVIDERS = ("google", "facebook", "apple", "microsoft")
NAMES = {"google": "Google", "facebook": "Facebook", "apple": "Apple", "microsoft": "Microsoft"}
SIGNUP_SALT = "nazria.social-signup"
SIGNUP_MAX_AGE_S = 600


class ProviderDisabled(Exception):
    """This provider is not set up on the server."""


class SocialTokenInvalid(Exception):
    """The token is not a valid, unexpired token of this provider for this app."""


class SocialUnavailable(Exception):
    """The provider could not be reached (network)."""


@dataclass(frozen=True)
class SocialIdentity:
    provider: str
    uid: str                      # the provider's stable user id (never the e-mail address)
    email: str = ""
    email_verified: bool = False
    name: str = ""
    extra: dict = field(default_factory=dict, compare=False)


# ------------------------------------------------------------------------------------------------- configuration
def _apps(provider: str) -> list[dict]:
    conf = (getattr(settings, "SOCIALACCOUNT_PROVIDERS", {}) or {}).get(provider) or {}
    return [a for a in conf.get("APPS") or [] if a.get("client_id")]


def client_ids(provider: str) -> list[str]:
    return [a["client_id"] for a in _apps(provider)]


def enabled(provider: str) -> bool:
    if provider not in PROVIDERS or not _apps(provider):
        return False
    if provider == "facebook":                       # debug_token needs the app secret
        return all(a.get("secret") for a in _apps(provider))
    return True


def enabled_providers() -> list[str]:
    return [p for p in PROVIDERS if enabled(p)]


def apple_callback_url() -> str:
    base = (getattr(settings, "NAZRIA_PUBLIC_URL", "") or "").rstrip("/")
    return f"{base}/api/v1/auth/apple/callback/" if base.startswith("https://") else ""


def public_config() -> dict:
    """What the app needs to start each sign-in (public identifiers only, never a secret)."""
    out: dict = {}
    if enabled("google"):
        out["google"] = {"client_id": client_ids("google")[0]}
    if enabled("facebook"):
        out["facebook"] = {"app_id": client_ids("facebook")[0]}
    if enabled("apple"):
        cb = apple_callback_url()
        out["apple"] = {"client_id": client_ids("apple")[0],
                        "start_url": cb.replace("/callback/", "/start/") if cb else None}
    if enabled("microsoft"):
        s = settings.SOCIALACCOUNT_PROVIDERS["microsoft"]
        out["microsoft"] = {"client_id": client_ids("microsoft")[0], "tenant": s.get("TENANT") or "common"}
    return out


# ------------------------------------------------------------------------------------------------- allauth adapter
class NazriaSocialAccountAdapter(DefaultSocialAccountAdapter):
    """Certificates and key sets are cached by their Cache-Control header (one HTTP cache per process); allauth's
    own web sign-up and auto-connect by e-mail are not used: the API creates and links accounts itself."""
    _cached_session = None

    def get_requests_session(self):
        session = super().get_requests_session()
        try:
            import cachecontrol
            if NazriaSocialAccountAdapter._cached_session is None:
                NazriaSocialAccountAdapter._cached_session = cachecontrol.CacheControlAdapter()
            session.mount("https://", NazriaSocialAccountAdapter._cached_session)
        except ImportError:
            pass
        return session

    def is_open_for_signup(self, request, sociallogin):
        return False


# ------------------------------------------------------------------------------------------------- verification
def _unverified_claims(jwt_token: str) -> dict:
    try:
        payload = jwt_token.split(".")[1]
        return json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    except (IndexError, ValueError, TypeError):
        return {}


def nonce_hash(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def _is_network(e: BaseException | None) -> bool:
    while e is not None:
        if isinstance(e, (requests.ConnectionError, requests.Timeout)):
            return True
        if isinstance(e, requests.HTTPError) and e.response is not None and e.response.status_code >= 500:
            return True
        e = e.__cause__ or e.__context__
    return False


def _identity(provider: str, login) -> SocialIdentity:
    acc = login.account
    emails = list(login.email_addresses or [])
    primary = next((e for e in emails if e.primary), emails[0] if emails else None)
    email = (primary.email if primary else "") or (login.user.email if login.user else "") or ""
    data = acc.extra_data or {}
    name = (data.get("name") or data.get("displayName")
            or " ".join(x for x in [getattr(login.user, "first_name", ""), getattr(login.user, "last_name", "")] if x))
    return SocialIdentity(provider=provider, uid=str(acc.uid), email=email[:254],
                          email_verified=bool(primary and primary.verified), name=str(name or "")[:150],
                          extra={k: data[k] for k in ("email", "name", "tid", "nonce") if k in data})


def verify_with_allauth(request, provider: str, token: dict) -> SocialIdentity:
    from allauth.socialaccount.adapter import get_adapter
    from allauth.socialaccount.providers.oauth2.client import OAuth2Error

    if not enabled(provider):
        raise ProviderDisabled()
    django_request = getattr(request, "_request", request)
    client_id = None
    if provider == "google":                       # several client IDs: pick the one the token was issued for
        client_id = _unverified_claims(token.get("id_token") or "").get("aud")
        if client_id not in client_ids("google"):
            raise SocialTokenInvalid()
    try:
        prov = get_adapter().get_provider(django_request, provider, client_id=client_id)
        login = prov.verify_token(django_request, token)
    except ValidationError as e:
        if _is_network(e):
            log.error("%s unavailable", provider)
            raise SocialUnavailable() from None
        log.info("%s token rejected", provider)
        raise SocialTokenInvalid() from None
    except requests.RequestException:
        log.error("%s unavailable", provider)
        raise SocialUnavailable() from None
    except (OAuth2Error, KeyError, ValueError, TypeError) as e:
        log.info("%s token rejected: %s", provider, type(e).__name__)
        raise SocialTokenInvalid() from None
    ident = _identity(provider, login)
    if provider == "apple":
        raw = token.get("nonce") or ""
        claim = str((login.account.extra_data or {}).get("nonce") or "")
        if not raw or not claim or not hmac.compare_digest(nonce_hash(raw), claim):
            log.info("apple token rejected: nonce")
            raise SocialTokenInvalid()
    return ident


# tests replace this (set_verifier); signature: (request, provider, token dict) -> SocialIdentity
_verifier = verify_with_allauth


def verify(request, provider: str, token: dict) -> SocialIdentity:
    if not enabled(provider):
        raise ProviderDisabled()
    return _verifier(request, provider, token)


def set_verifier(fn) -> None:
    global _verifier
    _verifier = fn or verify_with_allauth


# ------------------------------------------------------------------------------------------------- pending sign-up
def signup_token(ident: SocialIdentity) -> str:
    """A new account needs the patient's consent: instead of sending the provider token again (Google and Apple ID
    tokens can be used only once), the app sends this signed, 10-minute token back with ``consent: true``."""
    return signing.dumps({"p": ident.provider, "u": ident.uid, "e": ident.email, "v": ident.email_verified,
                          "n": ident.name}, salt=SIGNUP_SALT, compress=True)


def from_signup_token(value: str, provider: str) -> SocialIdentity:
    try:
        d = signing.loads(value, salt=SIGNUP_SALT, max_age=SIGNUP_MAX_AGE_S)
    except signing.BadSignature:
        raise SocialTokenInvalid() from None
    if d.get("p") != provider:
        raise SocialTokenInvalid()
    return SocialIdentity(provider=provider, uid=d["u"], email=d.get("e") or "", email_verified=bool(d.get("v")),
                          name=d.get("n") or "")
