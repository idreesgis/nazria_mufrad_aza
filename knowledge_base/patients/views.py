"""/api/v1/patients/: the patients an account consults for, their general info and its change history."""
from __future__ import annotations

from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import is_staff_user
from accounts.permissions import HasAppKey
from audit.middleware import audit
from consultations.serializers import ErrorOut

from . import serializers as S
from .intake import intake_payload
from .models import Patient, record_revision


def own_patients(request):
    return Patient.objects.filter(account=request.user, deleted_at__isnull=True)


def patient_for(request, pk, include_deleted_for_staff: bool = True) -> Patient | None:
    """The caller's own (not hidden) patient; staff may open any patient, hidden ones included."""
    try:
        if is_staff_user(request.user):
            qs = Patient.objects.all() if include_deleted_for_staff else Patient.objects.filter(deleted_at__isnull=True)
            return qs.filter(pk=pk).first()
        return own_patients(request).filter(pk=pk).first()
    except (ValueError, TypeError):
        return None


def create_patient(request, data: dict) -> Patient:
    """Validated PatientIn data → a new patient of the caller (with its first revision and an audit row)."""
    data = {k: v for k, v in data.items() if k != "consent"}
    with transaction.atomic():
        p = Patient.objects.create(account=request.user, consent_at=timezone.now(), **data)
        record_revision(p, request.user, "created", list(data))
    audit(request, "patient.create", "patient", p.id, relation=p.relation)
    return p


def _not_found():
    return Response({"error": "not_found", "detail": "no such patient"}, status=404)


class IntakeFormView(APIView):
    """The general-info form to show before the first diagnosis of a NEW patient (Urdu labels, in order).
    Send the answers to POST /patients/ (or as "new_patient" in POST /consultations/)."""
    permission_classes = [HasAppKey]

    @extend_schema(responses={200: S.IntakeFormOut})
    def get(self, request):
        return Response(intake_payload())


class PatientListCreateView(generics.ListAPIView):
    """GET: the account's patients (search by name). POST: add a patient (general info + consent)."""
    serializer_class = S.PatientOut

    def get_queryset(self):
        qs = own_patients(self.request)
        term = (self.request.query_params.get("search") or "").strip()
        if term:
            qs = qs.filter(Q(full_name__icontains=term))
        return S.with_counts(qs).order_by("full_name", "created_at")

    @extend_schema(parameters=[OpenApiParameter("search", str, description="part of the name")])
    def get(self, request, *args, **kwargs):
        page = self.paginate_queryset(self.get_queryset())
        audit(request, "patient.list", "user", request.user.pk)
        return self.get_paginated_response([S.patient_out(p) for p in page])

    @extend_schema(request=S.PatientIn, responses={201: S.PatientOut, 400: ErrorOut})
    def post(self, request):
        data = S.PatientIn(data=request.data)
        data.is_valid(raise_exception=True)
        p = create_patient(request, data.validated_data)
        return Response(S.patient_out(p), status=status.HTTP_201_CREATED)


class PatientDetailView(APIView):
    """One patient with their diagnoses and pulse analyses. PATCH updates the general info (every change is kept in
    /history/). DELETE hides the patient from the account; everything is kept."""

    @extend_schema(responses={200: S.PatientOut, 404: ErrorOut})
    def get(self, request, pk):
        p = patient_for(request, pk)
        if p is None:
            return _not_found()
        audit(request, "patient.view", "patient", p.id)
        return Response(S.patient_out(p))

    @extend_schema(request=S.PatientIn, responses={200: S.PatientOut, 400: ErrorOut, 404: ErrorOut})
    def patch(self, request, pk):
        p = patient_for(request, pk, include_deleted_for_staff=False)
        if p is None:
            return _not_found()
        data = S.PatientIn(p, data=request.data, partial=True)
        data.is_valid(raise_exception=True)
        changes = {k: v for k, v in data.validated_data.items() if k != "consent" and getattr(p, k) != v}
        if changes:
            with transaction.atomic():
                for k, v in changes.items():
                    setattr(p, k, v)
                p.updated_at = timezone.now()
                p.save()
                record_revision(p, request.user, "updated", list(changes))
            audit(request, "patient.update", "patient", p.id, fields=sorted(changes))
        return Response(S.patient_out(p))

    @extend_schema(responses={204: None, 404: ErrorOut})
    def delete(self, request, pk):
        p = patient_for(request, pk, include_deleted_for_staff=False)
        if p is None:
            return _not_found()
        with transaction.atomic():
            Patient.objects.filter(pk=p.pk).update(deleted_at=timezone.now())
            p.refresh_from_db()
            record_revision(p, request.user, "deleted")
        audit(request, "patient.delete", "patient", p.id)
        return Response(status=status.HTTP_204_NO_CONTENT)


class PatientHistoryView(generics.GenericAPIView):
    """Every change to the patient's general info, newest first (who, when, which fields, the info after it)."""
    serializer_class = S.RevisionOut

    @extend_schema(responses={200: S.RevisionOut(many=True), 404: ErrorOut})
    def get(self, request, pk):
        p = patient_for(request, pk)
        if p is None:
            return _not_found()
        page = self.paginate_queryset(p.revisions.all())
        audit(request, "patient.history", "patient", p.id)
        return self.get_paginated_response(S.RevisionOut(page, many=True).data)
