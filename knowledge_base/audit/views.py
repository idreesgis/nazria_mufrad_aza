"""Activity log: a patient's own events, and the full log for staff (filter by user, action, object, date)."""
from django.utils.dateparse import parse_datetime
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import generics

from accounts.permissions import HasAppKey, IsStaff

from .models import AuditEvent
from .serializers import AuditEventOut


class MyActivityView(generics.ListAPIView):
    """Everything this account did (logins, consultations, pulse uploads …), newest first."""
    serializer_class = AuditEventOut

    def get_queryset(self):
        return AuditEvent.objects.filter(actor=self.request.user).select_related("actor")


class StaffAuditView(generics.ListAPIView):
    """The complete audit log (staff only)."""
    serializer_class = AuditEventOut
    permission_classes = [HasAppKey, IsStaff]

    @extend_schema(parameters=[
        OpenApiParameter("user", int, description="actor user id"),
        OpenApiParameter("action", str, description="exact action, or a prefix ending in '.' (e.g. auth.)"),
        OpenApiParameter("object_id", str), OpenApiParameter("since", str, description="ISO date-time"),
        OpenApiParameter("until", str, description="ISO date-time")])
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    def get_queryset(self):
        q = AuditEvent.objects.select_related("actor")
        p = self.request.query_params
        if p.get("user"):
            q = q.filter(actor_id=p["user"])
        if p.get("action"):
            q = q.filter(action__startswith=p["action"]) if p["action"].endswith(".") else q.filter(action=p["action"])
        if p.get("object_id"):
            q = q.filter(object_id=p["object_id"])
        for key, lookup in (("since", "at__gte"), ("until", "at__lte")):
            if p.get(key) and parse_datetime(p[key]):
                q = q.filter(**{lookup: parse_datetime(p[key])})
        return q
