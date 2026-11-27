import json
import os

from django.conf import settings
from rest_framework import serializers

from .service import ALLOWED_EXTENSIONS


class PulseUploadIn(serializers.Serializer):
    video = serializers.FileField(help_text="Finger-on-lens (or wrist) video, 30–60 s; mp4, mov, 3gp, webm, mkv")
    method = serializers.ChoiceField(choices=["finger", "wrist"], default="finger")
    consultation = serializers.UUIDField(required=False, allow_null=True,
                                         help_text="Link to one of your consultations (optional)")
    symptoms = serializers.CharField(required=False, allow_blank=True, max_length=4000,
                                     help_text='Optional free-text symptoms: JSON list ["…", "…"] or comma separated')

    def validate_video(self, f):
        ext = os.path.splitext(f.name or "")[1].lower()
        if ext not in ALLOWED_EXTENSIONS:
            raise serializers.ValidationError(f"unsupported file type {ext or '(none)'}; allowed: "
                                              f"{', '.join(sorted(ALLOWED_EXTENSIONS))}")
        if f.size > settings.NAZRIA_PULSE_MAX_MB * 1024 * 1024:
            raise serializers.ValidationError(f"the video is larger than {settings.NAZRIA_PULSE_MAX_MB} MB")
        return f

    def validate_symptoms(self, value):
        if not value:
            return []
        try:
            items = json.loads(value)
        except json.JSONDecodeError:
            items = value.split(",")
        if not isinstance(items, list):
            raise serializers.ValidationError("a JSON list or comma-separated text")
        return [str(s).strip()[:200] for s in items if str(s).strip()][:50]


class PulseAnalysisOut(serializers.Serializer):
    id = serializers.UUIDField()
    patient = serializers.IntegerField(source="patient_id")
    consultation = serializers.UUIDField(source="consultation_id", allow_null=True)
    method = serializers.CharField()
    status = serializers.ChoiceField(choices=["processing", "completed", "failed"])
    result = serializers.DictField(help_text="Heart rate, HRV, pulse characteristics, waveform, signal quality "
                                             "(see docs/API.md); empty when the analysis failed")
    error = serializers.CharField(allow_blank=True)
    symptoms = serializers.ListField(child=serializers.CharField())
    created_at = serializers.DateTimeField()
    processed_at = serializers.DateTimeField(allow_null=True)
    disclaimer = serializers.CharField(default="")
