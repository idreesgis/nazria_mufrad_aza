"""Patient registration and login with phone + password (JWT)."""
import pytest
from rest_framework.test import APIClient

from accounts.models import PatientProfile
from accounts.phone import normalize_phone

pytestmark = pytest.mark.django_db
NEW = {"phone": "0300-7654321", "password": "neem-ka-patta-9", "full_name": "احمد", "gender": "male",
       "birth_year": 1980, "consent": True}


@pytest.mark.parametrize("raw", ["03001234567", "0300-1234567", "+92 300 1234567", "00923001234567",
                                 "923001234567", "3001234567", "۰۳۰۰۱۲۳۴۵۶۷"])
def test_phone_numbers_have_one_canonical_form(raw, settings):
    assert normalize_phone(raw) == "+923001234567"


@pytest.mark.parametrize("raw", ["", "abc", "123", "+92-300-12345678901234"])
def test_invalid_phone_numbers(raw, settings):
    with pytest.raises(ValueError):
        normalize_phone(raw)


def test_register_login_refresh_logout(anon, app_key):
    r = anon.post("/api/v1/auth/register/", NEW, format="json")
    assert r.status_code == 201, r.data
    assert r.data["user"]["phone"] == "+923007654321" and r.data["user"]["role"] == "patient"
    p = PatientProfile.objects.get(phone="+923007654321")
    assert p.consent_at and p.consent_version and p.full_name == "احمد" and p.user.check_password(NEW["password"])
    # log in with another spelling of the same number
    r = anon.post("/api/v1/auth/login/", {"phone": "+92 300 7654321", "password": NEW["password"]}, format="json")
    assert r.status_code == 200
    access, refresh = r.data["access"], r.data["refresh"]
    me = APIClient()
    me.credentials(HTTP_X_API_KEY=app_key, HTTP_AUTHORIZATION=f"Bearer {access}")
    assert me.get("/api/v1/me/").data["full_name"] == "احمد"
    # refresh rotates: the old refresh token stops working
    r2 = anon.post("/api/v1/auth/refresh/", {"refresh": refresh}, format="json")
    assert r2.status_code == 200 and r2.data["refresh"] != refresh
    assert anon.post("/api/v1/auth/refresh/", {"refresh": refresh}, format="json").status_code == 401
    # logout invalidates the current refresh token
    assert me.post("/api/v1/auth/logout/", {"refresh": r2.data["refresh"]}, format="json").status_code == 204
    assert anon.post("/api/v1/auth/refresh/", {"refresh": r2.data["refresh"]}, format="json").status_code == 401


@pytest.mark.parametrize("change,field", [
    ({"consent": False}, "consent"), ({"password": "12345678"}, "password"), ({"phone": "12"}, "phone"),
    ({"password": "short"}, "password"),
])
def test_register_validation(anon, change, field):
    r = anon.post("/api/v1/auth/register/", {**NEW, **change}, format="json")
    assert r.status_code == 400 and field in r.data["fields"]


def test_one_account_per_phone(anon, patient_user):
    r = anon.post("/api/v1/auth/register/", {**NEW, "phone": "0300 1234567"}, format="json")
    assert r.status_code == 400 and "already exists" in r.data["fields"]["phone"]


def test_wrong_password_is_rejected_without_saying_why(anon, patient_user):
    for body in ({"phone": "03001234567", "password": "wrong-password"}, {"phone": "03110000000", "password": "x"}):
        r = anon.post("/api/v1/auth/login/", body, format="json")
        assert r.status_code == 401 and r.data == {"error": "invalid_credentials",
                                                   "detail": "phone number or password is wrong"}


def test_profile_update_and_password_change(api):
    r = api.patch("/api/v1/me/", {"full_name": "نیا نام", "birth_year": 1975}, format="json")
    assert r.status_code == 200 and r.data["full_name"] == "نیا نام" and r.data["birth_year"] == 1975
    bad = api.post("/api/v1/me/password/", {"old_password": "wrong", "new_password": "naya-password-1"}, format="json")
    assert bad.status_code == 400
    ok = api.post("/api/v1/me/password/", {"old_password": "sabz-chai-2026", "new_password": "naya-password-1"},
                  format="json")
    assert ok.status_code == 204
    api.user.refresh_from_db()
    assert api.user.check_password("naya-password-1")


def test_login_attempts_are_rate_limited(anon, monkeypatch):
    from accounts.throttles import AuthRateThrottle
    monkeypatch.setattr(AuthRateThrottle, "rate", "3/min", raising=False)
    codes = [anon.post("/api/v1/auth/login/", {"phone": "03001234567", "password": "x"}, format="json").status_code
             for _ in range(4)]
    assert codes == [401, 401, 401, 429]


def test_create_staff_command(monkeypatch, app_key):
    from django.core.management import call_command

    from accounts.models import role_of
    monkeypatch.setenv("STAFF_PW", "hakeem-sahib-2026")
    call_command("create_staff", phone="0333-1112223", name="Hakeem", password_env="STAFF_PW")
    anon = APIClient()
    anon.credentials(HTTP_X_API_KEY=app_key)
    r = anon.post("/api/v1/auth/login/", {"phone": "03331112223", "password": "hakeem-sahib-2026"}, format="json")
    assert r.status_code == 200 and r.data["user"]["role"] == "hakeem"
    from django.contrib.auth import get_user_model
    assert role_of(get_user_model().objects.get(username="+923331112223")) == "hakeem"
