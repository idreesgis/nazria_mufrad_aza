"""Pulse video upload and analysis (moved here from the former pulse_diagnosis project)."""
from __future__ import annotations

import uuid

from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import generics, serializers, status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import is_staff_user
from accounts.throttles import PulseRateThrottle, UserRateThrottle
from audit.middleware import audit
from consultations.models import Consultation
from consultations.serializers import ErrorOut

from .models import PulseAnalysis
from nazria_api.language import request_language
from .serializers import PulseAnalysisOut, PulseUploadIn
from .service import run_analysis

SYMPTOM_SUGGESTIONS = {
    "general": ["Fatigue and lethargy", "Feeling of internal heat", "Feeling cold internally", "Excessive sweating",
                "Weight gain", "Weight loss", "Fever or chills"],
    "digestive": ["Poor appetite", "Excessive appetite", "Constipation with dry stools", "Loose stools or diarrhea",
                  "Bloating and gas", "Heartburn", "Nausea", "Excessive thirst"],
    "neurological": ["Headaches", "Dizziness", "Anxiety and worry", "Irritability and anger",
                     "Difficulty concentrating", "Poor memory", "Insomnia", "Excessive sleep"],
    "musculoskeletal": ["Joint pain", "Joint stiffness", "Muscle cramps", "Muscle weakness", "Body heaviness"],
    "skin": ["Dry skin", "Oily skin", "Acne", "Skin rashes", "Itching", "Pale complexion"],
    "respiratory": ["Shortness of breath", "Cough", "Excessive mucus/phlegm", "Chest congestion"],
    "urinary": ["Frequent urination", "Burning urination", "Dark urine", "Reduced urination"],
    "circulatory": ["Cold hands and feet", "Swelling in extremities", "Bleeding gums", "Easy bruising"],
}


def out(a: PulseAnalysis, lang: str = "ur") -> dict:
    from nazria_kb.i18n import DIRECTION

    from .i18n import DISCLAIMER as DISCLAIMERS, error_text, summary
    return {**PulseAnalysisOut(a).data, "error": error_text(a.error, lang), "error_en": a.error,
            "summary": summary(a.result, lang), "language": lang, "direction": DIRECTION[lang],
            "disclaimer": DISCLAIMERS[lang]}


def visible(request):
    """Analyses the caller may see: their own (not deleted); staff see all, deleted included."""
    if is_staff_user(request.user):
        return PulseAnalysis.objects.all()
    return PulseAnalysis.objects.filter(account=request.user, deleted_at__isnull=True)


class PulseListCreateView(generics.ListAPIView):
    """GET: the account's pulse analyses, newest first (?patient=<id> for one patient). POST (multipart): upload a
    patient's video and analyse it (takes seconds)."""
    serializer_class = PulseAnalysisOut
    parser_classes = [MultiPartParser, FormParser]

    def get_throttles(self):
        return [PulseRateThrottle(), UserRateThrottle()] if self.request.method == "POST" else super().get_throttles()

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
        return self.get_paginated_response([out(a, request_language(request)) for a in page])

    @extend_schema(request={"multipart/form-data": PulseUploadIn}, responses={201: PulseAnalysisOut, 400: ErrorOut})
    def post(self, request):
        data = PulseUploadIn(data=request.data)
        data.is_valid(raise_exception=True)
        d = data.validated_data
        from patients.views import patient_for
        consultation, patient = None, None
        if d.get("consultation"):
            consultation = Consultation.objects.filter(session_uid=d["consultation"], account=request.user,
                                                       deleted_at__isnull=True).first()
            if consultation is None:
                return Response({"error": "invalid_request", "detail": "no such consultation",
                                 "fields": {"consultation": "not one of your consultations"}}, status=400)
            patient = consultation.patient
        if d.get("patient"):
            chosen = patient_for(request, d["patient"], include_deleted_for_staff=False)
            if chosen is None or (patient is not None and chosen.pk != patient.pk):
                return Response({"error": "invalid_request", "detail": "no such patient",
                                 "fields": {"patient": "not one of your patients, or not the consultation's"}},
                                status=400)
            patient = chosen
        if patient is None:
            return Response({"error": "patient_required", "detail": "choose the patient of this pulse video",
                             "fields": {"patient": "required"}}, status=400)
        a = PulseAnalysis(account=patient.account, patient=patient, consultation=consultation, method=d["method"],
                          symptoms=d.get("symptoms") or [], video_size=d["video"].size)
        a.video.save(d["video"].name, d["video"], save=False)
        a.save()
        run_analysis(a)
        audit(request, "pulse.upload", "pulse_analysis", a.id, method=a.method, status=a.status,
              size_kb=a.video_size // 1024, consultation=str(consultation.pk) if consultation else None,
              patient=str(patient.id))
        return Response(out(a, request_language(request)), status=status.HTTP_201_CREATED)


class PulseDetailView(APIView):
    """One pulse analysis. DELETE hides it from your history (it is kept on the server)."""

    def _get(self, request, pk):
        return visible(request).filter(pk=pk).first()

    @extend_schema(responses={200: PulseAnalysisOut, 404: ErrorOut})
    def get(self, request, pk):
        a = self._get(request, pk)
        if a is None:
            return Response({"error": "not_found", "detail": "no such pulse analysis"}, status=404)
        audit(request, "pulse.view", "pulse_analysis", a.id)
        return Response(out(a, request_language(request)))

    @extend_schema(responses={204: None, 404: ErrorOut})
    def delete(self, request, pk):
        a = self._get(request, pk)
        if a is None or a.deleted_at:
            return Response({"error": "not_found", "detail": "no such pulse analysis"}, status=404)
        PulseAnalysis.objects.filter(pk=a.pk).update(deleted_at=timezone.now())
        audit(request, "pulse.delete", "pulse_analysis", a.id)
        return Response(status=status.HTTP_204_NO_CONTENT)


class SymptomSuggestionsOut(serializers.Serializer):
    symptom_categories = serializers.DictField(child=serializers.ListField(child=serializers.CharField()))


class SymptomSuggestionsView(APIView):
    """Free-text symptom suggestions for the pulse upload screen (from the former pulse_diagnosis project)."""

    @extend_schema(responses={200: SymptomSuggestionsOut})
    def get(self, request):
        return Response({"symptom_categories": SYMPTOM_SUGGESTIONS})
