"""REST API for the Android app: authentication, questionnaire, triage, consultations, explanations."""
import json

import pytest

from consultations import services
from consultations.models import ApiClient, Consultation
from nazria_kb.engine import QuestionnaireEngine, Session
from nazria_kb.providers import FakeProvider, ProviderError

from .conftest import REFERENCE

pytestmark = pytest.mark.django_db


def create(api, answers=REFERENCE):
    return api.post("/api/v1/consultations/", {"answers": answers}, format="json")


def token_get(api, r, suffix="", method="get"):
    return getattr(api, method)(f"/api/v1/consultations/{r.data['id']}/{suffix}")


# ---------------------------------------------------------------- access
def test_health_needs_no_key(client):
    r = client.get("/api/v1/health/")
    assert r.status_code == 200 and r.json() == {"status": "ok", "database": "ok", "explanation_enabled": False,
                                                 "api_version": 1}


def test_app_key_is_required_and_checked(client, app_key):
    r = client.get("/api/v1/questionnaire/")
    assert r.status_code == 403 and r.json()["error"] == "app_key_invalid"
    assert client.get("/api/v1/questionnaire/", HTTP_X_API_KEY="nzr_bad_key").status_code == 403
    c, key = ApiClient.create("revoked")
    ApiClient.objects.filter(pk=c.pk).update(is_active=False)
    assert client.get("/api/v1/questionnaire/", HTTP_X_API_KEY=key).status_code == 403
    assert client.get("/api/v1/questionnaire/", HTTP_X_API_KEY=app_key).status_code == 200
    assert ApiClient.objects.get(name="android-test").key_hash != app_key


def test_consultations_need_a_login(anon):
    assert anon.post("/api/v1/consultations/", {"answers": REFERENCE}, format="json").status_code == 401
    assert anon.get("/api/v1/consultations/").status_code == 401


def test_create_api_client_command_prints_a_working_key(client, capsys):
    from django.core.management import call_command
    call_command("create_api_client", "android-v1")
    key = capsys.readouterr().out.strip().splitlines()[-1]
    assert key.startswith("nzr_")
    assert client.get("/api/v1/questionnaire/", HTTP_X_API_KEY=key).status_code == 200
    from django.core.management.base import CommandError
    with pytest.raises(CommandError):
        call_command("create_api_client", "android-v1")


def test_openapi_schema_is_public(client):
    r = client.get("/api/schema/")
    assert r.status_code == 200 and b"/api/v1/consultations/" in r.content and b"X-Api-Key" in r.content


# ---------------------------------------------------------------- questionnaire and triage
def test_questionnaire_for_the_app(anon):
    api = anon
    r = api.get("/api/v1/questionnaire/")
    qs = r.data["questions"]
    assert [q["id"] for q in qs][:2] == ["red_flags", "complaint"] and len(qs) == 14
    assert qs[0]["kind"] == "multi" and qs[0]["emergency_unless"] == ["none"] and len(qs[0]["options"]) == 10
    assert next(q for q in qs if q["id"] == "pregnancy")["skip_if"] == {"question_id": "age_group", "equals": "child"}
    assert "weights" not in json.dumps(r.data) and "pages" not in json.dumps(r.data)
    assert api.get("/api/v1/questionnaire/").data["version"] == r.data["version"]


@pytest.mark.parametrize("body,emergency,flags", [
    ({"red_flags": ["none"]}, False, []),
    ({"red_flags": ["chest_pain", "breathing"]}, True, ["chest_pain", "breathing"]),
    ({"red_flags": ["none"], "complaint": "میرے سینے میں شدید درد ہے"}, True, ["chest_pain"]),
    ({"red_flags": ["none"], "complaint": "خودکشی کے خیالات آتے ہیں"}, True, ["self_harm"]),
])
def test_triage(anon, body, emergency, flags):
    r = anon.post("/api/v1/triage/", body, format="json")
    assert r.status_code == 200 and r.data["emergency"] is emergency and r.data["flags"] == flags
    assert (r.data["message"] is not None) is emergency
    if "self_harm" in flags:
        assert "اکیلے نہیں" in r.data["message"]


def test_triage_rejects_unknown_options(anon):
    r = anon.post("/api/v1/triage/", {"red_flags": ["fever"]}, format="json")
    assert r.status_code == 400 and r.data["error"] == "invalid_request"


# ---------------------------------------------------------------- consultations
def test_reference_consultation_matches_the_cli(api, kb):
    r = create(api)
    assert r.status_code == 201, r.data
    d = r.data
    a = d["assessment"]
    assert d["status"] == "completed" and d["emergency"] is None
    assert a["primary_system"] == "عضلاتی" and a["totals"] == {"اعصابی": 0, "عضلاتی": 8, "غدی": 0} and a["conclusive"]
    assert a["evidence"][0] == {"question_id": "urine_color", "option_key": "red", "question": a["evidence"][0]["question"],
                                "answer": "سرخ یا سرخی مائل", "system": "عضلاتی",
                                "citation": {"volume": 2, "volume_name": "جلد دوم", "pages": [125, 127, 133],
                                             "text": "جلد دوم، صفحات 125، 127، 133"}}
    book = d["book"]
    assert book["topic"]["id"] == 1603 and book["topic"]["citation"]["text"] == "جلد دوم، صفحہ 127"
    assert book["recipe"]["status"] == "shown" and "سناکی" in book["recipe"]["text"]
    assert d["advice"] and d["explanation"] is None and d["explanation_available"] is False
    # the same answers typed into the CLI engine give exactly the same Urdu text
    eng = QuestionnaireEngine(kb.retriever())
    s = Session()
    eng.start(s)
    for m in "10|مجھے پرانی قبض کی شکایت ہے|3|2|3|1|1|1|1|1|1|2|2|4".split("|"):
        reply = eng.reply(s, m)
    assert d["text"] == reply.text


def test_consultation_is_stored_in_the_patients_history(api, kb, app_key):
    r = create(api)
    uid = r.data["id"]
    s = kb.sessions[uid]
    assert s.status == "completed" and s.answers["urine_color"] == "red" and len(s.transcript) == 29
    c = Consultation.objects.get(pk=uid)
    assert c.primary_system == "عضلاتی" and c.patient == api.user and c.client.name == "android-test"
    got = api.get(f"/api/v1/consultations/{uid}/")
    assert got.status_code == 200 and got.data["assessment"] == r.data["assessment"] and got.data["patient"] == api.user.pk
    history = api.get("/api/v1/consultations/").data
    assert history["count"] == 1 and history["results"][0]["complaint"] == REFERENCE["complaint"]
    # another patient can neither see nor touch it
    from .conftest import logged_in, make_user
    other = logged_in(app_key, make_user("+923009999999"))
    assert other.get(f"/api/v1/consultations/{uid}/").status_code == 404
    assert other.delete(f"/api/v1/consultations/{uid}/").status_code == 404
    assert other.get("/api/v1/consultations/").data["count"] == 0


def test_delete_hides_from_the_patient_but_keeps_everything(api, kb, hakeem):
    r = create(api)
    assert token_get(api, r, method="delete").status_code == 204
    assert token_get(api, r).status_code == 404 and api.get("/api/v1/consultations/").data["count"] == 0
    c = Consultation.objects.get(pk=r.data["id"])
    assert c.deleted_at and c.deleted_by == api.user and r.data["id"] in kb.sessions      # nothing is removed
    staff_view = hakeem.get(f"/api/v1/consultations/{r.data['id']}/")
    assert staff_view.status_code == 200 and staff_view.data["deleted"] is True


@pytest.mark.parametrize("change,field,message", [
    ({"heart": None}, "heart", "required"),
    ({"heart": "maybe"}, "heart", "one option key"),
    ({"red_flags": "none"}, "red_flags", "list"),
    ({"complaint": "x"}, "complaint", "characters"),
    ({"mood": "good"}, "mood", "unknown question"),
])
def test_invalid_answers_are_explained_per_field(api, change, field, message):
    answers = {k: v for k, v in {**REFERENCE, **change}.items() if v is not None}
    r = create(api, answers)
    assert r.status_code == 400 and r.data["error"] == "invalid_answers" and message in r.data["fields"][field]
    assert not Consultation.objects.exists()


def test_emergency_needs_only_the_triage_answer_and_cannot_be_explained(api, monkeypatch):
    r = create(api, {"red_flags": ["breathing"]})
    assert r.status_code == 201 and r.data["status"] == "emergency" and r.data["assessment"] is None
    assert r.data["emergency"]["flags"] == ["breathing"] and "ہسپتال" in r.data["emergency"]["message"]
    assert api.get("/api/v1/consultations/").data["results"][0]["status"] == "emergency"
    monkeypatch.setenv("NAZRIA_ENGINE", "hybrid")
    assert token_get(api, r, "explanation/", "post").status_code == 409


def test_an_emergency_is_never_blocked_by_other_invalid_answers(api):
    r = create(api, {"red_flags": ["chest_pain"], "complaint": "x", "heart": "maybe", "mood": "bad"})
    assert r.status_code == 201 and r.data["status"] == "emergency"


def test_emergency_in_the_complaint_stops_the_consultation(api):
    r = create(api, {"red_flags": ["none"], "complaint": "میرے بچے نے غلطی سے زہر کھا لیا ہے"})
    assert r.status_code == 201 and r.data["status"] == "emergency" and r.data["emergency"]["flags"] == ["poisoning"]


def test_children_get_no_recipe_and_are_not_asked_about_pregnancy(api):
    answers = {k: v for k, v in REFERENCE.items() if k != "pregnancy"} | {"age_group": "child"}
    r = create(api, answers)
    assert r.status_code == 201, r.data
    recipe = r.data["book"]["recipe"]
    assert recipe["status"] == "withheld_vulnerable" and recipe["text"] is None and recipe["message"]
    assert "سناکی" not in json.dumps(r.data, ensure_ascii=False) and r.data["assessment"]["vulnerable"]


def test_hazardous_recipes_are_never_returned(api):
    r = create(api, {**REFERENCE, "complaint": "دمہ کی تکلیف ہے"})
    recipe = r.data["book"]["recipe"]
    assert recipe["status"] == "withheld_hazard" and recipe["text"] is None
    assert {h["code"] for h in recipe["hazards"]} == {"arsenic", "kushta", "mercury"}
    assert "سنکھیا ایک رتی" not in json.dumps(r.data, ensure_ascii=False)


def test_unknown_complaint_falls_back_to_safe_passages(api):
    r = create(api, {**REFERENCE, "complaint": "نزلہ رہتا ہے"})
    assert r.data["book"]["topic"] is None and r.data["book"]["passages"][0]["citation"]["text"] == "جلد دوم، صفحہ 128"


def test_database_errors_do_not_leak_connection_details(api, kb, monkeypatch):
    import psycopg
    def boom():
        raise psycopg.OperationalError("connection to server at secret-host failed: password=hunter2")
    monkeypatch.setattr(kb, "questions", boom)
    r = api.get("/api/v1/questionnaire/")
    assert r.status_code == 503 and r.data["error"] == "database_unavailable"
    assert "secret-host" not in json.dumps(r.data) and "hunter2" not in json.dumps(r.data)


# ---------------------------------------------------------------- AI explanation
GOOD = "کتاب کے مطابق عضلاتی قبض اکثر شدید اور دائمی ہوتی ہے (جلد دوم، صفحہ 127)۔ کسی مستند حکیم سے نبض و قارورہ کا معائنہ کروائیں۔"


def test_explanation_is_off_until_the_engine_is_switched(api):
    r = create(api)
    e = token_get(api, r, "explanation/", "post")
    assert e.status_code == 200 and e.data["status"] == "disabled"


def test_explanation_shown_stored_and_not_requested_twice(api, kb, monkeypatch):
    monkeypatch.setenv("NAZRIA_ENGINE", "hybrid")
    fp = FakeProvider([GOOD], name="gemini", model="gemini-test", external=True)
    services.set_provider(fp)
    r = create(api, {**REFERENCE, "complaint": "میرا نام احمد علی ہے، فون 03001234567، پرانی قبض ہے"})
    assert r.data["explanation_available"] is True
    e = token_get(api, r, "explanation/", "post")
    assert e.status_code == 200 and e.data["status"] == "shown", e.data
    assert e.data["text"].startswith("کتاب کے مطابق") and "ماخذ" not in e.data["text"]
    assert e.data["sources"][0]["citation"]["text"] == "جلد دوم، صفحہ 127"
    assert e.data["external_provider"] is True and "بیرونی AI" in e.data["notice"]
    sent = json.dumps(fp.calls[0]["messages"], ensure_ascii=False)
    assert "احمد علی" not in sent and "03001234567" not in sent        # identifying details never leave the server
    again = token_get(api, r, "explanation/", "post")
    assert again.data == e.data and len(fp.calls) == 1
    assert token_get(api, r).data["explanation"]["status"] == "shown"
    s = kb.sessions[r.data["id"]]
    assert s.engine == "hybrid" and s.provider == "gemini" and s.transcript[-1]["content"].startswith("وضاحت:")
    assert Consultation.objects.get(pk=r.data["id"]).explanation_status == "shown"


@pytest.mark.parametrize("answer,status,reason", [
    ("[NOT_COVERED]", "not_covered", None),
    ("آپ کی شکایت م比ں ہے (جلد دوم، صفحہ 127)", "rejected", "unusable_output"),
    ("عضلاتی قبض شدید ہوتی ہے۔", "rejected", "no_valid_citation"),
    (ProviderError("gemini", "quota", "daily quota used up"), "unavailable", "quota"),
])
def test_unusable_explanations_are_not_shown(api, monkeypatch, answer, status, reason):
    monkeypatch.setenv("NAZRIA_ENGINE", "hybrid")
    services.set_provider(FakeProvider([answer], name="gemini", model="m", external=True))
    e = token_get(api, create(api), "explanation/", "post")
    assert e.data["status"] == status and "text" not in e.data
    if reason:
        assert e.data["reason"] == reason


def test_explanation_without_permission_for_external_providers_is_unavailable(api, monkeypatch):
    monkeypatch.setenv("NAZRIA_ENGINE", "hybrid")
    monkeypatch.setenv("NAZRIA_LLM_PROVIDER", "gemini")        # NAZRIA_ALLOW_EXTERNAL_PROVIDERS not set
    e = token_get(api, create(api), "explanation/", "post")
    assert e.data == {"status": "unavailable", "reason": "policy", "retryable": False}


def test_explanations_are_rate_limited_per_client(api, monkeypatch):
    from accounts.throttles import ExplanationRateThrottle
    monkeypatch.setattr(ExplanationRateThrottle, "rate", "2/min", raising=False)
    r = create(api)
    codes = [token_get(api, r, "explanation/", "post").status_code for _ in range(3)]
    assert codes == [200, 200, 429]
