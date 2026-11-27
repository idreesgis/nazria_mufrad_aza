"""Sign in with Google: ID-token verification is replaced by a fake; the real verifier is checked with a
locally signed token (no network)."""
import pytest

from accounts import google
from accounts.google import GoogleIdentity, GoogleTokenInvalid, GoogleUnavailable
from accounts.models import PatientProfile, SocialAccount
from audit.models import AuditEvent

from .conftest import logged_in, make_user

CLIENT_ID = "1234-web.apps.googleusercontent.com"
TOKENS = {
    "tok-amina": GoogleIdentity("1001", "amina@gmail.com", True, "Amina Bibi"),
    "tok-other": GoogleIdentity("2002", "other@gmail.com", True, "Other"),
    "tok-unverified": GoogleIdentity("3003", "x@example.com", False, "X"),
}


def fake_verify(token):
    if token == "tok-down":
        raise GoogleUnavailable()
    if token not in TOKENS:
        raise GoogleTokenInvalid()
    return TOKENS[token]


@pytest.fixture(autouse=True)
def google_on(settings):
    settings.NAZRIA_GOOGLE_CLIENT_IDS = [CLIENT_ID]
    google.set_verifier(fake_verify)
    yield
    google.set_verifier(None)


def g(anon, token="tok-amina", **extra):
    return anon.post("/api/v1/auth/google/", {"id_token": token, **extra}, format="json")


def actions():
    return list(AuditEvent.objects.order_by("id").values_list("action", flat=True))


def test_new_account_needs_consent_then_is_created(anon):
    r = g(anon)
    assert r.status_code == 400 and r.json()["error"] == "consent_required"
    assert not SocialAccount.objects.exists()

    r = g(anon, consent=True, gender="female", birth_year=1990)
    assert r.status_code == 201, r.content
    body = r.json()
    assert body["created"] is True and body["access"] and body["refresh"]
    u = body["user"]
    assert u["phone"] is None and u["email"] == "amina@gmail.com" and u["full_name"] == "Amina Bibi"
    assert u["role"] == "patient" and u["has_password"] is False and u["linked_providers"] == ["google"]
    assert u["consent_at"] and u["gender"] == "female"
    assert "auth.google_register" in actions()


def test_second_sign_in_logs_in_without_consent(anon):
    g(anon, consent=True)
    r = g(anon)
    assert r.status_code == 200 and r.json()["created"] is False
    assert SocialAccount.objects.count() == 1 and PatientProfile.objects.count() == 1
    assert SocialAccount.objects.get().last_login_at is not None
    assert actions().count("auth.google_login") == 1


def test_tokens_work_and_refresh(anon):
    tokens = g(anon, consent=True).json()
    c = anon
    c.credentials(HTTP_X_API_KEY=anon._credentials["HTTP_X_API_KEY"], HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")
    assert c.get("/api/v1/me/").json()["email"] == "amina@gmail.com"
    r = c.post("/api/v1/auth/refresh/", {"refresh": tokens["refresh"]}, format="json")
    assert r.status_code == 200


@pytest.mark.parametrize("token,http,code", [("bad", 401, "invalid_google_token"),
                                             ("tok-down", 503, "google_unavailable"),
                                             ("tok-unverified", 400, "google_email_unverified")])
def test_rejected_tokens(anon, token, http, code):
    r = g(anon, token, consent=True)
    assert r.status_code == http and r.json()["error"] == code
    assert not SocialAccount.objects.exists()


def test_disabled_without_client_id(anon, settings):
    settings.NAZRIA_GOOGLE_CLIENT_IDS = []
    r = g(anon, consent=True)
    assert r.status_code == 503 and r.json()["error"] == "google_login_disabled"
    assert anon.get("/api/v1/health/").json()["google_login_enabled"] is False


def test_health_reports_google(anon):
    assert anon.get("/api/v1/health/").json()["google_login_enabled"] is True


def test_needs_app_key(client):
    r = client.post("/api/v1/auth/google/", {"id_token": "tok-amina", "consent": True}, content_type="application/json")
    assert r.status_code == 403 and r.json()["error"] == "app_key_invalid"


def test_token_never_logged(anon):
    g(anon, consent=True)
    for e in AuditEvent.objects.all():
        assert "tok-amina" not in str(e.details)


def test_inactive_user_refused(anon):
    uid = g(anon, consent=True).json()["user"]["id"]
    from django.contrib.auth import get_user_model
    get_user_model().objects.filter(pk=uid).update(is_active=False)
    r = g(anon)
    assert r.status_code == 403 and r.json()["error"] == "account_disabled"


# ------------------------------------------------------------------- linking an existing phone account
def test_phone_patient_links_google_then_signs_in_with_it(app_key, anon, patient_user):
    api = logged_in(app_key, patient_user)
    r = api.post("/api/v1/me/google/", {"id_token": "tok-amina"}, format="json")
    assert r.status_code == 200 and r.json()["linked_providers"] == ["google"]
    assert r.json()["email"] == "amina@gmail.com"
    r = g(anon)                                     # no consent needed: the account exists
    assert r.status_code == 200 and r.json()["user"]["id"] == patient_user.pk
    assert r.json()["user"]["phone"] == "+923001234567"


def test_link_conflicts(app_key, anon, patient_user):
    g(anon, "tok-other", consent=True)              # tok-other already has its own account
    api = logged_in(app_key, patient_user)
    r = api.post("/api/v1/me/google/", {"id_token": "tok-other"}, format="json")
    assert r.status_code == 409 and r.json()["error"] == "google_already_linked"
    assert api.post("/api/v1/me/google/", {"id_token": "tok-amina"}, format="json").status_code == 200
    r = api.post("/api/v1/me/google/", {"id_token": "tok-amina"}, format="json")       # idempotent
    assert r.status_code == 200 and SocialAccount.objects.filter(user=patient_user).count() == 1


def test_unlink_only_with_another_login_method(app_key, anon, patient_user):
    api = logged_in(app_key, patient_user)
    api.post("/api/v1/me/google/", {"id_token": "tok-amina"}, format="json")
    r = api.delete("/api/v1/me/google/")
    assert r.status_code == 200 and r.json()["linked_providers"] == []
    assert api.delete("/api/v1/me/google/").status_code == 404

    from django.contrib.auth import get_user_model
    gid = g(anon, "tok-other", consent=True).json()["user"]["id"]
    gapi = logged_in(app_key, get_user_model().objects.get(pk=gid))
    r = gapi.delete("/api/v1/me/google/")
    assert r.status_code == 409 and r.json()["error"] == "last_login_method"
    assert "auth.google_unlink" in actions()


def test_staff_cannot_use_google(app_key, anon):
    staff = make_user("+923331112223", name="Hakeem", staff=True)
    r = logged_in(app_key, staff).post("/api/v1/me/google/", {"id_token": "tok-amina"}, format="json")
    assert r.status_code == 403 and r.json()["error"] == "staff_password_only"
    SocialAccount.objects.create(user=staff, provider="google", uid="1001", email_verified=True)
    r = g(anon)
    assert r.status_code == 403 and r.json()["error"] == "staff_password_only"


# ------------------------------------------------------------------- a Google account adds phone + password
def test_google_account_adds_phone_and_password_then_phone_login(app_key, anon):
    from django.contrib.auth import get_user_model
    gid = g(anon, consent=True).json()["user"]["id"]
    api = logged_in(app_key, get_user_model().objects.get(pk=gid))
    r = api.patch("/api/v1/me/", {"phone": "0301-7654321"}, format="json")
    assert r.status_code == 200 and r.json()["phone"] == "+923017654321"
    r = api.patch("/api/v1/me/", {"phone": "0301-0000000"}, format="json")
    assert r.status_code == 400                                    # set once; staff change it later
    assert api.post("/api/v1/me/password/", {"new_password": "neela-asman-77"}, format="json").status_code == 204
    r = anon.post("/api/v1/auth/login/", {"phone": "03017654321", "password": "neela-asman-77"}, format="json")
    assert r.status_code == 200 and r.json()["user"]["has_password"] is True
    assert "auth.password_set" in actions()
    # once a password exists, changing it needs the old one again
    r = api.post("/api/v1/me/password/", {"new_password": "doosra-raasta-88"}, format="json")
    assert r.status_code == 400 and r.json()["error"] == "invalid_credentials"


def test_phone_taken_by_other_account(app_key, anon, patient_user):
    from django.contrib.auth import get_user_model
    gid = g(anon, consent=True).json()["user"]["id"]
    api = logged_in(app_key, get_user_model().objects.get(pk=gid))
    r = api.patch("/api/v1/me/", {"phone": "03001234567"}, format="json")
    assert r.status_code == 400 and "phone" in r.json()["fields"]


def test_staff_list_shows_google_patient(app_key, anon, hakeem):
    g(anon, consent=True)
    rows = hakeem.get("/api/v1/staff/patients/?search=amina@").json()["results"]
    assert len(rows) == 1 and rows[0]["phone"] is None and rows[0]["email"] == "amina@gmail.com"


# ------------------------------------------------------------------- the real verifier (no network)
def test_real_verifier_checks_signature_audience_and_issuer(monkeypatch):
    import time

    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID
    from cryptography import x509
    import datetime
    from google.auth import crypt, jwt
    from google.oauth2 import id_token

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "test")])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(1).not_valid_before(now - datetime.timedelta(days=1))
            .not_valid_after(now + datetime.timedelta(days=1)).sign(key, __import__("cryptography.hazmat.primitives.hashes",
                                                                                      fromlist=["SHA256"]).SHA256()))
    pem_cert = cert.public_bytes(serialization.Encoding.PEM).decode()
    pem_key = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                serialization.NoEncryption()).decode()
    signer = crypt.RSASigner.from_string(pem_key, key_id="k1")
    monkeypatch.setattr(id_token, "_fetch_certs", lambda request, url: {"k1": pem_cert})
    google.set_verifier(None)

    def token(**over):
        t = int(time.time())
        claims = {"iss": "https://accounts.google.com", "aud": CLIENT_ID, "sub": "999", "email": "a@gmail.com",
                  "email_verified": True, "name": "A", "iat": t, "exp": t + 600, **over}
        return jwt.encode(signer, claims).decode()

    ident = google.verify(token())
    assert ident == GoogleIdentity("999", "a@gmail.com", True, "A")
    for bad in (token(aud="someone-else.apps.googleusercontent.com"), token(iss="https://evil.example"),
                token(exp=int(time.time()) - 3600, iat=int(time.time()) - 7200), token()[:-4] + "AAAA"):
        with pytest.raises(GoogleTokenInvalid):
            google.verify(bad)
