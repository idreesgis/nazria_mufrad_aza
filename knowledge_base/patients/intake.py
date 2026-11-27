"""The patient's general info the app asks before the first diagnosis of a new patient (GET /patients/intake-form/),
and the questionnaire answers the server fills in from it for every diagnosis of that patient."""
from __future__ import annotations

import hashlib
import json
from datetime import date

from .models import CONDITIONS, Patient

CONDITION_LABELS = {"diabetes": "ذیابیطس (شوگر)", "hypertension": "بلند فشار خون", "heart": "دل کی بیماری",
                    "kidney": "گردوں کی بیماری", "liver": "جگر کی بیماری", "asthma": "دمہ", "thyroid": "تھائیرائیڈ",
                    "epilepsy": "مرگی", "other": "کوئی اور (نیچے لکھیں)"}


def _opts(pairs):
    return [{"key": k, "label": v} for k, v in pairs]


def intake_fields() -> list[dict]:
    year = date.today().year
    return [
        {"id": "full_name", "kind": "text", "required": True, "label": "مریض کا نام", "max_length": 150},
        {"id": "relation", "kind": "single", "required": True, "label": "مریض آپ کا کون ہے؟", "options": _opts([
            ("self", "میں خود"), ("spouse", "شوہر / بیوی"), ("child", "بیٹا / بیٹی"), ("parent", "والد / والدہ"),
            ("sibling", "بھائی / بہن"), ("relative", "کوئی اور رشتہ دار"), ("other", "کوئی اور")])},
        {"id": "gender", "kind": "single", "required": True, "label": "جنس",
         "options": _opts([("male", "مرد"), ("female", "عورت"), ("other", "دیگر")])},
        {"id": "birth_year", "kind": "integer", "required": True, "label": "پیدائش کا سال (مثلاً 1985)",
         "min": 1900, "max": year,
         "help": "عمر سے یہ طے ہوتا ہے کہ بچوں اور بزرگوں کے لیے نسخہ نہ دکھایا جائے"},
        {"id": "weight_kg", "kind": "number", "required": False, "label": "وزن (کلوگرام)", "min": 1, "max": 400},
        {"id": "height_cm", "kind": "number", "required": False, "label": "قد (سینٹی میٹر)", "min": 30, "max": 250},
        {"id": "chronic_conditions", "kind": "multi", "required": False,
         "label": "کیا مریض کو پہلے سے ان میں سے کوئی بیماری ہے؟ (جو لاگو ہوں)",
         "options": _opts([(c, CONDITION_LABELS[c]) for c in CONDITIONS]),
         "help": "گردے، جگر یا دل کی بیماری میں کوئی نسخہ نہیں دکھایا جاتا"},
        {"id": "conditions_other", "kind": "text", "required": False, "label": "کوئی اور بیماری", "max_length": 300},
        {"id": "allergies", "kind": "text", "required": False, "label": "کسی دوا یا چیز سے الرجی؟", "max_length": 300},
        {"id": "medications", "kind": "text", "required": False, "label": "اس وقت کون سی دوائیں لے رہے ہیں؟",
         "max_length": 500},
        {"id": "consent", "kind": "boolean", "required": True,
         "label": "میں تصدیق کرتا/کرتی ہوں کہ مجھے اس مریض کی معلومات محفوظ کرنے کی اجازت ہے "
                  "(بچے کی صورت میں میں سرپرست ہوں)۔"},
    ]


def intake_payload() -> dict:
    fields = intake_fields()
    version = hashlib.sha256(json.dumps(fields, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:16]
    return {"version": version, "fields": fields,
            "prefills": {"age_group": "from birth_year", "pregnancy": '"na" for male patients and children'}}


def answers_from_patient(patient: Patient) -> dict:
    """Questionnaire answers the patient's info already gives (the app need not ask these again)."""
    out: dict[str, str] = {}
    if patient.age_group:
        out["age_group"] = patient.age_group
    if patient.gender == "male" or patient.age_group == "child":
        out["pregnancy"] = "na"
    return out


def prefilled_question_ids(patient: Patient) -> list[str]:
    return sorted(answers_from_patient(patient))
