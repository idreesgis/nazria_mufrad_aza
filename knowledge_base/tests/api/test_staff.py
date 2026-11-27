"""Hakeem / admin: accounts, patients and their complete history."""
import pytest

from .conftest import REFERENCE, make_patient

pytestmark = pytest.mark.django_db


def test_staff_find_accounts_and_patients_and_see_complete_history(api, hakeem):
    r = api.post("/api/v1/consultations/", {"answers": REFERENCE, "patient_id": str(api.patient.id)}, format="json")
    api.delete(f"/api/v1/consultations/{r.data['id']}/")
    api.post("/api/v1/consultations/", {"answers": {"red_flags": ["breathing"]}}, format="json")
    child = make_patient(api.user, "Bachcha", relation="child", birth_year=2020)
    accounts = hakeem.get("/api/v1/staff/accounts/", {"search": "300123"}).data
    assert accounts["count"] == 1 and accounts["results"][0]["consultations"] == 2
    assert accounts["results"][0]["patients"] == 2
    h = hakeem.get(f"/api/v1/staff/accounts/{api.user.pk}/").data
    assert h["profile"]["phone"] == "+923001234567" and len(h["consultations"]) == 2 and len(h["patients"]) == 2
    assert sorted(c["deleted"] for c in h["consultations"]) == [False, True]       # hidden ones included
    assert {c["status"] for c in h["consultations"]} == {"completed", "emergency"}

    rows = hakeem.get("/api/v1/staff/patients/", {"search": "Bachcha"}).data
    assert rows["count"] == 1 and rows["results"][0]["account_phone"] == "+923001234567"
    ph = hakeem.get(f"/api/v1/staff/patients/{api.patient.id}/").data
    assert ph["patient"]["full_name"] == "Test Patient" and len(ph["consultations"]) == 1
    assert ph["consultations"][0]["deleted"] is True and ph["revisions"][0]["action"] == "created"
    assert hakeem.get(f"/api/v1/staff/patients/{child.id}/").data["consultations"] == []


def test_patients_cannot_use_staff_endpoints(api):
    for url in ("/api/v1/staff/accounts/", f"/api/v1/staff/accounts/{api.user.pk}/", "/api/v1/staff/patients/",
                f"/api/v1/staff/patients/{api.patient.id}/", "/api/v1/staff/audit/"):
        assert api.get(url).status_code == 403
