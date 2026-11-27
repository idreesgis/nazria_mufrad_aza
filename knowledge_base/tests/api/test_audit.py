"""Complete activity log: every API request, never secret, never changeable."""
import json

import pytest

from audit.models import AuditEvent

from .conftest import REFERENCE

pytestmark = pytest.mark.django_db


def test_every_request_is_logged_with_actor_action_and_result(anon, api, patient_user):
    anon.post("/api/v1/auth/login/", {"phone": "03001234567", "password": "wrong-pass"}, format="json")
    anon.post("/api/v1/auth/login/", {"phone": "03001234567", "password": "sabz-chai-2026"}, format="json")
    r = api.post("/api/v1/consultations/", {"answers": REFERENCE, "patient_id": str(api.patient.id)}, format="json")
    api.get(f"/api/v1/consultations/{r.data['id']}/")
    events = list(AuditEvent.objects.order_by("id"))
    actions = [e.action for e in events]
    assert actions == ["auth.login_failed", "auth.login", "consultation.create", "consultation.view"]
    failed, ok, created, viewed = events
    assert failed.actor is None and failed.details == {"phone": "+923001234567"} and failed.status_code == 401
    assert ok.actor == patient_user and ok.status_code == 200 and ok.api_client.name == "android-test"
    assert created.actor == patient_user and created.actor_type == "patient" and created.object_id == r.data["id"]
    assert created.details == {"status": "completed", "primary_system": "عضلاتی",
                               "patient": str(api.patient.id)} and created.ip == "127.0.0.1"
    dump = json.dumps(list(AuditEvent.objects.values()), default=str, ensure_ascii=False)
    for secret in ("sabz-chai-2026", "wrong-pass", "قبض", "Bearer"):           # no passwords, tokens or symptoms
        assert secret not in dump


def test_responses_carry_the_request_id(api):
    r = api.get("/api/v1/consultations/")
    assert str(AuditEvent.objects.get().request_id) == r["X-Request-ID"]


def test_audit_events_cannot_be_changed_or_deleted(api):
    api.get("/api/v1/me/")
    e = AuditEvent.objects.get()
    e.action = "tampered"
    with pytest.raises(PermissionError):
        e.save()
    with pytest.raises(PermissionError):
        e.delete()


def test_patient_sees_own_activity_staff_sees_everything(api, hakeem):
    api.get("/api/v1/me/")
    hakeem.get("/api/v1/me/")
    mine = api.get("/api/v1/me/activity/").data
    assert mine["count"] >= 1 and {e["actor"] for e in mine["results"]} == {api.user.pk}
    assert api.get("/api/v1/staff/audit/").status_code == 403
    full = hakeem.get("/api/v1/staff/audit/", {"user": api.user.pk}).data
    assert full["count"] >= 1 and all(e["actor"] == api.user.pk for e in full["results"])
    assert hakeem.get("/api/v1/staff/audit/", {"action": "api."}).data["count"] >= 1


def test_admin_requests_are_logged(client, hakeem):
    from django.contrib.auth import get_user_model
    admin = get_user_model().objects.create_superuser("+923000000000", password="admin-pass-2026")
    client.force_login(admin)
    assert client.get("/admin/audit/auditevent/").status_code == 200
    e = AuditEvent.objects.filter(path="/admin/audit/auditevent/").get()
    assert e.actor == admin and e.actor_type == "admin"
