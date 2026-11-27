"""The patient's general info the app asks before the first diagnosis of a new patient (GET /patients/intake-form/),
and the questionnaire answers the server fills in from it for every diagnosis of that patient."""
from __future__ import annotations

import hashlib
import json
from datetime import date

from .models import CONDITIONS, Patient

# (ur, en, ar)
CONDITION_LABELS = {
    "diabetes": ("ذیابیطس (شوگر)", "Diabetes", "السكري"), "hypertension": ("بلند فشار خون", "High blood pressure",
                                                                      "ارتفاع ضغط الدم"),
    "heart": ("دل کی بیماری", "Heart disease", "مرض القلب"), "kidney": ("گردوں کی بیماری", "Kidney disease", "مرض الكلى"),
    "liver": ("جگر کی بیماری", "Liver disease", "مرض الكبد"), "asthma": ("دمہ", "Asthma", "الربو"),
    "thyroid": ("تھائیرائیڈ", "Thyroid disease", "الغدة الدرقية"), "epilepsy": ("مرگی", "Epilepsy", "الصرع"),
    "other": ("کوئی اور (نیچے لکھیں)", "Other (write below)", "أخرى (اكتبها أدناه)"),
}
_T = {
    "full_name": ("مریض کا نام", "Patient's name", "اسم المريض"),
    "relation": ("مریض آپ کا کون ہے؟", "Who is the patient to you?", "ما صلة المريض بك؟"),
    "gender": ("جنس", "Gender", "الجنس"),
    "birth_year": ("پیدائش کا سال (مثلاً 1985)", "Year of birth (e.g. 1985)", "سنة الميلاد (مثلًا 1985)"),
    "birth_year.help": ("عمر سے یہ طے ہوتا ہے کہ بچوں اور بزرگوں کے لیے نسخہ نہ دکھایا جائے",
                        "The age decides that no recipe is shown for children and the elderly",
                        "يُحدَّد بالعمر ألّا تُعرض وصفة للأطفال وكبار السن"),
    "weight_kg": ("وزن (کلوگرام)", "Weight (kg)", "الوزن (كغ)"),
    "height_cm": ("قد (سینٹی میٹر)", "Height (cm)", "الطول (سم)"),
    "chronic_conditions": ("کیا مریض کو پہلے سے ان میں سے کوئی بیماری ہے؟ (جو لاگو ہوں)",
                           "Does the patient already have any of these diseases? (choose all that apply)",
                           "هل يعاني المريض من أيٍّ من هذه الأمراض؟ (اختر كل ما ينطبق)"),
    "chronic_conditions.help": ("گردے، جگر یا دل کی بیماری میں کوئی نسخہ نہیں دکھایا جاتا",
                                "With kidney, liver or heart disease no recipe is shown",
                                "مع مرض الكلى أو الكبد أو القلب لا تُعرض أي وصفة"),
    "conditions_other": ("کوئی اور بیماری", "Any other disease", "أي مرض آخر"),
    "allergies": ("کسی دوا یا چیز سے الرجی؟", "Allergic to any medicine or thing?", "حساسية من أي دواء أو مادة؟"),
    "medications": ("اس وقت کون سی دوائیں لے رہے ہیں؟", "Which medicines are being taken now?",
                    "ما الأدوية التي يتناولها الآن؟"),
    "consent": ("میں تصدیق کرتا/کرتی ہوں کہ مجھے اس مریض کی معلومات محفوظ کرنے کی اجازت ہے "
                "(بچے کی صورت میں میں سرپرست ہوں)۔",
                "I confirm that I may record this patient's information (for a child, I am the guardian).",
                "أؤكد أنه يحق لي حفظ معلومات هذا المريض (وفي حالة الطفل فأنا وليّ أمره)."),
}
_RELATIONS = [("self", ("میں خود", "Myself", "أنا")), ("spouse", ("شوہر / بیوی", "Husband / wife", "الزوج / الزوجة")),
              ("child", ("بیٹا / بیٹی", "Son / daughter", "الابن / الابنة")),
              ("parent", ("والد / والدہ", "Father / mother", "الأب / الأم")),
              ("sibling", ("بھائی / بہن", "Brother / sister", "الأخ / الأخت")),
              ("relative", ("کوئی اور رشتہ دار", "Another relative", "قريب آخر")),
              ("other", ("کوئی اور", "Someone else", "شخص آخر"))]
_GENDERS = [("male", ("مرد", "Male", "ذكر")), ("female", ("عورت", "Female", "أنثى")), ("other", ("دیگر", "Other", "آخر"))]
_I = {"ur": 0, "en": 1, "ar": 2}


def _opts(pairs, lang):
    return [{"key": k, "label": v[_I[lang]]} for k, v in pairs]


def intake_fields(lang: str = "ur") -> list[dict]:
    year = date.today().year
    t = {k: v[_I[lang]] for k, v in _T.items()}
    return [
        {"id": "full_name", "kind": "text", "required": True, "label": t["full_name"], "max_length": 150},
        {"id": "relation", "kind": "single", "required": True, "label": t["relation"], "options": _opts(_RELATIONS, lang)},
        {"id": "gender", "kind": "single", "required": True, "label": t["gender"], "options": _opts(_GENDERS, lang)},
        {"id": "birth_year", "kind": "integer", "required": True, "label": t["birth_year"], "min": 1900, "max": year,
         "help": t["birth_year.help"]},
        {"id": "weight_kg", "kind": "number", "required": False, "label": t["weight_kg"], "min": 1, "max": 400},
        {"id": "height_cm", "kind": "number", "required": False, "label": t["height_cm"], "min": 30, "max": 250},
        {"id": "chronic_conditions", "kind": "multi", "required": False, "label": t["chronic_conditions"],
         "options": _opts([(c, CONDITION_LABELS[c]) for c in CONDITIONS], lang), "help": t["chronic_conditions.help"]},
        {"id": "conditions_other", "kind": "text", "required": False, "label": t["conditions_other"], "max_length": 300},
        {"id": "allergies", "kind": "text", "required": False, "label": t["allergies"], "max_length": 300},
        {"id": "medications", "kind": "text", "required": False, "label": t["medications"], "max_length": 500},
        {"id": "consent", "kind": "boolean", "required": True, "label": t["consent"]},
    ]


def intake_payload(lang: str = "ur") -> dict:
    from nazria_kb.i18n import DIRECTION
    fields = intake_fields(lang)
    version = hashlib.sha256(json.dumps(fields, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:16]
    return {"version": version, "language": lang, "direction": DIRECTION[lang], "fields": fields,
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
