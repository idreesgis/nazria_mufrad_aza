"""Pulse (نبض) videos and their PPG analysis, for one patient of the account that uploaded them (kept permanently)."""
from __future__ import annotations

import os
import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone


def video_path(instance: "PulseAnalysis", filename: str) -> str:
    # a random file name: the original name may contain personal details
    ext = os.path.splitext(filename)[1].lower()[:6]
    return f"pulse/{timezone.now():%Y/%m}/{instance.id}{ext}"


class PulseAnalysis(models.Model):
    METHODS = [("finger", "finger on the camera lens"), ("wrist", "traditional wrist nabz, four fingers")]
    STATUSES = [("processing", "processing"), ("completed", "completed"), ("failed", "failed")]
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    account = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="pulse_analyses")
    patient = models.ForeignKey("patients.Patient", null=True, on_delete=models.PROTECT, related_name="pulse_analyses")
    consultation = models.ForeignKey("consultations.Consultation", null=True, blank=True, on_delete=models.PROTECT,
                                     related_name="pulse_analyses")
    method = models.CharField(max_length=10, choices=METHODS, default="finger")
    video = models.FileField(upload_to=video_path, max_length=200)
    video_size = models.PositiveBigIntegerField(default=0)
    symptoms = models.JSONField(default=list, blank=True)
    status = models.CharField(max_length=12, choices=STATUSES, default="processing")
    result = models.JSONField(default=dict, blank=True)
    error = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(default=timezone.now, editable=False, db_index=True)
    processed_at = models.DateTimeField(null=True, blank=True)
    deleted_at = models.DateTimeField(null=True, blank=True, help_text="hidden from the patient; kept for history")

    class Meta:
        ordering = ["-created_at"]
        verbose_name_plural = "pulse analyses"

    def __str__(self) -> str:
        return f"{self.id} {self.status}"
