"""Runs the PPG analysis on an uploaded video and stores the result (or a safe error message)."""
from __future__ import annotations

import logging

from django.utils import timezone

from .models import PulseAnalysis
from .ppg_service import analyze_pulse_video

log = logging.getLogger("pulse")
ALLOWED_EXTENSIONS = {".mp4", ".mov", ".3gp", ".webm", ".mkv", ".m4v", ".avi"}
DISCLAIMER = ("Pulse analysis from a phone camera is experimental and only supports a Hakeem's examination; "
              "it is not a diagnosis. نبض کا یہ تجزیہ تجرباتی ہے، تشخیص نہیں۔")
# messages of the analyser that are safe to show (they never contain a file path)
_KNOWN = {
    "Insufficient frames extracted": "the video is too short or the finger was not detected",
    "No signal to filter": "no pulse signal was found in the video",
    "Insufficient heartbeats detected": "too few heartbeats were detected; keep the finger still on the lens",
    "Could not open video": "the video file could not be read",
}


def run_analysis(a: PulseAnalysis) -> PulseAnalysis:
    try:
        a.result = analyze_pulse_video(a.video.path, method=a.method)
        a.status, a.error = "completed", ""
    except Exception as e:                                    # noqa: BLE001 - any failure is stored, never raised
        msg = str(e)
        a.status = "failed"
        a.error = next((v for k, v in _KNOWN.items() if msg.startswith(k)), "the video could not be analysed")
        log.warning("pulse analysis %s failed: %s", a.id, type(e).__name__)
    a.processed_at = timezone.now()
    a.save(update_fields=["result", "status", "error", "processed_at"])
    return a
