"""Sign in with Microsoft from a phone: allauth's Microsoft provider only does the web redirect flow, so this subclass
adds ``verify_token`` for an ID token the app got itself (AppAuth, authorization code + PKCE, public client).

Registered through ``SOCIALACCOUNT_PROVIDERS["microsoft"]["provider_class"]``; the provider id stays "microsoft".

Checks: the signature (Microsoft's published keys), the audience (our client ID), the expiry, and the issuer
``https://login.microsoftonline.com/{tid}/v2.0``. With ``TENANT`` = "common" any work, school or personal account
is accepted; "consumers" only personal accounts; "organizations" only work or school accounts; a tenant ID only that
organisation.
"""
from __future__ import annotations

import requests
from django.http import HttpRequest

from allauth.socialaccount.adapter import get_adapter
from allauth.socialaccount.internal import jwtkit
from allauth.socialaccount.providers.microsoft.provider import MicrosoftGraphProvider
from allauth.socialaccount.providers.oauth2.client import OAuth2Error

KEYS_URL = "https://login.microsoftonline.com/common/discovery/v2.0/keys"
PERSONAL_TENANT = "9188040d-6c67-4c5b-b112-36a304b66dad"      # Microsoft's fixed tenant of all personal accounts


def tenant_allowed(configured: str, tid: str) -> bool:
    configured = (configured or "common").lower()
    if configured == "common":
        return True
    if configured == "consumers":
        return tid == PERSONAL_TENANT
    if configured == "organizations":
        return tid != PERSONAL_TENANT
    return tid == configured


class MicrosoftTokenProvider(MicrosoftGraphProvider):
    def tenant(self) -> str:
        s = self.get_settings()
        return str(s.get("TENANT", s.get("tenant", "common")))

    def verify_token(self, request: HttpRequest, token):
        id_token = token.get("id_token")
        if not id_token:
            raise get_adapter().validation_error("invalid_token")
        try:
            data = jwtkit.verify_and_decode(credential=id_token, keys_url=KEYS_URL, issuer=None,
                                            audience=[self.app.client_id], lookup_kid=jwtkit.lookup_kid_jwk)
        except (OAuth2Error, requests.RequestException) as e:
            raise get_adapter().validation_error("invalid_token") from e
        tid = str(data.get("tid") or "")
        if (not tid or data.get("iss") != f"https://login.microsoftonline.com/{tid}/v2.0"
                or not tenant_allowed(self.tenant(), tid) or not (data.get("oid") or data.get("sub"))):
            raise get_adapter().validation_error("invalid_token")
        # the shape of a Microsoft Graph /me answer, which the parent provider reads; "id" = the object id (oid),
        # the same for this person in every app of the tenant
        graph = {"id": str(data.get("oid") or data["sub"]), "displayName": data.get("name") or "",
                 "mail": data.get("email") or "", "userPrincipalName": data.get("preferred_username") or "",
                 "tid": tid}
        return self.sociallogin_from_response(request, graph)

    def extract_email_addresses(self, data):
        return []      # a Microsoft "email" claim is not verified for work accounts: never trusted as verified


provider_classes = [MicrosoftTokenProvider]
