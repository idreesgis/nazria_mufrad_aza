"""Staff (Hakeem / admin): find patients and see their complete history."""
from django.contrib.auth import get_user_model
from django.db.models import Count, Q
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
from .views import profile_of

User = get_user_model()


class PatientRowOut(serializers.Serializer):
    id = serializers.IntegerField()
    phone = serializers.CharField(allow_null=True)
    email = serializers.CharField(allow_blank=True)
    full_name = serializers.CharField()
    created_at = serializers.DateTimeField()
    last_login = serializers.DateTimeField(allow_null=True)
    consultations = serializers.IntegerField()
    pulse_analyses = serializers.IntegerField()
    is_active = serializers.BooleanField()


class PatientListView(generics.ListAPIView):
    """All patients (search by phone, name or e-mail), newest first."""
    permission_classes = [HasAppKey, IsStaff]
    serializer_class = PatientRowOut

    @extend_schema(parameters=[OpenApiParameter("search", str, description="part of the phone number, name or e-mail")])
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    def get_queryset(self):
        q = PatientProfile.objects.select_related("user").annotate(
            n_consultations=Count("user__consultations", distinct=True),
            n_pulse=Count("user__pulse_analyses", distinct=True)).order_by("-created_at", "-pk")
        term = (self.request.query_params.get("search") or "").strip()
        if term:
            q = q.filter(Q(phone__icontains=term) | Q(full_name__icontains=term) | Q(user__email__icontains=term))
        return q

    def list(self, request, *args, **kwargs):
        page = self.paginate_queryset(self.get_queryset())
        audit(request, "staff.patients.list", "", None, search=bool(request.query_params.get("search")))
        return self.get_paginated_response([
            {"id": p.user_id, "phone": p.phone or None, "email": p.user.email or "", "full_name": p.full_name,
             "created_at": p.created_at,
             "last_login": p.user.last_login, "consultations": p.n_consultations, "pulse_analyses": p.n_pulse,
             "is_active": p.user.is_active} for p in page])


class PatientHistoryView(APIView):
    """One patient's complete history: profile, every consultation (hidden ones too) and pulse analysis."""
    permission_classes = [HasAppKey, IsStaff]

    @extend_schema(responses={200: dict, 404: ErrorOut})
    def get(self, request, pk):
        user = User.objects.filter(pk=pk).first()
        if user is None:
            return Response({"error": "not_found", "detail": "no such user"}, status=404)
        consultations = list(Consultation.objects.filter(patient=user))
        pulses = PulseAnalysis.objects.filter(patient=user)
        audit(request, "staff.patient.view", "user", user.pk)
        return Response({
            "profile": {**profile_of(user), "is_active": user.is_active, "last_login": user.last_login,
                        "role": role_of(user)},
            "consultations": summaries(consultations),
            "pulse_analyses": [{"id": str(p.id), "status": p.status, "method": p.method, "created_at": p.created_at,
                                "consultation": str(p.consultation_id) if p.consultation_id else None,
                                "average_heart_rate_bpm": (p.result or {}).get("average_heart_rate_bpm"),
                                "deleted": p.deleted_at is not None} for p in pulses],
        })
