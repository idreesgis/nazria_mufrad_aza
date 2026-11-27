"""Staff (Hakeem / admin): find accounts and patients, and see their complete history (hidden items included)."""
from django.contrib.auth import get_user_model
from django.db.models import Count, Max, Q
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import generics, serializers
from rest_framework.response import Response
from rest_framework.views import APIView

from audit.middleware import audit
from consultations.models import Consultation
from consultations.serializers import ErrorOut
from consultations.views import summaries
from pulse.models import PulseAnalysis

from .models import PatientProfile, role_of
from .permissions import HasAppKey, IsStaff
from nazria_api.language import request_language

from .views import profile_of

User = get_user_model()


def _pulses(qs) -> list[dict]:
    return [{"id": str(p.id), "status": p.status, "method": p.method, "created_at": p.created_at,
             "patient": str(p.patient_id) if p.patient_id else None,
             "consultation": str(p.consultation_id) if p.consultation_id else None,
             "average_heart_rate_bpm": (p.result or {}).get("average_heart_rate_bpm"),
             "deleted": p.deleted_at is not None} for p in qs]


# ---------------------------------------------------------------------------------------------- accounts
class AccountRowOut(serializers.Serializer):
    id = serializers.IntegerField()
    phone = serializers.CharField(allow_null=True)
    email = serializers.CharField(allow_blank=True)
    full_name = serializers.CharField()
    created_at = serializers.DateTimeField()
    last_login = serializers.DateTimeField(allow_null=True)
    patients = serializers.IntegerField()
    consultations = serializers.IntegerField()
    pulse_analyses = serializers.IntegerField()
    is_active = serializers.BooleanField()


class AccountListView(generics.ListAPIView):
    """All accounts (search by phone, name or e-mail), newest first."""
    permission_classes = [HasAppKey, IsStaff]
    serializer_class = AccountRowOut

    @extend_schema(parameters=[OpenApiParameter("search", str, description="part of the phone number, name or e-mail")])
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    def get_queryset(self):
        q = PatientProfile.objects.select_related("user").annotate(
            n_patients=Count("user__patients", distinct=True),
            n_consultations=Count("user__consultations", distinct=True),
            n_pulse=Count("user__pulse_analyses", distinct=True)).order_by("-created_at", "-pk")
        term = (self.request.query_params.get("search") or "").strip()
        if term:
            q = q.filter(Q(phone__icontains=term) | Q(full_name__icontains=term) | Q(user__email__icontains=term))
        return q

    def list(self, request, *args, **kwargs):
        page = self.paginate_queryset(self.get_queryset())
        audit(request, "staff.accounts.list", "", None, search=bool(request.query_params.get("search")))
        return self.get_paginated_response([
            {"id": p.user_id, "phone": p.phone or None, "email": p.user.email or "", "full_name": p.full_name,
             "created_at": p.created_at, "last_login": p.user.last_login, "patients": p.n_patients,
             "consultations": p.n_consultations, "pulse_analyses": p.n_pulse, "is_active": p.user.is_active}
            for p in page])


class AccountHistoryView(APIView):
    """One account: profile, its patients (hidden ones too), every consultation and pulse analysis."""
    permission_classes = [HasAppKey, IsStaff]

    @extend_schema(responses={200: dict, 404: ErrorOut})
    def get(self, request, pk):
        from patients.serializers import patient_out, with_counts
        user = User.objects.filter(pk=pk).first()
        if user is None:
            return Response({"error": "not_found", "detail": "no such user"}, status=404)
        audit(request, "staff.account.view", "user", user.pk)
        return Response({
            "profile": {**profile_of(user), "is_active": user.is_active, "last_login": user.last_login,
                        "role": role_of(user)},
            "patients": [patient_out(p) for p in with_counts(user.patients.all())],
            "consultations": summaries(list(Consultation.objects.filter(account=user)), request_language(request)),
            "pulse_analyses": _pulses(PulseAnalysis.objects.filter(account=user)),
        })


# ---------------------------------------------------------------------------------------------- patients
class StaffPatientRowOut(serializers.Serializer):
    id = serializers.UUIDField()
    full_name = serializers.CharField()
    relation = serializers.CharField()
    gender = serializers.CharField(allow_blank=True)
    age = serializers.IntegerField(allow_null=True)
    account = serializers.IntegerField()
    account_phone = serializers.CharField(allow_null=True)
    consultations = serializers.IntegerField()
    pulse_analyses = serializers.IntegerField()
    last_consultation_at = serializers.DateTimeField(allow_null=True)
    deleted = serializers.BooleanField()


class StaffPatientListView(generics.ListAPIView):
    """All patients of all accounts (search by patient name, or the account's phone, name or e-mail)."""
    permission_classes = [HasAppKey, IsStaff]
    serializer_class = StaffPatientRowOut

    @extend_schema(parameters=[OpenApiParameter("search", str,
                                                description="patient name, or the account's phone, name or e-mail")])
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    def get_queryset(self):
        from patients.models import Patient
        q = Patient.objects.select_related("account", "account__profile").annotate(
            n_consultations=Count("consultations", distinct=True), n_pulse=Count("pulse_analyses", distinct=True),
            last_at=Max("consultations__created_at")).order_by("-created_at", "pk")
        term = (self.request.query_params.get("search") or "").strip()
        if term:
            q = q.filter(Q(full_name__icontains=term) | Q(account__profile__phone__icontains=term)
                         | Q(account__profile__full_name__icontains=term) | Q(account__email__icontains=term))
        return q

    def list(self, request, *args, **kwargs):
        page = self.paginate_queryset(self.get_queryset())
        audit(request, "staff.patients.list", "", None, search=bool(request.query_params.get("search")))

        def phone(p):
            prof = getattr(p.account, "profile", None)
            return prof.phone if prof else None
        return self.get_paginated_response([
            {"id": p.id, "full_name": p.full_name, "relation": p.relation, "gender": p.gender, "age": p.age,
             "account": p.account_id, "account_phone": phone(p), "consultations": p.n_consultations,
             "pulse_analyses": p.n_pulse, "last_consultation_at": p.last_at, "deleted": p.deleted_at is not None}
            for p in page])


class StaffPatientHistoryView(APIView):
    """One patient's complete history: general info, every change to it, every diagnosis and pulse analysis."""
    permission_classes = [HasAppKey, IsStaff]

    @extend_schema(responses={200: dict, 404: ErrorOut})
    def get(self, request, pk):
        from patients.models import Patient
        from patients.serializers import RevisionOut, patient_out
        p = Patient.objects.filter(pk=pk).first()
        if p is None:
            return Response({"error": "not_found", "detail": "no such patient"}, status=404)
        audit(request, "staff.patient.view", "patient", p.id)
        return Response({
            "patient": patient_out(p),
            "account": {**profile_of(p.account), "is_active": p.account.is_active},
            "revisions": RevisionOut(p.revisions.all(), many=True).data,
            "consultations": summaries(list(Consultation.objects.filter(patient=p)), request_language(request)),
            "pulse_analyses": _pulses(PulseAnalysis.objects.filter(patient=p)),
        })
