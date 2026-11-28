"""Social sign-in (Google, Facebook, Apple, Microsoft) through django-allauth.

Most tests replace the token check with a fake (accounts.social.set_verifier). The real allauth checks are tested at
the end with tokens signed by a local key (no network)."""
import base64
import hashlib
import json
import time
from urllib.parse import parse_qs, urlparse

import pytest
from allauth.socialaccount.models import SocialAccount as SocialLink
from django.contrib.auth import get_user_model

from accounts import social
from accounts.models import PatientProfile
from accounts.social import SocialIdentity, SocialTokenInvalid, SocialUnavailable
from audit.models import AuditEvent

from .conftest import logged_in, make_user

GOOGLE_ID = "1234-web.apps.googleusercontent.com"
FB_ID, FB_SECRET = "555000111", "fb-secret-for-tests"
APPLE_ID = "org.nazria.app.signin"
MS_ID = "00000000-aaaa-bbbb-cccc-000000000001"

TOKENS = {
    ("google", "tok-amina"): SocialIdentity("google", "1001", "amina@gmail.com", True, "Amina Bibi"),
    ("google", "tok-other"): SocialIdentity("google", "2002", "other@gmail.com", True, "Other"),
    ("google", "tok-unverified"): SocialIdentity("google", "3003", "x@example.com", False, "X"),
    ("facebook", "fb-amina"): SocialIdentity("facebook", "fb-77", "amina@fb.example", False, "Amina FB"),
    ("apple", "ap-amina"): SocialIdentity("apple", "001234.abcd", "x7@privaterelay.appleid.com", True, ""),
    ("microsoft", "ms-amina"): SocialIdentity("microsoft", "oid-42", "amina@outlook.com", False, "Amina MS"),
}


def configure(settings, *, google=True, facebook=True, apple=True, microsoft=True, public_url="https://nazria.example"):
    p = settings.SOCIALACCOUNT_PROVIDERS
    settings.SOCIALACCOUNT_PROVIDERS = {
        **p,
        "google": {**p["google"], "APPS": [{"client_id": GOOGLE_ID, "secret": "", "key": ""}] if google else []},
        "facebook": {**p["facebook"], "APPS": [{"client_id": FB_ID, "secret": FB_SECRET, "key": ""}] if facebook else []},
        "apple": {**p["apple"], "APPS": [{"client_id": APPLE_ID, "secret": "", "key": "",
                                          "settings": {"certificate_key": ""}}] if apple else []},
        "microsoft": {**p["microsoft"], "APPS": [{"client_id": MS_ID, "secret": "", "key": ""}] if microsoft else [],
                      "TENANT": "common"},
    }
    settings.NAZRIA_GOOGLE_CLIENT_IDS = [GOOGLE_ID] if google else []
    settings.NAZRIA_PUBLIC_URL = public_url


def fake_verify(request, provider, token):
    t = token.get("id_token") or token.get("access_token")
    if t == "tok-down":
        raise SocialUnavailable()
    if (provider, t) not in TOKENS:
        raise SocialTokenInvalid()
    if provider == "apple" and token.get("nonce") != "raw-nonce":
        raise SocialTokenInvalid()
    return TOKENS[(provider, t)]


@pytest.fixture(autouse=True)
def providers_on(settings):
    configure(settings)
    social.set_verifier(fake_verify)
    yield
    social.set_verifier(None)


def g(anon, token="tok-amina", **extra):
    """The older Google route."""
    return anon.post("/api/v1/auth/google/", {"id_token": token, **extra}, format="json")


def sign_up(anon, provider="google", **token):
    """First sign-in (400 consent_required) then the same with signup_token + consent."""
    token = token or {"id_token": "tok-amina"}
    r = anon.post(f"/api/v1/auth/social/{provider}/", token, format="json")
    assert r.status_code == 400 and r.json()["error"] == "consent_required", r.content
    r = anon.post(f"/api/v1/auth/social/{provider}/", {"signup_token": r.json()["signup_token"], "consent": True},
                  format="json")
    assert r.status_code == 201, r.content
    return r.json()


def actions():
    return list(AuditEvent.objects.order_by("id").values_list("action", flat=True))


# ------------------------------------------------------------------- sign-up and sign-in
def test_new_account_needs_consent_then_is_created(anon):
    r = anon.post("/api/v1/auth/social/google/", {"id_token": "tok-amina", "gender": "female"}, format="json")
    assert r.status_code == 400 and r.json()["error"] == "consent_required" and r.json()["signup_token"]
    assert not SocialLink.objects.exists()
    r = anon.post("/api/v1/auth/social/google/", {"signup_token": r.json()["signup_token"], "consent": True,
                                                  "gender": "female", "birth_year": 1990}, format="json")
    assert r.status_code == 201, r.content
    body = r.json()
    assert body["created"] is True and body["provider"] == "google" and body["access"] and body["refresh"]
    u = body["user"]
    assert u["phone"] is None and u["email"] == "amina@gmail.com" and u["full_name"] == "Amina Bibi"
    assert u["role"] == "patient" and u["has_password"] is False and u["linked_providers"] == ["google"]
    assert u["consent_at"] and u["gender"] == "female"
    link = SocialLink.objects.get()
    assert (link.provider, link.uid) == ("google", "1001") and link.extra_data["email"] == "amina@gmail.com"
    assert "auth.social_consent_required" in actions() and "auth.social_register" in actions()


@pytest.mark.parametrize("provider,token,name", [
    ("facebook", {"access_token": "fb-amina"}, "Amina FB"),
    ("apple", {"id_token": "ap-amina", "nonce": "raw-nonce"}, ""),
    ("microsoft", {"id_token": "ms-amina"}, "Amina MS"),
])
def test_every_provider_signs_up_and_in(anon, provider, token, name):
    body = sign_up(anon, provider, **token)
    assert body["provider"] == provider and body["user"]["linked_providers"] == [provider]
    assert body["user"]["full_name"] == name
    r = anon.post(f"/api/v1/auth/social/{provider}/", token, format="json")
    assert r.status_code == 200 and r.json()["created"] is False and r.json()["user"]["id"] == body["user"]["id"]
    assert get_user_model().objects.get(pk=body["user"]["id"]).username.startswith(provider[0] + "_")


def test_apple_name_from_first_sign_in(anon):
    r = anon.post("/api/v1/auth/social/apple/", {"id_token": "ap-amina", "nonce": "raw-nonce"}, format="json")
    r = anon.post("/api/v1/auth/social/apple/", {"signup_token": r.json()["signup_token"], "consent": True,
                                                 "full_name": "Amina Apple"}, format="json")
    assert r.status_code == 201 and r.json()["user"]["full_name"] == "Amina Apple"


def test_signup_token_is_bound_to_provider_and_signed(anon):
    r = anon.post("/api/v1/auth/social/google/", {"id_token": "tok-amina"}, format="json")
    st = r.json()["signup_token"]
    r = anon.post("/api/v1/auth/social/facebook/", {"signup_token": st, "consent": True}, format="json")
    assert r.status_code == 401 and r.json()["error"] == "invalid_social_token"
    r = anon.post("/api/v1/auth/social/google/", {"signup_token": st[:-3] + "xyz", "consent": True}, format="json")
    assert r.status_code == 401
    assert not SocialLink.objects.exists()


def test_signup_token_expires(anon, monkeypatch):
    st = anon.post("/api/v1/auth/social/google/", {"id_token": "tok-amina"}, format="json").json()["signup_token"]
    monkeypatch.setattr(social, "SIGNUP_MAX_AGE_S", -1)
    r = anon.post("/api/v1/auth/social/google/", {"signup_token": st, "consent": True}, format="json")
    assert r.status_code == 401


def test_same_person_different_providers_are_separate_accounts(anon):
    """Never joined by e-mail: a second provider is added by linking, while logged in."""
    a = sign_up(anon, "google")
    b = sign_up(anon, "microsoft", id_token="ms-amina")
    assert a["user"]["id"] != b["user"]["id"]


def test_second_sign_in_logs_in_without_consent(anon):
    sign_up(anon)
    r = anon.post("/api/v1/auth/social/google/", {"id_token": "tok-amina"}, format="json")
    assert r.status_code == 200 and r.json()["created"] is False
    assert SocialLink.objects.count() == 1 and PatientProfile.objects.count() == 1
    assert actions().count("auth.social_login") == 1


def test_tokens_work_and_refresh(anon):
    tokens = sign_up(anon)
    c = anon
    c.credentials(HTTP_X_API_KEY=anon._credentials["HTTP_X_API_KEY"], HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")
    assert c.get("/api/v1/me/").json()["email"] == "amina@gmail.com"
    assert c.post("/api/v1/auth/refresh/", {"refresh": tokens["refresh"]}, format="json").status_code == 200


@pytest.mark.parametrize("provider,token,http,code", [
    ("google", {"id_token": "bad"}, 401, "invalid_social_token"),
    ("google", {"id_token": "tok-down"}, 503, "provider_unavailable"),
    ("google", {"id_token": "tok-unverified"}, 400, "email_unverified"),
    ("apple", {"id_token": "ap-amina", "nonce": "someone-elses"}, 401, "invalid_social_token"),
    ("apple", {"id_token": "ap-amina"}, 401, "invalid_social_token"),
    ("facebook", {"access_token": "tok-down"}, 503, "provider_unavailable"),
    ("google", {}, 400, "invalid_request"),
    ("twitter", {"id_token": "x"}, 404, "not_found"),
])
def test_rejected(anon, provider, token, http, code):
    r = anon.post(f"/api/v1/auth/social/{provider}/", {**token, "consent": True}, format="json")
    assert r.status_code == http and r.json()["error"] == code, r.content
    assert not SocialLink.objects.exists()


def test_disabled_provider(anon, settings):
    configure(settings, facebook=False, microsoft=False, public_url="")
    r = anon.post("/api/v1/auth/social/facebook/", {"access_token": "fb-amina", "consent": True}, format="json")
    assert r.status_code == 503 and r.json()["error"] == "provider_disabled"
    h = anon.get("/api/v1/health/").json()
    assert h["social_providers"] == ["google", "apple"] and h["google_login_enabled"] is True
    assert h["social_config"]["apple"]["start_url"] is None             # no HTTPS address: no web sign-in


def test_facebook_needs_the_app_secret(anon, settings):
    configure(settings)
    settings.SOCIALACCOUNT_PROVIDERS["facebook"]["APPS"][0]["secret"] = ""
    assert "facebook" not in anon.get("/api/v1/health/").json()["social_providers"]


def test_health_lists_providers_and_public_ids_only(anon):
    h = anon.get("/api/v1/health/").json()
    assert h["social_providers"] == ["google", "facebook", "apple", "microsoft"]
    assert h["social_config"] == {
        "google": {"client_id": GOOGLE_ID}, "facebook": {"app_id": FB_ID},
        "apple": {"client_id": APPLE_ID, "start_url": "https://nazria.example/api/v1/auth/apple/start/"},
        "microsoft": {"client_id": MS_ID, "tenant": "common"}}
    assert FB_SECRET not in json.dumps(h)


def test_needs_app_key(client):
    r = client.post("/api/v1/auth/social/google/", {"id_token": "tok-amina", "consent": True},
                    content_type="application/json")
    assert r.status_code == 403 and r.json()["error"] == "app_key_invalid"


def test_tokens_never_logged_or_stored(anon):
    sign_up(anon)
    sign_up(anon, "facebook", access_token="fb-amina")
    for e in AuditEvent.objects.all():
        assert "tok-amina" not in str(e.details) and "fb-amina" not in str(e.details)
    for link in SocialLink.objects.all():
        assert "tok-amina" not in json.dumps(link.extra_data) and "fb-amina" not in json.dumps(link.extra_data)
    from allauth.socialaccount.models import SocialToken
    assert not SocialToken.objects.exists()


def test_inactive_user_refused(anon):
    uid = sign_up(anon)["user"]["id"]
    get_user_model().objects.filter(pk=uid).update(is_active=False)
    r = anon.post("/api/v1/auth/social/google/", {"id_token": "tok-amina"}, format="json")
    assert r.status_code == 403 and r.json()["error"] == "account_disabled"


# ------------------------------------------------------------------- the older Google route
def test_legacy_google_route_and_codes(anon, settings):
    r = g(anon)
    assert r.status_code == 400 and r.json()["error"] == "consent_required"
    r = g(anon, consent=True)                    # an older app sends the ID token again: allowed by the fake
    assert r.status_code == 201 and r.json()["created"] is True
    assert g(anon).status_code == 200
    assert g(anon, "bad").json()["error"] == "invalid_google_token"
    assert g(anon, "tok-down").json()["error"] == "google_unavailable"
    assert g(anon, "tok-unverified").json()["error"] == "google_email_unverified"
    configure(settings, google=False)
    r = g(anon, consent=True)
    assert r.status_code == 503 and r.json()["error"] == "google_login_disabled"


# ------------------------------------------------------------------- linking to an existing account
def test_phone_patient_links_providers_then_signs_in_with_them(app_key, anon, patient_user):
    api = logged_in(app_key, patient_user)
    r = api.post("/api/v1/me/social/google/", {"id_token": "tok-amina"}, format="json")
    assert r.status_code == 200 and r.json()["linked_providers"] == ["google"]
    assert r.json()["email"] == "amina@gmail.com"
    r = api.post("/api/v1/me/social/facebook/", {"access_token": "fb-amina"}, format="json")
    assert r.status_code == 200 and r.json()["linked_providers"] == ["facebook", "google"]
    assert r.json()["email"] == "amina@gmail.com"                    # an unverified e-mail never replaces it
    for provider, token in (("google", {"id_token": "tok-amina"}), ("facebook", {"access_token": "fb-amina"})):
        r = anon.post(f"/api/v1/auth/social/{provider}/", token, format="json")
        assert r.status_code == 200 and r.json()["user"]["id"] == patient_user.pk
    assert "auth.social_link" in actions()


def test_legacy_google_link_route(app_key, patient_user):
    api = logged_in(app_key, patient_user)
    assert api.post("/api/v1/me/google/", {"id_token": "tok-amina"}, format="json").json()["linked_providers"] == ["google"]
    assert api.delete("/api/v1/me/google/").json()["linked_providers"] == []


def test_link_conflicts(app_key, anon, patient_user):
    sign_up(anon, id_token="tok-other")                 # tok-other already has its own account
    api = logged_in(app_key, patient_user)
    r = api.post("/api/v1/me/social/google/", {"id_token": "tok-other"}, format="json")
    assert r.status_code == 409 and r.json()["error"] == "social_already_linked"
    assert api.post("/api/v1/me/google/", {"id_token": "tok-other"}, format="json").json()["error"] == \
        "google_already_linked"
    assert api.post("/api/v1/me/social/google/", {"id_token": "tok-amina"}, format="json").status_code == 200
    r = api.post("/api/v1/me/social/google/", {"id_token": "tok-amina"}, format="json")       # idempotent
    assert r.status_code == 200 and SocialLink.objects.filter(user=patient_user).count() == 1


def test_unlink_only_with_another_login_method(app_key, anon, patient_user):
    api = logged_in(app_key, patient_user)
    api.post("/api/v1/me/social/google/", {"id_token": "tok-amina"}, format="json")
    r = api.delete("/api/v1/me/social/google/")
    assert r.status_code == 200 and r.json()["linked_providers"] == []
    assert api.delete("/api/v1/me/social/google/").status_code == 404
    assert api.delete("/api/v1/me/social/myspace/").status_code == 404

    gid = sign_up(anon, id_token="tok-other")["user"]["id"]
    gapi = logged_in(app_key, get_user_model().objects.get(pk=gid))
    r = gapi.delete("/api/v1/me/social/google/")
    assert r.status_code == 409 and r.json()["error"] == "last_login_method"
    # with a second provider linked, the first can go
    assert gapi.post("/api/v1/me/social/microsoft/", {"id_token": "ms-amina"}, format="json").status_code == 200
    r = gapi.delete("/api/v1/me/social/google/")
    assert r.status_code == 200 and r.json()["linked_providers"] == ["microsoft"]
    assert gapi.delete("/api/v1/me/social/microsoft/").status_code == 409
    assert "auth.social_unlink" in actions()


def test_staff_cannot_use_social_sign_in(app_key, anon):
    staff = make_user("+923331112223", name="Hakeem", staff=True)
    r = logged_in(app_key, staff).post("/api/v1/me/social/google/", {"id_token": "tok-amina"}, format="json")
    assert r.status_code == 403 and r.json()["error"] == "staff_password_only"
    SocialLink.objects.create(user=staff, provider="google", uid="1001")
    r = anon.post("/api/v1/auth/social/google/", {"id_token": "tok-amina"}, format="json")
    assert r.status_code == 403 and r.json()["error"] == "staff_password_only"


# ------------------------------------------------------------------- a social account adds phone + password
def test_social_account_adds_phone_and_password_then_phone_login(app_key, anon):
    gid = sign_up(anon, "facebook", access_token="fb-amina")["user"]["id"]
    api = logged_in(app_key, get_user_model().objects.get(pk=gid))
    r = api.patch("/api/v1/me/", {"phone": "0301-7654321"}, format="json")
    assert r.status_code == 200 and r.json()["phone"] == "+923017654321"
    assert api.patch("/api/v1/me/", {"phone": "0301-0000000"}, format="json").status_code == 400
    assert api.post("/api/v1/me/password/", {"new_password": "neela-asman-77"}, format="json").status_code == 204
    r = anon.post("/api/v1/auth/login/", {"phone": "03017654321", "password": "neela-asman-77"}, format="json")
    assert r.status_code == 200 and r.json()["user"]["has_password"] is True
    assert "auth.password_set" in actions()
    r = api.post("/api/v1/me/password/", {"new_password": "doosra-raasta-88"}, format="json")
    assert r.status_code == 400 and r.json()["error"] == "invalid_credentials"
    assert api.delete("/api/v1/me/social/facebook/").status_code == 200      # phone + password now exist


def test_phone_taken_by_other_account(app_key, anon, patient_user):
    gid = sign_up(anon)["user"]["id"]
    api = logged_in(app_key, get_user_model().objects.get(pk=gid))
    r = api.patch("/api/v1/me/", {"phone": "03001234567"}, format="json")
    assert r.status_code == 400 and "phone" in r.json()["fields"]


def test_staff_list_shows_social_patient(app_key, anon, hakeem):
    sign_up(anon)
    rows = hakeem.get("/api/v1/staff/accounts/?search=amina@").json()["results"]
    assert len(rows) == 1 and rows[0]["phone"] is None and rows[0]["email"] == "amina@gmail.com"


# ------------------------------------------------------------------- Sign in with Apple through the browser
def test_apple_web_start_and_callback(client, db):
    nonce_hash = hashlib.sha256(b"raw-nonce").hexdigest()
    r = client.get("/api/v1/auth/apple/start/", {"nonce": nonce_hash, "state": "app-state-0123456789"})
    assert r.status_code == 302
    url = urlparse(r["Location"])
    q = {k: v[0] for k, v in parse_qs(url.query).items()}
    assert url.netloc == "appleid.apple.com" and q["client_id"] == APPLE_ID and q["nonce"] == nonce_hash
    assert q["redirect_uri"] == "https://nazria.example/api/v1/auth/apple/callback/"
    assert q["response_mode"] == "form_post" and q["response_type"] == "code id_token"
    assert "app-state" not in q["state"] or q["state"] != "app-state-0123456789"     # our own signed state

    user = json.dumps({"name": {"firstName": "Amina", "lastName": "Bibi"}, "email": "x@privaterelay.appleid.com"})
    r = client.post("/api/v1/auth/apple/callback/", {"state": q["state"], "id_token": "ap-amina", "code": "c",
                                                     "user": user})
    assert r.status_code == 200 and r["Cache-Control"] == "no-store"
    html = r.content.decode()
    target = html.split("url=")[1].split("'")[0].replace("&amp;", "&")
    t = urlparse(target)
    tq = {k: v[0] for k, v in parse_qs(t.query).items()}
    assert f"{t.scheme}://{t.netloc}{t.path}" == "org.nazria.app://auth/apple"
    assert tq == {"state": "app-state-0123456789", "id_token": "ap-amina", "name": "Amina Bibi"}
    assert not any("ap-amina" in str(e.details) for e in AuditEvent.objects.all())


def test_apple_web_errors(client, settings, db):
    assert client.get("/api/v1/auth/apple/start/", {"nonce": "short", "state": "app-state-0123456789"}).status_code == 400
    assert client.post("/api/v1/auth/apple/callback/", {"state": "forged", "id_token": "x"}).status_code == 400
    nonce_hash = hashlib.sha256(b"n").hexdigest()
    r = client.get("/api/v1/auth/apple/start/", {"nonce": nonce_hash, "state": "app-state-0123456789"})
    state = parse_qs(urlparse(r["Location"]).query)["state"][0]
    r = client.post("/api/v1/auth/apple/callback/", {"state": state, "error": "user_cancelled_authorize"})
    assert "error=user_cancelled_authorize" in r.content.decode()
    configure(settings, public_url="http://203.0.113.10")             # Apple needs HTTPS
    assert client.get("/api/v1/auth/apple/start/", {"nonce": nonce_hash, "state": "app-state-0123456789"}).status_code == 503


# ------------------------------------------------------------------- the real allauth checks (local keys, no network)
@pytest.fixture
def signer(monkeypatch, db):
    """Tokens signed with a local RSA key; allauth fetches the 'public keys' from this fake instead of the network."""
    import jwt as pyjwt
    from cryptography.hazmat.primitives.asymmetric import rsa

    from allauth.socialaccount.internal import jwtkit

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pub = key.public_key()
    seen = []

    def fake_fetch_key(credential, keys_url, lookup):
        seen.append(keys_url)
        if pyjwt.get_unverified_header(credential).get("kid") != "k1":
            from allauth.socialaccount.providers.oauth2.client import OAuth2Error
            raise OAuth2Error("Invalid 'kid'")
        return "RS256", pub

    monkeypatch.setattr(jwtkit, "fetch_key", fake_fetch_key)
    social.set_verifier(None)

    def sign(claims: dict, kid="k1") -> str:
        t = int(time.time())
        return pyjwt.encode({"iat": t, "exp": t + 600, **claims}, key, algorithm="RS256", headers={"kid": kid})
    sign.seen = seen
    return sign


def _verify(provider, token):
    from django.test import RequestFactory
    return social.verify(RequestFactory().post("/"), provider, token)


def test_real_google_check(signer):
    good = {"iss": "https://accounts.google.com", "aud": GOOGLE_ID, "sub": "999", "email": "a@gmail.com",
            "email_verified": True, "name": "A"}
    ident = _verify("google", {"id_token": signer(good)})
    assert (ident.uid, ident.email, ident.email_verified, ident.name) == ("999", "a@gmail.com", True, "A")
    for bad in ({**good, "aud": "someone-else.apps.googleusercontent.com"}, {**good, "iss": "https://evil.example"},
                {**good, "exp": int(time.time()) - 3600}):
        with pytest.raises(SocialTokenInvalid):
            _verify("google", {"id_token": signer(bad)})
    with pytest.raises(SocialTokenInvalid):
        _verify("google", {"id_token": signer(good)[:-4] + "AAAA"})
    with pytest.raises(SocialTokenInvalid):
        _verify("google", {"id_token": signer(good, kid="other")})


def test_real_google_token_used_once(signer):
    tok = signer({"iss": "https://accounts.google.com", "aud": GOOGLE_ID, "sub": "9", "email": "a@gmail.com",
                  "email_verified": True, "jti": "once-1"})
    _verify("google", {"id_token": tok})
    with pytest.raises(SocialTokenInvalid):                     # allauth's replay protection
        _verify("google", {"id_token": tok})


def test_real_apple_check_with_nonce(signer):
    claims = {"iss": "https://appleid.apple.com", "aud": APPLE_ID, "sub": "001.apple", "email": "r@privaterelay.appleid.com",
              "email_verified": "true", "nonce": hashlib.sha256(b"raw-nonce").hexdigest()}
    ident = _verify("apple", {"id_token": signer(claims), "nonce": "raw-nonce"})
    assert ident.uid == "001.apple" and ident.email_verified is True
    with pytest.raises(SocialTokenInvalid):
        _verify("apple", {"id_token": signer(claims), "nonce": "stolen-token-wrong-nonce"})
    with pytest.raises(SocialTokenInvalid):
        _verify("apple", {"id_token": signer({**claims, "aud": "com.other.app"}), "nonce": "raw-nonce"})


def test_real_microsoft_check(signer, settings):
    tid = "72f988bf-0000-0000-0000-000000000001"
    claims = {"iss": f"https://login.microsoftonline.com/{tid}/v2.0", "aud": MS_ID, "tid": tid, "oid": "oid-7",
              "sub": "pairwise-sub", "name": "Amina MS", "preferred_username": "amina@contoso.example"}
    ident = _verify("microsoft", {"id_token": signer(claims)})
    assert ident.uid == "oid-7" and ident.name == "Amina MS" and ident.email_verified is False
    assert signer.seen[-1] == "https://login.microsoftonline.com/common/discovery/v2.0/keys"
    for bad in ({**claims, "aud": "another-app"}, {**claims, "iss": "https://login.microsoftonline.com/x/v2.0"},
                {**claims, "tid": ""}):
        with pytest.raises(SocialTokenInvalid):
            _verify("microsoft", {"id_token": signer(bad)})
    settings.SOCIALACCOUNT_PROVIDERS["microsoft"]["TENANT"] = "consumers"          # personal accounts only
    with pytest.raises(SocialTokenInvalid):
        _verify("microsoft", {"id_token": signer(claims)})


def test_real_facebook_check(monkeypatch, db):
    """Facebook access tokens are checked with Graph API debug_token (app secret) and /me."""
    social.set_verifier(None)
    calls = []

    class Resp:
        def __init__(self, data, status=200):
            self._d, self.status_code, self.ok = data, status, status < 400

        def json(self):
            return self._d

        def raise_for_status(self):
            if self.status_code >= 400:
                import requests
                raise requests.HTTPError(response=self)

    class FakeSession:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get(self, url, params=None, **kw):
            calls.append((url, params))
            if url.endswith("/oauth/access_token"):
                assert params["client_secret"] == FB_SECRET
                return Resp({"access_token": "app-token"})
            if url.endswith("/debug_token"):
                ok = params["input_token"] == "fb-good"
                return Resp({"data": {"is_valid": ok, "app_id": FB_ID if ok else "999"}})
            if url.endswith("/me"):
                return Resp({"id": "fb-77", "email": "amina@fb.example", "name": "Amina FB"})
            raise AssertionError(url)

    from allauth.socialaccount import adapter as aa
    monkeypatch.setattr(aa.DefaultSocialAccountAdapter, "get_requests_session", lambda self: FakeSession())
    monkeypatch.setattr(social.NazriaSocialAccountAdapter, "get_requests_session", lambda self: FakeSession())
    ident = _verify("facebook", {"access_token": "fb-good"})
    assert (ident.uid, ident.name, ident.email) == ("fb-77", "Amina FB", "amina@fb.example")
    assert not ident.email_verified
    with pytest.raises(SocialTokenInvalid):
        _verify("facebook", {"access_token": "fb-forged"})


def test_network_failure_is_unavailable(monkeypatch, db):
    import requests

    from allauth.socialaccount.internal import jwtkit
    social.set_verifier(None)

    def down(*a, **k):
        raise requests.ConnectionError("down")
    monkeypatch.setattr(jwtkit, "fetch_key", down)
    payload = base64.urlsafe_b64encode(json.dumps({"aud": GOOGLE_ID}).encode()).decode().rstrip("=")
    with pytest.raises(SocialUnavailable):
        _verify("google", {"id_token": f"e30.{payload}.sig"})


# ------------------------------------------------------------------- the data migration
def test_old_google_links_are_copied_to_allauth(patient_user):
    import importlib

    from django.apps import apps as django_apps

    from accounts.models import SocialAccount as OldLink
    OldLink.objects.create(user=patient_user, provider="google", uid="g-old-1", email="old@gmail.com",
                           email_verified=True, name="Old")
    mig = importlib.import_module("accounts.migrations.0005_copy_google_links_to_allauth")
    mig.copy_links(django_apps, None)
    mig.copy_links(django_apps, None)                          # again: nothing twice
    link = SocialLink.objects.get(provider="google", uid="g-old-1")
    assert link.user_id == patient_user.pk and link.extra_data["email"] == "old@gmail.com"
    assert SocialLink.objects.filter(uid="g-old-1").count() == 1
    assert OldLink.objects.count() == 1                        # the old table is kept
