"""Django-side records. The consultation content (answers, result, transcript) stays in the knowledge-base tables
nazria.consultation_sessions / consultation_messages; these models only hold API access data."""
from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone

KEY_PREFIX = "nzr_"


def _hash(secret: str) -> str:
    # the secrets are random 256-bit values, so a fast hash is sufficient (no password stretching needed)
    return hashlib.sha256(secret.encode()).hexdigest()


class ApiClient(models.Model):
    """An app (or app version) allowed to call the API. The key is shown once on creation and stored hashed."""
    name = models.CharField(max_length=100, unique=True)
    key_prefix = models.CharField(max_length=16, unique=True, editable=False)
    key_hash = models.CharField(max_length=64, editable=False)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    last_used_at = models.DateTimeField(null=True, blank=True, editable=False)
    notes = models.TextField(blank=True)

    class Meta:
        verbose_name = "API client"
        ordering = ["name"]

    def __str__(self) -> str:
        return f"{self.name} ({KEY_PREFIX}{self.key_prefix}…)"

    @classmethod
    def create(cls, name: str, notes: str = "") -> tuple["ApiClient", str]:
        """New client and its plain key (``nzr_<prefix>_<secret>``); only the hash is stored."""
        prefix = secrets.token_hex(6)
        key = f"{KEY_PREFIX}{prefix}_{secrets.token_urlsafe(32)}"
        return cls.objects.create(name=name, notes=notes, key_prefix=prefix, key_hash=_hash(key)), key

    @classmethod
    def authenticate(cls, key: str) -> "ApiClient | None":
        if not key.startswith(KEY_PREFIX) or key.count("_") < 2:
            return None
        prefix = key[len(KEY_PREFIX):].split("_", 1)[0]
        client = cls.objects.filter(key_prefix=prefix, is_active=True).first()
        if client is None or not hmac.compare_digest(client.key_hash, _hash(key)):
            return None
        now = timezone.now()
        if client.last_used_at is None or (now - client.last_used_at).total_seconds() > 300:
            cls.objects.filter(pk=client.pk).update(last_used_at=now)
        return client


class Consultation(models.Model):
    """One diagnosis of a patient: the account that ran it, the patient it was for (and their general info at the
    time), status and a few summary fields. The full content (answers, result, transcript, AI explanation) is in
    nazria.consultation_sessions / consultation_messages. Kept permanently; "delete" only hides it (deleted_at)."""
    session_uid = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    account = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT,
                                related_name="consultations")
    patient = models.ForeignKey("patients.Patient", null=True, on_delete=models.PROTECT,
                                related_name="consultations")
    patient_snapshot = models.JSONField(default=dict, blank=True,
                                        help_text="the patient's general info when this diagnosis was made")
    rediagnosis_of = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT,
                                       related_name="rediagnoses")
    client = models.ForeignKey(ApiClient, null=True, on_delete=models.SET_NULL, related_name="consultations")
    status = models.CharField(max_length=20)                     # completed | emergency
    primary_system = models.CharField(max_length=20, blank=True)
    explanation_status = models.CharField(max_length=40, blank=True)
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    deleted_at = models.DateTimeField(null=True, blank=True)
    deleted_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                   related_name="+")

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["created_at"]),
                   models.Index(fields=["account", "created_at"], name="consultatio_account_idx"),
                   models.Index(fields=["patient", "created_at"], name="consultation_patient_idx")]

    def __str__(self) -> str:
        return f"{self.session_uid} {self.status}"
