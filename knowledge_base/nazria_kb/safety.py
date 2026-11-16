"""Safety layer shared by every consultation engine (questionnaire now, LLM providers later).

* Red-flag triage: emergency symptoms stop the consultation and send the patient to a hospital.
* Hazard detection: remedies containing toxic minerals / poisonous plants (arsenic, mercury,
  copper sulphate, aconite, nux vomica, opium, lead ...) or calcined metals (کشتہ) are never
  shown to a patient; they are flagged for practitioner-only use.
* Vulnerable groups (children, pregnancy/breast-feeding, elderly) never receive recipes.
"""
from __future__ import annotations

import re

from .normalize import search_key

# name variants -> hazard code. Matched as whole words on normalised (diacritic-free) text.
HAZARDOUS_INGREDIENTS: dict[str, str] = {
    "سنکھیا": "arsenic", "سم الفار": "arsenic", "ہڑتال": "arsenic", "ہرتال": "arsenic",
    "مینسل": "arsenic", "منسل": "arsenic",
    "پارہ": "mercury", "پارا": "mercury", "سیماب": "mercury", "زیبق": "mercury", "شنگرف": "mercury",
    "رس کپور": "mercury", "رسکپور": "mercury", "دار چکنا": "mercury", "دارچکنا": "mercury",
    "نیلا طوطیہ": "copper_sulphate", "نیلا تھوتھا": "copper_sulphate", "توتیا": "copper_sulphate",
    "سرب": "lead", "مردار سنگ": "lead", "مرداسنگ": "lead", "مردارسنگ": "lead", "سیندور": "lead", "سفیدہ کاشغری": "lead",
    "بچھناگ": "aconite", "میٹھا تیلیا": "aconite",
    "کچلہ": "strychnine", "کچلا": "strychnine", "اذاراقی": "strychnine",
    "دھتورا": "datura", "دھتورہ": "datura", "دھتورے": "datura", "تخم دھتورا": "datura",
    "افیون": "opium", "تریاک": "opium",
    "بھنگ": "cannabis", "چرس": "cannabis",
    "اجوائن خراسانی": "henbane", "بذر البنج": "henbane",
    "جمال گوٹہ": "croton", "جمال گھوٹہ": "croton", "حب السلاطین": "croton",
    "کنیر": "oleander", "شوکران": "hemlock",
}
KUSHTA_RE = re.compile(r"(?:^|\s)(?:کشتہ|کشتۂ|کشتے|کشتوں|کشتہء)(?:\s|$)|کشتہ جات|کشتہجات")
_HAZ_RE = re.compile(r"(?:^|\s)(" + "|".join(sorted(map(re.escape, HAZARDOUS_INGREDIENTS), key=len, reverse=True)) + r")(?=\s|$)")


def hazard_flags(text: str) -> list[str]:
    """Hazard codes found in a recipe/turn text, e.g. ['arsenic', 'kushta']."""
    if not text:
        return []
    key = search_key(text)
    flags = {HAZARDOUS_INGREDIENTS[m.group(1)] for m in _HAZ_RE.finditer(key)}
    if KUSHTA_RE.search(key):
        flags.add("kushta")
    return sorted(flags)


# --------------------------------------------------------------------------- red flags
RED_FLAGS: list[tuple[str, str]] = [
    ("chest_pain", "سینے میں شدید درد یا دباؤ"),
    ("breathing", "سانس لینے میں شدید دشواری"),
    ("unconscious", "بے ہوشی، دورہ (جھٹکے) یا شدید غنودگی"),
    ("stroke", "چہرہ ٹیڑھا ہونا، بازو/ٹانگ اچانک کمزور ہونا یا بولنے میں دقت"),
    ("bleeding", "خون کی قے، پاخانے میں کالا یا تازہ خون، یا شدید خون بہنا"),
    ("fever_neck", "تیز بخار کے ساتھ گردن اکڑ جانا یا جسم پر سرخ دھبے"),
    ("pregnancy_emergency", "حمل کے دوران خون آنا یا پیٹ میں شدید درد"),
    ("child_fever", "پانچ سال سے کم عمر بچے میں تیز بخار یا پانی کی شدید کمی"),
    ("self_harm", "خود کو نقصان پہنچانے کے خیالات"),
]

EMERGENCY_MESSAGE = (
    "آپ نے جو علامت بتائی ہے وہ ہنگامی نوعیت کی ہو سکتی ہے۔ برائے مہربانی فوراً قریبی ہسپتال کی ایمرجنسی "
    "جائیں یا ایمبولینس کو کال کریں۔ اس حالت میں گھر پر کوئی دیسی دوا استعمال نہ کریں۔"
)
SELF_HARM_MESSAGE = (
    "آپ اکیلے نہیں ہیں۔ براہ کرم ابھی کسی قریبی عزیز سے بات کریں اور فوراً قریبی ہسپتال یا ہنگامی سروس سے رابطہ کریں۔"
)
DISCLAIMER = (
    "یہ سوالنامہ کتاب «کلیات تحقیقات صابر ملتانی» کی بنیاد پر صرف رہنمائی کے لیے ہے، یہ تشخیص نہیں ہے۔ "
    "حتمی تشخیص اور علاج کے لیے کسی مستند حکیم سے نبض اور قارورہ کا معائنہ ضرور کروائیں۔"
)
BOOK_DISCLAIMER_LLM = (
    "یہ جواب کتاب «کلیات تحقیقات صابر ملتانی» کے اقتباسات کی بنیاد پر صرف رہنمائی کے لیے ہے، یہ تشخیص نہیں ہے۔ "
    "حتمی تشخیص اور علاج کے لیے کسی مستند حکیم سے نبض اور قارورہ کا معائنہ ضرور کروائیں۔"
)
PRACTITIONER_ONLY = (
    "اس مرض کے لیے کتاب میں جو نسخہ درج ہے اس میں ایسے اجزاء ({items}) شامل ہیں جو غلط مقدار میں زہریلے "
    "ہو سکتے ہیں، اس لیے یہ نسخہ یہاں نہیں دکھایا جا رہا۔ یہ صرف مستند حکیم کی نگرانی میں استعمال ہو سکتا ہے۔"
)
VULNERABLE_NO_RECIPE = (
    "بچوں، حاملہ یا دودھ پلانے والی خواتین اور بزرگوں کے لیے یہاں کوئی نسخہ تجویز نہیں کیا جاتا۔ "
    "براہ کرم براہ راست کسی مستند حکیم یا ڈاکٹر سے رجوع کریں۔"
)
HAZARD_NAMES_UR = {
    "arsenic": "سنکھیا/سم الفار", "mercury": "پارہ/شنگرف", "copper_sulphate": "نیلا طوطیہ", "lead": "سرب",
    "aconite": "بچھناگ", "strychnine": "کچلہ", "datura": "دھتورا", "opium": "افیون", "cannabis": "بھنگ",
    "henbane": "اجوائن خراسانی", "croton": "جمال گوٹہ", "kushta": "کشتہ جات",
    "oleander": "کنیر", "hemlock": "شوکران",
}

# --------------------------------------------------------------------------- free-text red flags
# Patterns are matched on search_key()-normalised text (no diacritics/punctuation). They are
# deliberately conservative: a false alarm only sends the patient to a hospital, a miss could harm.
# Codes reuse RED_FLAGS where they overlap; extra codes cover free-text-only emergencies.
_RF_TEXT: list[tuple[str, str]] = [
    ("chest_pain", r"سین[ےہ] (?:میں )?(?:شدید |سخت |بہت )?(?:درد|دباؤ)|دل کا دورہ|chest pain|heart attack"),
    ("breathing", r"سانس (?:لینے )?(?:میں )?(?:شدید |سخت |بہت )?(?:دشواری|مشکل|رک|بند|نہیں آ|اکھڑ)|دم گھٹ|can.?t breathe"),
    ("unconscious", r"بے ?ہوش|دورہ پڑ|دورے پڑ|جھٹکے لگ|unconscious|seizure"),
    ("stroke", r"چہرہ ٹیڑھا|منہ ٹیڑھا|اچانک (?:\S+ ){0,3}(?:فالج|لقوہ|کمزور|سن ہو|بول نہیں|بولنے میں)|stroke"),
    ("bleeding", r"خون کی (?:قے|الٹی)|(?:قے|الٹی) میں خون|پاخان[ےہ] میں (?:کالا|خون)|کالا پاخانہ|"
                 r"کھانسی (?:میں|کے ساتھ) خون|خون (?:تھوک|بہہ رہا|بہ رہا|نہیں رک)|vomiting blood"),
    ("fever_neck", r"گردن (?:اکڑ|سخت|میں اکڑاؤ)"),
    ("pregnancy_emergency", r"حمل (?:\S+ ){0,6}(?:خون آ|شدید درد|پانی آ)"),
    ("child_fever", r"(?:نوزائیدہ|شیر خوار|چھوٹے بچے|بچے) (?:\S+ ){0,4}(?:تیز بخار|پانی کی (?:شدید )?کمی|بے ہوش)"),
    ("self_harm", r"خود ?کشی|خود کو (?:نقصان|مار|ختم)|مرنا چاہت|جینا نہیں چاہت|زندگی ختم کر|suicid|kill myself"),
    ("poisoning", r"زہر (?:کھا|پی|نگل)|زہریل[یا] (?:چیز|دوا) (?:کھا|پی)|(?:دوا|گولیاں) زیادہ (?:مقدار میں )?(?:کھا|لے) ل|overdose"),
    ("severe_headache", r"اچانک (?:\S+ ){0,2}(?:شدید|ناقابل برداشت) سر (?:میں )?درد|زندگی کا سب سے شدید سر درد"),
    ("allergy_swelling", r"(?:چہر[ےہ]|ہونٹ|زبان|گل[ےا]) (?:\S+ ){0,2}(?:سوج گ|سوجن)(?:\S* ){0,4}(?:سانس)|گلا بند ہو"),
    ("severe_abdominal_pain", r"پیٹ (?:میں )?(?:شدید|ناقابل برداشت|سخت) درد"),
]
_RF_TEXT_RE = [(code, re.compile(pat, re.IGNORECASE)) for code, pat in _RF_TEXT]


def detect_red_flags(text: str) -> list[str]:
    """Emergency codes found in a free-text patient message (empty list = none)."""
    if not text:
        return []
    key = search_key(text)
    return [code for code, rx in _RF_TEXT_RE if rx.search(key)]


def emergency_message(codes: list[str]) -> str:
    return SELF_HARM_MESSAGE if "self_harm" in codes else EMERGENCY_MESSAGE


# --------------------------------------------------------------------------- output guards
# A paragraph "looks like a recipe" when it names a recipe or gives ingredient quantities.
RECIPE_LIKE_RE = re.compile(
    r"نسخہ|اجزاء|اجزا |ہوالشافی|ھوالشافی|ترکیب تیاری|طریقہ تیاری|"
    r"\d+\s*(?:تولہ|تولے|ماشہ|ماشے|رتی|گرام|ملی|چمچ|چمچہ|عدد|حصہ|حصے|سیر|چھٹانک)")


def looks_like_recipe(text: str) -> bool:
    return bool(text) and bool(RECIPE_LIKE_RE.search(search_key(text).replace("۔", " ")) or
                               RECIPE_LIKE_RE.search(text))


def safe_for_patient(text: str, vulnerable: bool) -> bool:
    """True if a book excerpt may be shown: no hazardous ingredient, and no recipe for vulnerable groups."""
    return not hazard_flags(text) and not (vulnerable and looks_like_recipe(text))


def guard_answer(text: str, vulnerable: bool) -> tuple[str, dict]:
    """Post-check a generated answer paragraph by paragraph.

    * a paragraph with a hazardous ingredient is removed and replaced by the practitioner-only notice
    * for vulnerable patients any recipe-like paragraph is removed and the no-recipe notice added
    Returns (safe_text, {"hazards": [...], "removed_paragraphs": n, "vulnerable_recipe_removed": bool}).
    """
    paras = [p for p in re.split(r"\n\s*\n|\n", text or "") if p.strip()]
    kept, hazards, removed, vuln_removed = [], set(), 0, False
    for p in paras:
        h = hazard_flags(p)
        if h:
            hazards.update(h)
            removed += 1
            continue
        if vulnerable and looks_like_recipe(p):
            vuln_removed = True
            removed += 1
            continue
        kept.append(p)
    if hazards:
        kept.append(PRACTITIONER_ONLY.format(items="، ".join(HAZARD_NAMES_UR.get(x, x) for x in sorted(hazards))))
    if vuln_removed:
        kept.append(VULNERABLE_NO_RECIPE)
    return "\n".join(kept), {"hazards": sorted(hazards), "removed_paragraphs": removed,
                             "vulnerable_recipe_removed": vuln_removed}
