"""The language of a request's patient-facing text: ur | en | ar.

Order: ``?lang=`` → ``Accept-Language`` → the logged-in user's saved language → Urdu. Responses carry
``Content-Language``."""
from __future__ import annotations

from nazria_kb.i18n import DEFAULT_LANGUAGE, from_accept_language, normalize_lang


def request_language(request) -> str:
    raw = getattr(request, "_request", request)
    cached = getattr(raw, "nazria_lang", None)
    if cached:
        return cached
    params = getattr(request, "query_params", None) or getattr(raw, "GET", {})
    lang = normalize_lang(params.get("lang")) or from_accept_language(raw.META.get("HTTP_ACCEPT_LANGUAGE"))
    if not lang:
        user = getattr(request, "user", None)
        if user is not None and getattr(user, "is_authenticated", False):
            from accounts.models import PatientProfile
            lang = normalize_lang(PatientProfile.objects.filter(user=user).values_list("language", flat=True).first())
    lang = lang or DEFAULT_LANGUAGE
    raw.nazria_lang = lang
    return lang


class ContentLanguageMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        lang = getattr(request, "nazria_lang", None)
        if lang and not response.has_header("Content-Language"):
            response["Content-Language"] = lang
        return response
