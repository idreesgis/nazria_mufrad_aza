"""Hakeem / admin: patients and their complete history."""
import pytest

from .conftest import REFERENCE

pytestmark = pytest.mark.django_db


def test_staff_find_patients_and_see_complete_history(api, hakeem):
    r = api.post("/api/v1/consultations/", {"answers": REFERENCE}, format="json")
    api.delete(f"/api/v1/consultations/{r.data['id']}/")
    api.post("/api/v1/consultations/", {"answers": {"red_flags": ["breathing"]}}, format="json")
    patients = hakeem.get("/api/v1/staff/patients/", {"search": "300123"}).data
    assert patients["count"] == 1 and patients["results"][0]["consultations"] == 2
    h = hakeem.get(f"/api/v1/staff/patients/{api.user.pk}/").data
    assert h["profile"]["phone"] == "+923001234567" and len(h["consultations"]) == 2
    assert sorted(c["deleted"] for c in h["consultations"]) == [False, True]       # hidden ones included
    assert {c["status"] for c in h["consultations"]} == {"completed", "emergency"}


def test_patients_cannot_use_staff_endpoints(api):
    for url in ("/api/v1/staff/patients/", f"/api/v1/staff/patients/{api.user.pk}/", "/api/v1/staff/audit/"):
        assert api.get(url).status_code == 403
