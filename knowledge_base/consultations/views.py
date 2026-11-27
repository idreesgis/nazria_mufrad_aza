"""REST endpoints for the Android app (all under /api/v1/). See docs/API.md for the flow and examples."""
from __future__ import annotations

import logging

from django.db import DatabaseError as DjangoDatabaseError
from django.db import transaction
from django.utils import timezone
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import generics, status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.views import exception_handler as drf_exception_handler

from accounts import google as google_login
from accounts.models import is_staff_user
from accounts.permissions import HasAppKey
from accounts.throttles import ExplanationRateThrottle, UserRateThrottle
from audit.middleware import audit

from . import serializers as S
from . import services
from .backends import knowledge_base
from .models import Consultation

log = logging.getLogger("consultations")


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
                "explanation_enabled": services.explanation_enabled(), "google_login_enabled": google_login.enabled(),
                "api_version": services.API_VERSION}
        return Response(body, status=200 if db == "ok" else 503)


class QuestionnaireView(APIView):
    """The questions and options the app shows, in order (as edited by a Hakeem in the database). No login needed."""
    permission_classes = [HasAppKey]

    @extend_schema(responses={200: S.QuestionnaireOut})
    def get(self, request):
        return Response(services.questionnaire_payload(knowledge_base().questions()))


class TriageView(APIView):
    """Emergency check for the first answers. Call it after the red-flag question (and after the complaint).
    No login needed: an emergency must never wait for a login."""
    permission_classes = [HasAppKey]

    @extend_schema(request=S.TriageRequest, responses={200: S.TriageOut, 400: S.ErrorOut})
    def post(self, request):
        req = S.TriageRequest(data=request.data)
        req.is_valid(raise_exception=True)
        known = {o.key for q in knowledge_base().questions() if q.stage == "triage" for o in q.options}
        bad = [f for f in req.validated_data["red_flags"] if f not in known]
        if bad:
            return _error("invalid_request", "unknown red-flag option", 400, {"red_flags": f"unknown: {bad}"})
        result = services.triage(req.validated_data["red_flags"], req.validated_data.get("complaint"))
        audit(request, "triage", "", None, emergency=result["emergency"], flags=result["flags"])
        return Response(result)


def consultation_body(c: Consultation, session) -> dict:
    payload = dict(session.result.get("api") or {})
    pulses = [{"id": str(p.id), "status": p.status, "method": p.method, "created_at": p.created_at,
               "average_heart_rate_bpm": (p.result or {}).get("average_heart_rate_bpm")}
              for p in c.pulse_analyses.all() if p.deleted_at is None]
    return {"id": str(c.session_uid), "patient": c.patient_id, **payload,
            "explanation": session.result.get("explanation"),
            "explanation_available": payload.get("status") == "completed" and services.explanation_enabled(),
            "pulse_analyses": pulses, "deleted": c.deleted_at is not None}


def summaries(consultations: list[Consultation]) -> list[dict]:
    extra = knowledge_base().session_summaries([str(c.session_uid) for c in consultations])
    return [{"id": str(c.session_uid), "status": c.status, "created_at": c.created_at,
             "primary_system": c.primary_system or None, "explanation_status": c.explanation_status or None,
             "complaint": extra.get(str(c.session_uid), {}).get("complaint", ""), "deleted": c.deleted_at is not None}
            for c in consultations]


def visible(request):
    """Consultations the caller may see: their own (not hidden); staff see all, hidden ones included."""
    if is_staff_user(request.user):
        return Consultation.objects.all()
    return Consultation.objects.filter(patient=request.user, deleted_at__isnull=True)


class ConsultationListCreateView(generics.ListAPIView):
    """GET: your consultation history, newest first. POST: submit all answers and get the assessment
    (or the emergency referral); it is stored in your history."""
    serializer_class = S.ConsultationSummaryOut

    def get_queryset(self):
        return visible(self.request).filter(patient=self.request.user)

    def list(self, request, *args, **kwargs):
        page = self.paginate_queryset(self.get_queryset())
        audit(request, "consultation.list", "user", request.user.pk)
        return self.get_paginated_response(summaries(page))

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
        with transaction.atomic():
            kb.save_session(s)
            c = Consultation.objects.create(session_uid=s.session_uid, patient=request.user,
                                            client=getattr(request._request, "api_client", None), status=s.status,
                                            primary_system=s.result.get("primary_system") or "")
        audit(request, "consultation.create", "consultation", c.session_uid, status=c.status,
              primary_system=c.primary_system or None)
        return Response(consultation_body(c, s), status=status.HTTP_201_CREATED)


class _VisibleConsultation(APIView):
    def _get(self, request, pk):
        c = visible(request).filter(session_uid=pk).first()
        s = knowledge_base().load_session(str(pk)) if c else None
        if s is None:
            return None, None, _error("not_found", "no such consultation", 404)
        return c, s, None


class ConsultationDetailView(_VisibleConsultation):
    """One consultation. DELETE hides it from your history (everything is kept on the server)."""

    @extend_schema(responses={200: S.ConsultationOut, 404: S.ErrorOut})
    def get(self, request, pk):
        c, s, err = self._get(request, pk)
        if err:
            return err
        audit(request, "consultation.view", "consultation", pk)
        return Response(consultation_body(c, s))

    @extend_schema(responses={204: None, 404: S.ErrorOut})
    def delete(self, request, pk):
        c, s, err = self._get(request, pk)
        if err or c.deleted_at:
            return err or _error("not_found", "no such consultation", 404)
        Consultation.objects.filter(pk=c.pk).update(deleted_at=timezone.now(), deleted_by=request.user)
        audit(request, "consultation.delete", "consultation", pk)
        return Response(status=status.HTTP_204_NO_CONTENT)


class ExplanationView(_VisibleConsultation):
    """AI explanation of a completed result in plain Urdu, using only book passages (may take 10–30 s).
    Returns status "disabled" while the server runs with NAZRIA_ENGINE=questionnaire."""

    def get_throttles(self):
        return [ExplanationRateThrottle(), UserRateThrottle()]

    @extend_schema(request=None, responses={200: S.ExplanationOut, 404: S.ErrorOut, 409: S.ErrorOut,
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
        audit(request, "consultation.explain", "consultation", pk, status=result["status"],
              reason=result.get("reason"), model=result.get("model"))
        return Response(result)
