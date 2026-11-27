"""One account, many patients: general info, its history, diagnosis per patient, prefilled answers, re-diagnosis."""
import pytest

from consultations.models import Consultation
from nazria_kb.safety import CONDITION_NO_RECIPE, MEDICATION_ADVICE
from patients.models import Patient, PatientRevision

from .conftest import REFERENCE, logged_in, make_patient, make_user

pytestmark = pytest.mark.django_db

SIGNS = {k: v for k, v in REFERENCE.items() if k not in ("age_group", "pregnancy")}
NEW = {"full_name": "Amina", "relation": "child", "gender": "female", "birth_year": 2019, "weight_kg": 18.5,
       "chronic_conditions": ["asthma"], "consent": True}


def diagnose(api, answers=SIGNS, **body):
    return api.post("/api/v1/consultations/", {"answers": answers, **body}, format="json")


def test_intake_form_lists_the_general_info_to_ask(anon):
    r = anon.get("/api/v1/patients/intake-form/")
    assert r.status_code == 200 and r.data["version"]
    ids = [f["id"] for f in r.data["fields"]]
    assert ids[:4] == ["full_name", "relation", "gender", "birth_year"] and "consent" in ids
    required = {f["id"] for f in r.data["fields"] if f["required"]}
    assert required == {"full_name", "relation", "gender", "birth_year", "consent"}
    conditions = next(f for f in r.data["fields"] if f["id"] == "chronic_conditions")
    assert {"kidney", "liver", "heart", "diabetes"} <= {o["key"] for o in conditions["options"]}


def test_one_account_many_patients(api, app_key):
    r = api.post("/api/v1/patients/", NEW, format="json")
    assert r.status_code == 201, r.data
    p = r.data
    assert p["age_group"] == "child" and p["prefilled_questions"] == ["age_group", "pregnancy"]
    assert p["weight_kg"] == 18.5 and p["chronic_conditions"] == ["asthma"] and p["consultations"] == 0
    names = [x["full_name"] for x in api.get("/api/v1/patients/").data["results"]]
    assert names == ["Amina", "Test Patient"]                      # the default patient of the test client
    other = logged_in(app_key, make_user("+923009999999"))
    assert other.get(f"/api/v1/patients/{p['id']}/").status_code == 404
    assert [x["full_name"] for x in other.get("/api/v1/patients/").data["results"]] == ["Test Patient"]


@pytest.mark.parametrize("change,field", [({"consent": False}, "consent"), ({"birth_year": 2999}, "birth_year"),
                                          ({"gender": ""}, "gender"), ({"full_name": None}, "full_name"),
                                          ({"chronic_conditions": ["cancer"]}, "chronic_conditions")])
def test_patient_validation(api, change, field):
    body = {k: v for k, v in {**NEW, **change}.items() if v is not None}
    r = api.post("/api/v1/patients/", body, format="json")
    assert r.status_code == 400 and field in r.data["fields"]


def test_every_change_to_general_info_is_kept(api):
    pid = api.post("/api/v1/patients/", NEW, format="json").data["id"]
    r = api.patch(f"/api/v1/patients/{pid}/", {"weight_kg": 19.2, "medications": "Ventolin"}, format="json")
    assert r.status_code == 200 and r.data["weight_kg"] == 19.2
    api.patch(f"/api/v1/patients/{pid}/", {"weight_kg": 19.2}, format="json")          # no change: no revision
    h = api.get(f"/api/v1/patients/{pid}/history/").data
    assert [x["action"] for x in h["results"]] == ["updated", "created"]
    assert h["results"][0]["fields"] == ["medications", "weight_kg"] and h["results"][1]["data"]["weight_kg"] == 18.5
    rev = PatientRevision.objects.first()
    with pytest.raises(PermissionError):
        rev.delete()


def test_hidden_patient_is_kept_but_cannot_be_diagnosed(api, hakeem):
    pid = api.post("/api/v1/patients/", NEW, format="json").data["id"]
    assert api.delete(f"/api/v1/patients/{pid}/").status_code == 204
    assert api.get(f"/api/v1/patients/{pid}/").status_code == 404
    assert diagnose(api, patient_id=pid).status_code == 404
    assert Patient.objects.get(pk=pid).deleted_at is not None
    assert hakeem.get(f"/api/v1/patients/{pid}/").data["deleted"] is True


# ------------------------------------------------------------------------------------------- diagnosis
def test_new_patient_and_diagnosis_in_one_request(api):
    r = diagnose(api, new_patient={**NEW, "birth_year": 1990, "gender": "male", "relation": "spouse"})
    assert r.status_code == 201, r.data
    assert r.data["patient"]["full_name"] == "Amina" and r.data["patient"]["age_group"] == "adult"
    assert r.data["prefilled_answers"] == {"age_group": "adult", "pregnancy": "na"}
    assert r.data["book"]["recipe"]["status"] == "shown"
    p = Patient.objects.get(pk=r.data["patient"]["id"])
    assert p.account == api.user and p.consultations.count() == 1


def test_invalid_new_patient_creates_nothing(api):
    r = diagnose(api, new_patient={"full_name": "X"})
    assert r.status_code == 400 and r.data["error"] == "invalid_patient" and "new_patient.birth_year" in r.data["fields"]
    assert Patient.objects.filter(full_name="X").count() == 0 and not Consultation.objects.exists()


def test_invalid_answers_do_not_create_the_new_patient(api):
    r = diagnose(api, {"red_flags": ["none"]}, new_patient=NEW)
    assert r.status_code == 400 and r.data["error"] == "invalid_answers"
    assert not Patient.objects.filter(full_name="Amina").exists()


def test_patient_is_required_except_for_an_emergency(api):
    r = diagnose(api, REFERENCE)
    assert r.status_code == 400 and r.data["error"] == "patient_required"
    r = diagnose(api, {"red_flags": ["chest_pain"]})
    assert r.status_code == 201 and r.data["status"] == "emergency" and r.data["patient"] is None


def test_patient_info_wins_over_the_apps_age_answer(api):
    r = diagnose(api, {**SIGNS, "age_group": "child", "pregnancy": "na"}, patient_id=str(api.patient.id))
    assert r.status_code == 201 and r.data["prefilled_answers"]["age_group"] == "adult"
    assert r.data["book"]["recipe"]["status"] == "shown"


def test_adult_woman_is_still_asked_about_pregnancy(api):
    woman = make_patient(api.user, "Zainab", relation="spouse", gender="female", birth_year=1992)
    r = diagnose(api, patient_id=str(woman.id))
    assert r.status_code == 400 and r.data["fields"] == {"pregnancy": "required"}
    r = diagnose(api, {**SIGNS, "pregnancy": "yes"}, patient_id=str(woman.id))
    assert r.status_code == 201 and r.data["book"]["recipe"]["status"] == "withheld_vulnerable"


def test_kidney_liver_heart_disease_withholds_recipes_and_medicines_add_caution(api):
    sick = make_patient(api.user, "Abba", relation="parent", birth_year=1970, chronic_conditions=["kidney"],
                        medications="Amlodipine")
    r = diagnose(api, patient_id=str(sick.id))
    assert r.status_code == 201
    recipe = r.data["book"]["recipe"]
    assert recipe["status"] == "withheld_condition" and recipe["text"] is None and recipe["message"] == CONDITION_NO_RECIPE
    assert MEDICATION_ADVICE in r.data["advice"] and CONDITION_NO_RECIPE in r.data["text"]
    assert "سناکی" not in r.data["text"]


def test_each_diagnosis_keeps_the_info_of_its_time(api):
    pid = str(api.patient.id)
    first = diagnose(api, patient_id=pid).data
    api.patch(f"/api/v1/patients/{pid}/", {"weight_kg": 80, "chronic_conditions": ["diabetes"]}, format="json")
    second = diagnose(api, patient_id=pid).data
    assert api.get(f"/api/v1/consultations/{first['id']}/").data["patient"]["weight_kg"] is None
    assert second["patient"]["weight_kg"] == 80.0 and second["patient"]["chronic_conditions"] == ["diabetes"]
    hist = api.get("/api/v1/consultations/", {"patient": pid}).data
    assert hist["count"] == 2 and hist["results"][0]["patient"]["full_name"] == "Test Patient"
    other = make_patient(api.user, "Bhai", relation="sibling")
    assert api.get("/api/v1/consultations/", {"patient": str(other.id)}).data["count"] == 0
    assert api.get(f"/api/v1/patients/{pid}/").data["consultations"] == 2


# ------------------------------------------------------------------------------------------- re-diagnosis
def test_rediagnose_reuses_answers_and_current_info(api):
    pid = str(api.patient.id)
    first = diagnose(api, patient_id=pid).data
    api.patch(f"/api/v1/patients/{pid}/", {"chronic_conditions": ["liver"]}, format="json")
    r = api.post(f"/api/v1/consultations/{first['id']}/rediagnose/", {"answers": {"duration": "days"}}, format="json")
    assert r.status_code == 201, r.data
    assert r.data["rediagnosis_of"] == first["id"] and r.data["id"] != first["id"]
    assert r.data["book"]["recipe"]["status"] == "withheld_condition"          # the new info is used
    assert CONDITION_NO_RECIPE not in first["text"] and first["book"]["recipe"]["status"] == "shown"
    assert api.get(f"/api/v1/consultations/{first['id']}/").data["book"]["recipe"]["status"] == "shown"  # unchanged
    assert "پرانی" not in r.data["text"] or r.data["advice"] == []                    # duration is no longer chronic
    hist = api.get("/api/v1/consultations/").data["results"]
    assert [h["rediagnosis_of"] for h in hist] == [first["id"], None]


def test_rediagnose_without_changes_and_access_rules(api, app_key):
    first = diagnose(api, patient_id=str(api.patient.id)).data
    r = api.post(f"/api/v1/consultations/{first['id']}/rediagnose/", {}, format="json")
    assert r.status_code == 201 and r.data["assessment"]["primary_system"] == first["assessment"]["primary_system"]
    other = logged_in(app_key, make_user("+923009999999"))
    assert other.post(f"/api/v1/consultations/{first['id']}/rediagnose/", {}, format="json").status_code == 404
    bad = api.post(f"/api/v1/consultations/{first['id']}/rediagnose/", {"answers": {"heart": "maybe"}}, format="json")
    assert bad.status_code == 400 and "heart" in bad.data["fields"]


def test_rediagnose_an_emergency_without_patient_needs_one(api):
    em = diagnose(api, {"red_flags": ["breathing"]}).data
    r = api.post(f"/api/v1/consultations/{em['id']}/rediagnose/", {"answers": {**SIGNS, "red_flags": ["none"]}},
                 format="json")
    assert r.status_code == 400 and r.data["error"] == "patient_required"
    r = api.post(f"/api/v1/consultations/{em['id']}/rediagnose/",
                 {"answers": {**SIGNS, "red_flags": ["none"]}, "patient_id": str(api.patient.id)}, format="json")
    assert r.status_code == 201 and r.data["status"] == "completed" and r.data["patient"]["id"] == str(api.patient.id)


# ------------------------------------------------------------------------------------------- pulse
def test_pulse_upload_needs_a_patient_of_the_account(api, app_key):
    from django.core.files.uploadedfile import SimpleUploadedFile

    def up(client, **f):
        return client.post("/api/v1/pulse/analyses/", {"video": SimpleUploadedFile("p.mp4", b"x", "video/mp4"), **f},
                           format="multipart")
    r = up(api)
    assert r.status_code == 400 and r.data["error"] == "patient_required"
    other = logged_in(app_key, make_user("+923009999999"))
    assert up(api, patient=str(other.patient.id)).status_code == 400
    kid = make_patient(api.user, "Bachcha", relation="child", birth_year=2020)
    r = up(api, patient=str(kid.id))
    assert r.status_code == 201 and r.data["patient"] == str(kid.id) and r.data["account"] == api.user.pk
    assert api.get("/api/v1/pulse/analyses/", {"patient": str(kid.id)}).data["count"] == 1
    assert api.get("/api/v1/pulse/analyses/", {"patient": str(api.patient.id)}).data["count"] == 0
    c = diagnose(api, patient_id=str(api.patient.id)).data
    assert up(api, consultation=c["id"], patient=str(kid.id)).status_code == 400          # not the consultation's
    assert up(api, consultation=c["id"]).data["patient"] == str(api.patient.id)
