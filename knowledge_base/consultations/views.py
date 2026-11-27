"""REST endpoints for the Android app (all under /api/v1/). See docs/API.md for the flow and examples."""
from __future__ import annotations

import logging

from django.db import DatabaseError as DjangoDatabaseError
from django.db import transaction
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.views import exception_handler as drf_exception_handler

from . import serializers as S
from . import services
from .authentication import ClientRateThrottle, ExplanationRateThrottle
from .backends import knowledge_base
from .models import Consultation

log = logging.getLogger("consultations")
TOKEN_HEADER = OpenApiParameter("X-Consultation-Token", str, OpenApiParameter.HEADER, required=True,
                                description="The access_token returned when the consultation was created")


def _error(code: str, detail: str, http: int, fields: dict | None = None) -> Response:
    body = {"error": code, "detail": detail}
    if fields:
        body["fields"] = fields
    return Response(body, status=http)


def exception_handler(exc, context):
    """Uniform {"error", "detail", "fields"?} bodies. Database errors never expose connection details."""
    if isinstance(exc, services.ValidationFailed):
        return _error("invalid_answers", "some answers are missing or invalid", 400, exc.fields)
    try:
        import psycopg
        db_errors = (DjangoDatabaseError, psycopg.Error)
    except ImportError:                                   # pragma: no cover
        db_errors = (DjangoDatabaseError,)
    if isinstance(exc, db_errors):
        log.error("database error: %s", type(exc).__name__)
        return _error("database_unavailable", "the knowledge base is not reachable, try again later", 503)
    response = drf_exception_handler(exc, context)
    if response is None:
        return None
    data = response.data
    if isinstance(data, dict) and "detail" in data and len(data) == 1:
        code = getattr(data["detail"], "code", "error")
        response.data = {"error": str(code), "detail": str(data["detail"])}
    elif isinstance(data, dict):
        response.data = {"error": "invalid_request", "detail": "the request is not valid",
                         "fields": {k: " ".join(map(str, v)) if isinstance(v, list) else str(v) for k, v in data.items()}}
    return response


class HealthView(APIView):
    """Liveness and database check (no API key needed)."""
    authentication_classes: list = []
    permission_classes = [AllowAny]

    @extend_schema(responses={200: S.HealthOut, 503: S.HealthOut}, auth=[])
    def get(self, request):
        try:
            knowledge_base().ping()
            db = "ok"
        except Exception as e:                           # noqa: BLE001 - report, never leak details
            log.error("health check: database %s", type(e).__name__)
            db = "unavailable"
        body = {"status": "ok" if db == "ok" else "degraded", "database": db,
                "explanation_enabled": services.explanation_enabled(), "api_version": services.API_VERSION}
        return Response(body, status=200 if db == "ok" else 503)


class QuestionnaireView(APIView):
    """The questions and options the app shows, in order (as edited by a Hakeem in the database)."""

    @extend_schema(responses={200: S.QuestionnaireOut})
    def get(self, request):
        return Response(services.questionnaire_payload(knowledge_base().questions()))


class TriageView(APIView):
    """Emergency check for the first answers. Call it after the red-flag question (and after the complaint)."""

    @extend_schema(request=S.TriageRequest, responses={200: S.TriageOut, 400: S.ErrorOut})
    def post(self, request):
        req = S.TriageRequest(data=request.data)
        req.is_valid(raise_exception=True)
        known = {o.key for q in knowledge_base().questions() if q.stage == "triage" for o in q.options}
        bad = [f for f in req.validated_data["red_flags"] if f not in known]
        if bad:
            return _error("invalid_request", "unknown red-flag option", 400, {"red_flags": f"unknown: {bad}"})
        return Response(services.triage(req.validated_data["red_flags"], req.validated_data.get("complaint")))


def _consultation_body(c: Consultation, session, token: str | None = None) -> dict:
    payload = dict(session.result.get("api") or {})
    body = {"id": str(c.session_uid), **({"access_token": token} if token else {}), **payload,
            "explanation": session.result.get("explanation"),
            "explanation_available": payload.get("status") == "completed" and services.explanation_enabled()}
    return body


class ConsultationCreateView(APIView):
    """Submit all answers; returns the assessment (or the emergency referral). Stored for later reading."""

    @extend_schema(request=S.ConsultationRequest,
                   responses={201: S.ConsultationOut, 400: S.ErrorOut, 503: S.ErrorOut})
    def post(self, request):
        req = S.ConsultationRequest(data=request.data)
        req.is_valid(raise_exception=True)
        kb = knowledge_base()
        questions = kb.questions()
        answers = services.validate_answers(questions, req.validated_data["answers"])
        outcome = services.run_consultation(kb, questions, answers)
        s = outcome.session
        token, token_hash = Consultation.new_token()
        with transaction.atomic():
            kb.save_session(s)
            c = Consultation.objects.create(session_uid=s.session_uid, client=request.auth, token_hash=token_hash,
                                            status=s.status, primary_system=s.result.get("primary_system") or "")
        return Response(_consultation_body(c, s, token), status=status.HTTP_201_CREATED)


class _OwnedConsultation(APIView):
    def _get(self, request, pk):
        c = Consultation.objects.filter(session_uid=pk).first()
        if c is None or not c.token_matches(request.headers.get("X-Consultation-Token")):
            return None, None, _error("not_found", "no such consultation", 404)
        s = knowledge_base().load_session(str(pk))
        if s is None:
            return None, None, _error("not_found", "no such consultation", 404)
        return c, s, None


class ConsultationDetailView(_OwnedConsultation):
    """Read a stored consultation again, or delete it (the patient's data is removed from the server)."""

    @extend_schema(parameters=[TOKEN_HEADER], responses={200: S.ConsultationOut, 404: S.ErrorOut})
    def get(self, request, pk):
        c, s, err = self._get(request, pk)
        return err or Response(_consultation_body(c, s))

    @extend_schema(parameters=[TOKEN_HEADER], responses={204: None, 404: S.ErrorOut})
    def delete(self, request, pk):
        c, s, err = self._get(request, pk)
        if err:
            return err
        with transaction.atomic():
            knowledge_base().delete_session(str(pk))
            c.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class ExplanationView(_OwnedConsultation):
    """AI explanation of a completed result in plain Urdu, using only book passages (may take 10–30 s).
    Returns status "disabled" while the server runs with NAZRIA_ENGINE=questionnaire."""
    throttle_classes = [ClientRateThrottle, ExplanationRateThrottle]

    @extend_schema(parameters=[TOKEN_HEADER], request=None,
                   responses={200: S.ExplanationOut, 404: S.ErrorOut, 409: S.ErrorOut,
                              429: OpenApiResponse(description="too many explanation requests")})
    def post(self, request, pk):
        c, s, err = self._get(request, pk)
        if err:
            return err
        if s.status != "completed":
            return _error("not_explainable", "only completed consultations can be explained", 409)
        result = services.explain(knowledge_base(), s)
        if c.explanation_status != result["status"]:
            Consultation.objects.filter(pk=c.pk).update(explanation_status=result["status"])
        return Response(result)
