"""Three languages: every fixed patient-facing Urdu string has an English and an Arabic translation, and the safety
checks work in all three."""
import re

import pytest

from nazria_kb import diet, safety
from nazria_kb.engine import CHRONIC_ADVICE
from nazria_kb.i18n import (CATALOG, complaint_urdu_terms, from_accept_language, normalize_lang, tehreek_name, tr)
from nazria_kb.llm_engine import EXTERNAL_NOTICE, NOT_COVERED_MESSAGE
from nazria_kb.questionnaire import DEFAULT_QUESTIONS, SYSTEM_ORGANS, TEHREEK_MIZAJ

ARABIC = re.compile(r"[؀-ۿ]")
URDU_ONLY = re.compile(r"[ٹڈڑںھہےۓ]")


def patient_strings():
    out = []
    for q in DEFAULT_QUESTIONS:
        out += [q.text] + [o.label for o in q.options]
    out += [label for _, label in safety.RED_FLAGS] + list(safety.TEXT_FLAG_LABELS.values())
    out += list(safety.HAZARD_NAMES_UR.values()) + list(SYSTEM_ORGANS.values()) + list(TEHREEK_MIZAJ.values())
    out += [safety.EMERGENCY_MESSAGE, safety.SELF_HARM_MESSAGE, safety.DISCLAIMER, safety.BOOK_DISCLAIMER_LLM,
            safety.PRACTITIONER_ONLY, safety.VULNERABLE_NO_RECIPE, safety.CONDITION_NO_RECIPE,
            safety.MEDICATION_ADVICE, CHRONIC_ADVICE, NOT_COVERED_MESSAGE, EXTERNAL_NOTICE]
    for g in diet.FOOD_GROUPS.values():
        for k in ("breakfast", "lunch", "dinner", "fruits", "dry_fruits"):
            out += g[k]
        out += [g["qehwa"]["name"], g["qehwa"]["how"]] + g["qehwa"]["ingredients"]
    out += diet.GENERAL_RULES + list(diet.CHOOSE_IF.values()) + [diet.NO_DRY_FRUITS, diet.NO_FRUITS]
    p = diet.plan_for("عضلاتی غدی", ["diabetes", "hypertension", "kidney"], caution=True, vulnerable=True)
    out += p["notes"]
    return out


def test_every_patient_string_is_translated():
    missing = sorted({s for s in patient_strings() if s not in CATALOG})
    assert missing == []


@pytest.mark.parametrize("ur", sorted({s for s in CATALOG}))
def test_translations_are_in_the_right_script_and_keep_placeholders(ur):
    en, ar = CATALOG[ur]
    assert en and ar and not ARABIC.search(en.replace("«", "").replace("»", "")), en
    assert ARABIC.search(ar) and not URDU_ONLY.search(ar), ar
    for ph in re.findall(r"\{\w+\}", ur):
        assert ph in en and ph in ar


def test_language_codes():
    assert normalize_lang("en-US") == "en" and normalize_lang("AR_sa") == "ar" and normalize_lang("fr") is None
    assert from_accept_language("fr-FR,ar;q=0.9,en;q=0.8") == "ar" and from_accept_language("de") is None
    assert tr("ہاں", "en") == "Yes" and tr("ہاں", "ar") == "نعم" and tr("ہاں", "ur") == "ہاں"
    assert tr("کوئی نامعلوم جملہ", "en") == "کوئی نامعلوم جملہ"           # untranslated: Urdu
    assert tehreek_name("عضلاتی غدی", "en") == "Muscular-Glandular" and tehreek_name("غدی اعصابی", "ar") == "غدّي عصبي"


@pytest.mark.parametrize("text,codes", [
    ("I cannot breathe", ["breathing"]), ("severe chest pain since an hour", ["chest_pain"]),
    ("he fainted and had a seizure", ["unconscious"]), ("vomiting blood", ["bleeding"]),
    ("I want to kill myself", ["self_harm"]), ("my baby has a high fever", ["child_fever"]),
    ("ألم شديد في الصدر", ["chest_pain"]), ("لا أستطيع التنفس", ["breathing"]), ("فقدان الوعي", ["unconscious"]),
    ("تقيؤ الدم", ["bleeding"]), ("أفكر في الانتحار", ["self_harm"]), ("أنا حامل وعندي نزيف", ["pregnancy_emergency"]),
    ("سینے میں شدید درد", ["chest_pain"]),
    ("chronic constipation for years", []), ("سعال مزمن مع بلغم", []), ("I fit in well at work", []),
])
def test_emergencies_are_found_in_three_languages(text, codes):
    assert safety.detect_red_flags(text) == codes


def test_hazards_and_recipes_in_english_and_arabic():
    assert safety.hazard_flags("Take kushta of arsenic with honey") == ["arsenic", "kushta"]
    assert safety.hazard_flags("الزئبق والأفيون") == ["mercury", "opium"] and safety.hazard_flags("senna leaves") == []
    assert safety.looks_like_recipe("Recipe: 2 g senna") and safety.looks_like_recipe("الوصفة: 3 غرام")
    text, info = safety.guard_answer("Constipation is chronic.\nRecipe: arsenic 1 g", False, "en")
    assert "arsenic 1 g" not in text and "qualified practitioner" in text and info["hazards"] == ["arsenic"]


def test_english_and_arabic_complaints_find_urdu_topics():
    assert complaint_urdu_terms("chronic constipation") == "قبض"
    assert complaint_urdu_terms("سعال وحمى") == "کھانسی بخار"
    assert complaint_urdu_terms("پرانی قبض") == ""                        # already Urdu
