"""Pulse video upload and analysis (the former pulse_diagnosis project, now part of the API)."""
import io

import numpy as np
import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from audit.models import AuditEvent
from pulse.models import PulseAnalysis

from .conftest import REFERENCE

pytestmark = pytest.mark.django_db


def finger_video(tmp_path, bpm=72, seconds=20, fps=30) -> bytes:
    """A synthetic finger-on-lens video whose red channel pulses at ``bpm``."""
    import cv2
    path = str(tmp_path / "finger.mp4")
    w = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"mp4v"), fps, (160, 120))
    rng = np.random.default_rng(1)
    for i in range(fps * seconds):
        t = i / fps
        v = 150 + 12 * np.sin(2 * np.pi * bpm / 60 * t) + 4 * np.sin(4 * np.pi * bpm / 60 * t) + rng.normal(0, 1)
        f = np.zeros((120, 160, 3), np.uint8)
        f[:, :, 2], f[:, :, 1], f[:, :, 0] = np.clip(v, 0, 255), 20, 15
        w.write(f)
    w.release()
    return open(path, "rb").read()


def upload(api, data: bytes, name="pulse.mp4", **fields):
    return api.post("/api/v1/pulse/analyses/", {"video": SimpleUploadedFile(name, data, "video/mp4"), **fields},
                    format="multipart")


def test_finger_video_is_analysed_and_kept_in_history(api, tmp_path, settings):
    r = upload(api, finger_video(tmp_path), symptoms='["Headaches", "Insomnia"]')
    assert r.status_code == 201, r.data
    assert r.data["status"] == "completed" and 66 <= r.data["result"]["average_heart_rate_bpm"] <= 80
    assert r.data["symptoms"] == ["Headaches", "Insomnia"] and "experimental" in r.data["disclaimer"]
    a = PulseAnalysis.objects.get(pk=r.data["id"])
    assert a.patient == api.user and a.video.name.startswith("pulse/") and "pulse.mp4" not in a.video.name
    assert api.get("/api/v1/pulse/analyses/").data["count"] == 1
    assert api.get(f"/api/v1/pulse/analyses/{a.id}/").data["result"] == r.data["result"]
    assert AuditEvent.objects.filter(action="pulse.upload", object_id=str(a.id)).exists()


def test_unreadable_video_fails_with_a_safe_message(api):
    r = upload(api, b"not a video at all")
    assert r.status_code == 201 and r.data["status"] == "failed" and r.data["result"] == {}
    assert r.data["error"] == "the video file could not be read" and "/" not in r.data["error"]


@pytest.mark.parametrize("name,size_mb,expected", [("pulse.exe", 0, "unsupported file type"),
                                                   ("pulse.mp4", 3, "larger than")])
def test_upload_validation(api, settings, name, size_mb, expected):
    settings.NAZRIA_PULSE_MAX_MB = 2
    r = upload(api, b"x" * (size_mb * 1024 * 1024 + 10), name=name)
    assert r.status_code == 400 and expected in r.data["fields"]["video"]


def test_link_to_own_consultation_only(api, app_key, tmp_path):
    c = api.post("/api/v1/consultations/", {"answers": REFERENCE}, format="json").data
    r = upload(api, finger_video(tmp_path, seconds=12), consultation=c["id"])
    assert r.status_code == 201 and r.data["consultation"] == c["id"]
    detail = api.get(f"/api/v1/consultations/{c['id']}/").data
    assert detail["pulse_analyses"][0]["id"] == r.data["id"]
    from .conftest import logged_in, make_user
    other = logged_in(app_key, make_user("+923009999999"))
    bad = upload(other, b"x", consultation=c["id"])
    assert bad.status_code == 400 and "consultation" in bad.data["fields"]
    assert other.get(f"/api/v1/pulse/analyses/{r.data['id']}/").status_code == 404


def test_delete_hides_but_keeps_the_video(api, hakeem, tmp_path):
    r = upload(api, finger_video(tmp_path, seconds=12))
    assert api.delete(f"/api/v1/pulse/analyses/{r.data['id']}/").status_code == 204
    assert api.get(f"/api/v1/pulse/analyses/{r.data['id']}/").status_code == 404
    a = PulseAnalysis.objects.get(pk=r.data["id"])
    assert a.deleted_at and a.video.storage.exists(a.video.name)
    assert hakeem.get(f"/api/v1/pulse/analyses/{a.id}/").status_code == 200


def test_symptom_suggestions(api):
    assert "digestive" in api.get("/api/v1/pulse/symptom-suggestions/").data["symptom_categories"]
