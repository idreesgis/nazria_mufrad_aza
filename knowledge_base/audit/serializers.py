from rest_framework import serializers

from .models import AuditEvent


class AuditEventOut(serializers.ModelSerializer):
    actor_phone = serializers.CharField(source="actor.username", default=None)

    class Meta:
        model = AuditEvent
        fields = ["id", "at", "request_id", "actor", "actor_phone", "actor_type", "action", "object_type", "object_id",
                  "method", "path", "status_code", "duration_ms", "ip", "user_agent", "details"]
