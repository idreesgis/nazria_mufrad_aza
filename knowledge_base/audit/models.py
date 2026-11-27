"""Append-only log of every API and admin request: who, what, when, from where, and the result.

Never stored here: passwords, tokens, request bodies, symptom text. Rows cannot be changed or deleted through
Django, and on PostgreSQL a trigger refuses UPDATE / DELETE as well (migration 0002)."""
from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone


class AuditEvent(models.Model):
    ACTOR_TYPES = [("patient", "patient"), ("hakeem", "hakeem"), ("admin", "admin"), ("anonymous", "anonymous")]
    id = models.BigAutoField(primary_key=True)
    at = models.DateTimeField(default=timezone.now, db_index=True)
    request_id = models.UUIDField(db_index=True)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                              related_name="audit_events")
    actor_type = models.CharField(max_length=10, choices=ACTOR_TYPES)
    api_client = models.ForeignKey("consultations.ApiClient", null=True, blank=True, on_delete=models.PROTECT)
    action = models.CharField(max_length=60, db_index=True, help_text="e.g. consultation.create, auth.login_failed")
    object_type = models.CharField(max_length=30, blank=True)
    object_id = models.CharField(max_length=64, blank=True, db_index=True)
    method = models.CharField(max_length=8)
    path = models.CharField(max_length=255)
    status_code = models.PositiveSmallIntegerField()
    duration_ms = models.PositiveIntegerField()
    ip = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=255, blank=True)
    details = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-at", "-id"]
        indexes = [models.Index(fields=["actor", "at"]), models.Index(fields=["object_type", "object_id"])]

    def __str__(self) -> str:
        return f"{self.at:%Y-%m-%d %H:%M:%S} {self.action} {self.status_code}"

    def save(self, *args, **kwargs):
        if self.pk is not None and AuditEvent.objects.filter(pk=self.pk).exists():
            raise PermissionError("audit events cannot be changed")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PermissionError("audit events cannot be deleted")
