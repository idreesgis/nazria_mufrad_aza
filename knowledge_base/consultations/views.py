"""REST endpoints for the Android app (all under /api/v1/). See docs/API.md for the flow and examples."""
from __future__ import annotations

import logging
import uuid

from django.db import DatabaseError as DjangoDatabaseError
from django.db import transaction
from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
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
    return {"id": str(c.session_uid), "account": c.account_id, "patient": c.patient_snapshot or None,
            "rediagnosis_of": str(c.rediagnosis_of_id) if c.rediagnosis_of_id else None,
            "prefilled_answers": session.result.get("prefilled_answers") or {}, **payload,
            "explanation": session.result.get("explanation"),
            "explanation_available": payload.get("status") == "completed" and services.explanation_enabled(),
            "pulse_analyses": pulses, "deleted": c.deleted_at is not None}


def summaries(consultations: list[Consultation]) -> list[dict]:
    extra = knowledge_base().session_summaries([str(c.session_uid) for c in consultations])
    return [{"id": str(c.session_uid), "status": c.status, "created_at": c.created_at,
             "patient": ({"id": str(c.patient_id), "full_name": c.patient_snapshot.get("full_name", ""),
                          "relation": c.patient_snapshot.get("relation", "")} if c.patient_id else None),
             "rediagnosis_of": str(c.rediagnosis_of_id) if c.rediagnosis_of_id else None,
             "primary_system": c.primary_system or None, "explanation_status": c.explanation_status or None,
             "complaint": extra.get(str(c.session_uid), {}).get("complaint", ""), "deleted": c.deleted_at is not None}
            for c in consultations]


def visible(request):
    """Consultations the caller may see: their account's (not hidden); staff see all, hidden ones included."""
    if is_staff_user(request.user):
        return Consultation.objects.all()
    return Consultation.objects.filter(account=request.user, deleted_at__isnull=True)


def _patient_required():
    return _error("patient_required", "choose a patient (patient_id) or add one (new_patient)", 400,
                  {"patient_id": "required"})


def diagnose(request, raw_answers: dict, patient, new_patient_data: dict | None = None, rediagnosis_of=None):
    """Validate (with the answers the patient's info gives), run, and store one diagnosis. ``patient`` is an existing
    Patient, or None with ``new_patient_data`` (created in the same transaction), or None for an emergency."""
    from patients.intake import answers_from_patient
    from patients.models import Patient
    from patients.views import create_patient

    probe = patient or (Patient(**{k: v for k, v in new_patient_data.items() if k != "consent"})
                        if new_patient_data else None)
    prefilled = answers_from_patient(probe) if probe else {}
    kb = knowledge_base()
    questions = kb.questions()
    known = {q.id for q in questions}
    prefilled = {k: v for k, v in prefilled.items() if k in known}
    answers = services.validate_answers(questions, {**raw_answers, **prefilled})
    outcome = services.run_consultation(kb, questions, answers, health=probe.health() if probe else None)
    s = outcome.session
    if probe is None and s.status != "emergency":
        return None, None, _patient_required()
    s.result["prefilled_answers"] = prefilled
    with transaction.atomic():
        if patient is None and new_patient_data:
            patient = create_patient(request, new_patient_data)
        kb.save_session(s)
        c = Consultation.objects.create(
            session_uid=s.session_uid, account=patient.account if patient else request.user, patient=patient,
            patient_snapshot=patient.snapshot() if patient else {}, rediagnosis_of=rediagnosis_of,
            client=getattr(request._request, "api_client", None), status=s.status,
            primary_system=s.result.get("primary_system") or "")
    extra = {"rediagnosis_of": str(rediagnosis_of.pk)} if rediagnosis_of else {}
    audit(request, "consultation.rediagnose" if rediagnosis_of else "consultation.create", "consultation",
          c.session_uid, status=c.status, primary_system=c.primary_system or None,
          patient=str(patient.id) if patient else None, **extra)
    return c, s, None


class ConsultationListCreateView(generics.ListAPIView):
    """GET: the account's diagnoses, newest first (?patient=<id> for one patient). POST: diagnose a patient: send all
    answers with either patient_id (an existing patient: re-diagnosis) or new_patient (their general info, asked
    first for a new patient). Returns the assessment (or the emergency referral), stored in the patient's history."""
    serializer_class = S.ConsultationSummaryOut

    def get_queryset(self):
        qs = visible(self.request).filter(account=self.request.user)
        pid = self.request.query_params.get("patient")
        if pid:
            try:
                qs = qs.filter(patient_id=uuid.UUID(pid))
            except ValueError:
                qs = qs.none()
        return qs

    @extend_schema(parameters=[OpenApiParameter("patient", OpenApiTypes.UUID, description="only this patient")])
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    def list(self, request, *args, **kwargs):
        page = self.paginate_queryset(self.get_queryset())
        audit(request, "consultation.list", "user", request.user.pk,
              patient=request.query_params.get("patient") or None)
        return self.get_paginated_response(summaries(page))

    @extend_schema(request=S.ConsultationRequest,
                   responses={201: S.ConsultationOut, 400: S.ErrorOut, 404: S.ErrorOut, 503: S.ErrorOut})
    def post(self, request):
        from patients.serializers import PatientIn
        from patients.views import patient_for
        req = S.ConsultationRequest(data=request.data)
        req.is_valid(raise_exception=True)
        d = req.validated_data
        patient, new_data = None, None
        if d.get("patient_id"):
            patient = patient_for(request, d["patient_id"], include_deleted_for_staff=False)
            if patient is None:
                return _error("not_found", "no such patient", 404, {"patient_id": "not one of your patients"})
        elif d.get("new_patient"):
            pin = PatientIn(data=d["new_patient"])
            if not pin.is_valid():
                return _error("invalid_patient", "the new patient's information is not valid", 400,
                              {f"new_patient.{k}": " ".join(map(str, v)) if isinstance(v, list) else str(v)
                               for k, v in pin.errors.items()})
            new_data = pin.validated_data
        c, s, err = diagnose(request, d["answers"], patient, new_data)
        if err:
            return err
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


class RediagnoseView(_VisibleConsultation):
    """Diagnose the same patient again from an earlier diagnosis: its answers are reused, the ones sent here replace
    them, and the patient's CURRENT general info and the current book are used. A new diagnosis is stored (linked by
    rediagnosis_of); the earlier one stays unchanged."""

    @extend_schema(request=S.RediagnoseRequest,
                   responses={201: S.ConsultationOut, 400: S.ErrorOut, 404: S.ErrorOut})
    def post(self, request, pk):
        from patients.views import patient_for
        old, s_old, err = self._get(request, pk)
        if err:
            return err
        req = S.RediagnoseRequest(data=request.data)
        req.is_valid(raise_exception=True)
        d = req.validated_data
        pid = old.patient_id or d.get("patient_id")
        patient = patient_for(request, pid, include_deleted_for_staff=False) if pid else None
        if patient is None:
            return (_error("not_found", "no such patient", 404, {"patient_id": "not one of your patients"})
                    if pid else _patient_required())
        prefilled_before = (s_old.result or {}).get("prefilled_answers") or {}
        known = {q.id for q in knowledge_base().questions()}       # questions a Hakeem removed since are dropped
        previous = {k: v for k, v in s_old.answers.items() if k not in prefilled_before and k in known}
        c, s, err = diagnose(request, {**previous, **d["answers"]}, patient, rediagnosis_of=old)
        if err:
            return err
        return Response(consultation_body(c, s), status=status.HTTP_201_CREATED)


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
