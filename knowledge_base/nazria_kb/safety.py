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
    "جمال گوٹہ": "croton", "جمال گھوٹہ": "croton", "جمال گوٹ": "croton", "جمالہ گوند": "croton", "حب السلاطین": "croton",
    "کنیر": "oleander", "شوکران": "hemlock",
}
KUSHTA_RE = re.compile(r"(?:^|\s)(?:کشتہ|کشتۂ|کشتے|کشتوں|کشتہء)(?:\s|$)|کشتہ جات|کشتہجات")
_HAZ_RE = re.compile(r"(?:^|\s)(" + "|".join(sorted(map(re.escape, HAZARDOUS_INGREDIENTS), key=len, reverse=True)) + r")(?=\s|$)")


# English and Arabic names (AI explanations in those languages), matched on ml_key() text
HAZARDOUS_INGREDIENTS_ML: dict[str, str] = {
    "arsenic": "arsenic", "زرنيخ": "arsenic", "الزرنيخ": "arsenic", "mercury": "mercury", "cinnabar": "mercury",
    "quicksilver": "mercury", "زئبق": "mercury", "الزئبق": "mercury", "زنجفر": "mercury", "الزنجفر": "mercury",
    "copper sulphate": "copper_sulphate", "copper sulfate": "copper_sulphate", "blue vitriol": "copper_sulphate",
    "كبريتات النحاس": "copper_sulphate", "lead oxide": "lead", "litharge": "lead", "red lead": "lead",
    "مرتك": "lead", "سيلقون": "lead", "aconite": "aconite", "aconitum": "aconite", "خانق الذئب": "aconite",
    "nux vomica": "strychnine", "strychnine": "strychnine", "جوز القيء": "strychnine", "جوز القي": "strychnine",
    "ستركنين": "strychnine", "datura": "datura", "thorn apple": "datura", "داتوره": "datura", "الداتوره": "datura",
    "opium": "opium", "افيون": "opium", "الافيون": "opium", "cannabis": "cannabis", "hashish": "cannabis",
    "bhang": "cannabis", "حشيش": "cannabis", "الحشيش": "cannabis", "قنب": "cannabis", "القنب": "cannabis",
    "henbane": "henbane", "بنج": "henbane", "البنج": "henbane", "croton": "croton", "حب الملوك": "croton",
    "oleander": "oleander", "دفلي": "oleander", "الدفلي": "oleander", "hemlock": "hemlock", "شوكران": "hemlock",
    "الشوكران": "hemlock", "kushta": "kushta", "calcined metal": "kushta", "calx": "kushta", "كشته": "kushta",
}
# Arabic attaches و ف ب ل ك (and, so, with, for, like) and ال (the) to the word: «والأفيون» is «and the opium»
_HAZ_ML_RE = re.compile(r"(?<!\w)(?:[وفبلك]?(?:ال)?)(" + "|".join(sorted(map(re.escape, HAZARDOUS_INGREDIENTS_ML), key=len,
                                                                      reverse=True)) + r")(?!\w)")


def hazard_flags(text: str) -> list[str]:
    """Hazard codes found in a recipe/turn text (Urdu, English or Arabic), e.g. ['arsenic', 'kushta']."""
    if not text:
        return []
    key = search_key(text)
    flags = {HAZARDOUS_INGREDIENTS[m.group(1)] for m in _HAZ_RE.finditer(key)}
    if KUSHTA_RE.search(key):
        flags.add("kushta")
    flags |= {HAZARDOUS_INGREDIENTS_ML[m.group(1)] for m in _HAZ_ML_RE.finditer(ml_key(text))}
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
# Patient-facing texts name no book, author, page or "حکیم": the patient is referred to a qualified practitioner
# (مستند معالج). Book volume/page references stay in the question bank for review tools only.
DISCLAIMER = (
    "یہ نتیجہ نظریہ مفرد اعضاء کے مطابق آپ کی بتائی ہوئی علامات کی بنیاد پر صرف رہنمائی کے لیے ہے، یہ تشخیص نہیں ہے۔ "
    "حتمی تشخیص اور علاج کے لیے کسی مستند معالج سے نبض اور قارورہ کا معائنہ ضرور کروائیں۔"
)
BOOK_DISCLAIMER_LLM = (
    "یہ وضاحت نظریہ مفرد اعضاء کی روشنی میں صرف رہنمائی کے لیے ہے، یہ تشخیص نہیں ہے۔ "
    "حتمی تشخیص اور علاج کے لیے کسی مستند معالج سے نبض اور قارورہ کا معائنہ ضرور کروائیں۔"
)
PRACTITIONER_ONLY = (
    "اس تکلیف کے نسخے میں ایسے اجزاء ({items}) شامل ہیں جو غلط مقدار میں زہریلے "
    "ہو سکتے ہیں، اس لیے یہ نسخہ یہاں نہیں دکھایا جا رہا۔ یہ صرف مستند معالج کی نگرانی میں استعمال ہو سکتا ہے۔"
)
VULNERABLE_NO_RECIPE = (
    "بچوں، حاملہ یا دودھ پلانے والی خواتین اور بزرگوں کے لیے یہاں کوئی نسخہ تجویز نہیں کیا جاتا۔ "
    "براہ کرم براہ راست کسی مستند معالج یا ڈاکٹر سے رجوع کریں۔"
)
# Patient health conditions (from the patient's general info) for which no book recipe is shown: herbal recipes can
# harm a weak kidney, liver or heart, or interact with the medicines these patients take. For a practitioner to review.
RECIPE_RISK_CONDITIONS = frozenset({"kidney", "liver", "heart"})
CONDITION_NO_RECIPE = (
    "مریض کو پہلے سے گردے، جگر یا دل کی بیماری ہے، اس لیے یہاں کوئی نسخہ تجویز نہیں کیا جاتا۔ "
    "براہ کرم اپنے معالج سے براہ راست رجوع کریں۔"
)
MEDICATION_ADVICE = (
    "مریض پہلے سے دوائیں لے رہا ہے، یا اسے کسی چیز سے الرجی ہے: کوئی بھی دیسی نسخہ شروع کرنے سے پہلے "
    "اپنے معالج سے ضرور مشورہ کریں، کیونکہ دوائیں آپس میں اثر کر سکتی ہیں۔"
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

# English and Arabic, matched on ml_key() text (lower case, Arabic letter variants and diacritics unified).
_RF_TEXT_ML: list[tuple[str, str]] = [
    ("chest_pain", r"chest (?:\w+ ){0,2}(?:pain|pressure|tightness)|pain in (?:my |the )?chest|heart attack|"
                   r"(?:الم|وجع|ضغط) (?:\S+ ){0,2}(?:في )?(?:ال)?صدر|نوبه قلبيه|ذبحه صدريه"),
    ("breathing", r"(?:can ?not|can.?t|cannot|unable to|hard to|difficult(?:y)?(?: to)?|trouble|struggling to) ?(?:\w+ )?breath|"
                  r"short(?:ness)? of breath|not breathing|choking|"
                  r"(?:صعوبه|ضيق) (?:\S+ ){0,1}(?:في )?التنفس|لا (?:استطيع|اقدر) (?:ان )?(?:اتنفس|التنفس)|اختناق"),
    ("unconscious", r"unconscious|faint(?:ed|ing)|passed out|seizure|convuls|(?:having|had|has) (?:a )?fits?\b|"
                    r"(?:فقد|فقدان) (?:ال)?وعي|اغماء|اغمي|غيبوبه|نوبه صرع|تشنج"),
    ("stroke", r"stroke|face (?:is )?droop|sudden(?:ly)? (?:\w+ ){0,3}(?:weak|numb|paraly|can.?t speak|slurr)|"
               r"سكته دماغيه|جلطه دماغيه|تدلي الوجه|شلل مفاجئ|ضعف مفاجئ|صعوبه (?:مفاجئه )?في الكلام"),
    ("bleeding", r"vomit(?:ing|ed)? (?:\w+ )?blood|blood in (?:my |the )?(?:stool|vomit)|black stool|coughing (?:up )?blood|"
                 r"bleeding (?:heavily|a lot|won.?t stop)|heavy bleeding|"
                 r"(?:تقيؤ|قيء|استفراغ) (?:ال)?دم|دم في (?:ال)?براز|براز اسود|(?:سعال|كحه) (?:مع )?دم|نزيف (?:شديد|حاد|لا يتوقف)"),
    ("fever_neck", r"stiff neck|neck (?:is )?stiff|تيبس (?:في )?الرقبه|تصلب الرقبه"),
    ("pregnancy_emergency", r"pregnan\w* (?:\w+ ){0,6}(?:bleed|severe pain)|(?:bleed\w*|severe pain) (?:\w+ ){0,4}pregnan|"
                            r"حامل (?:\S+ ){0,4}(?:نزيف|ألم شديد|الم شديد)|نزيف (?:\S+ ){0,3}(?:ال)?حمل"),
    ("child_fever", r"(?:baby|infant|newborn|toddler|child) (?:\w+ ){0,4}(?:high fever|dehydrat|unconscious)|"
                    r"(?:رضيع|مولود|طفل\S*) (?:\S+ ){0,4}(?:حمي شديده|حرار\S* عاليه|حمي عاليه|جفاف)"),
    ("self_harm", r"suicid|kill myself|end my life|want to die|harm myself|hurt myself|"
                  r"انتحار|اقتل نفسي|انهي حياتي|اريد ان اموت|اذيه نفسي|اؤذي نفسي"),
    ("poisoning", r"poison|overdose|swallowed (?:\w+ ){0,3}(?:pills|tablets|chemical)|"
                  r"تسمم|سم |جرعه زائده|ابتلع (?:\S+ ){0,3}(?:حبوب|اقراص)"),
    ("severe_headache", r"(?:sudden|worst) (?:\w+ ){0,3}headache|thunderclap|صداع (?:مفاجئ|شديد جدا)|اسوا صداع"),
    ("allergy_swelling", r"(?:face|lips?|tongue|throat) (?:\w+ ){0,2}swell(?:ing|ed)?|anaphyla|"
                         r"تورم (?:ال)?(?:وجه|شفتين|شفه|لسان|حلق)|حساسيه شديده"),
    ("severe_abdominal_pain", r"(?:severe|unbearable|intense) (?:\w+ ){0,2}(?:abdominal|stomach|belly) pain|"
                              r"الم (?:شديد|حاد) في (?:ال)?(?:بطن|معده)"),
]
_RF_TEXT_ML_RE = [(code, re.compile(pat, re.IGNORECASE)) for code, pat in _RF_TEXT_ML]
_AR_DIACRITICS = re.compile(r"[\u064B-\u0652\u0670\u0640]")


def ml_key(text: str) -> str:
    """English/Arabic matching form: lower case, no Arabic diacritics or tatweel, أ إ آ → ا, ى ی → ي, ة → ه,
    ک → ك, one space between words."""
    t = _AR_DIACRITICS.sub("", (text or "").lower())
    t = re.sub("[أإآ]", "ا", t).replace("ى", "ي").replace("ی", "ي").replace("ة", "ه").replace("ک", "ك")
    return " " + re.sub(r"\s+", " ", re.sub(r"[^\w\s']", " ", t)).strip() + " "


def detect_red_flags(text: str) -> list[str]:
    """Emergency codes found in a free-text patient message in Urdu, English or Arabic (empty list = none)."""
    if not text:
        return []
    key, ml = search_key(text), ml_key(text)
    found = [code for code, rx in _RF_TEXT_RE if rx.search(key)]
    found += [code for code, rx in _RF_TEXT_ML_RE if rx.search(ml) and code not in found]
    order = [c for c, _ in _RF_TEXT]
    return sorted(found, key=order.index)


# Urdu labels of the free-text-only emergency codes (the others are the RED_FLAGS options)
TEXT_FLAG_LABELS = {
    "poisoning": "زہر یا دوا کی زیادہ مقدار کھا لینا", "severe_headache": "اچانک شدید سر درد",
    "allergy_swelling": "چہرے، ہونٹوں یا گلے کی سوجن کے ساتھ سانس کی دشواری",
    "severe_abdominal_pain": "پیٹ میں شدید درد",
}


def emergency_message(codes: list[str], lang: str = "ur") -> str:
    from .i18n import tr
    return tr(SELF_HARM_MESSAGE if "self_harm" in codes else EMERGENCY_MESSAGE, lang)


# --------------------------------------------------------------------------- output guards
# A paragraph "looks like a recipe" when it names a recipe or gives ingredient quantities.
RECIPE_LIKE_RE = re.compile(
    r"نسخہ|اجزاء|اجزا |ہوالشافی|ھوالشافی|ترکیب تیاری|طریقہ تیاری|"
    r"\d+\s*(?:تولہ|تولے|ماشہ|ماشے|رتی|گرام|ملی|چمچ|چمچہ|عدد|حصہ|حصے|سیر|چھٹانک)")


RECIPE_LIKE_ML_RE = re.compile(
    r"recipe|ingredients|preparation|grind (?:them|together)|\d+\s*(?:g|gm|grams?|mg|ml|tsp|teaspoons?|tbsp|"
    r"tablespoons?|parts?|tola|masha|ratti)\b|وصفه|مكونات|طريقه التحضير|\d+\s*(?:غرام|جرام|ملغ|مل|ملعقه|جزء)")


def looks_like_recipe(text: str) -> bool:
    return bool(text) and bool(RECIPE_LIKE_RE.search(search_key(text).replace("۔", " ")) or
                               RECIPE_LIKE_RE.search(text) or RECIPE_LIKE_ML_RE.search(ml_key(text)))


def safe_for_patient(text: str, vulnerable: bool) -> bool:
    """True if a book excerpt may be shown: no hazardous ingredient, and no recipe for vulnerable groups."""
    return not hazard_flags(text) and not (vulnerable and looks_like_recipe(text))


def guard_answer(text: str, vulnerable: bool, lang: str = "ur") -> tuple[str, dict]:
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
    from .i18n import sep, tr
    if hazards:
        kept.append(tr(PRACTITIONER_ONLY, lang).format(
            items=sep(lang).join(tr(HAZARD_NAMES_UR.get(x, x), lang) for x in sorted(hazards))))
    if vuln_removed:
        kept.append(tr(VULNERABLE_NO_RECIPE, lang))
    return "\n".join(kept), {"hazards": sorted(hazards), "removed_paragraphs": removed,
                             "vulnerable_recipe_removed": vuln_removed}


# --------------------------------------------------------------------------- no references in patient text
_NUMS = r"[0-9۰-۹]+(?:\s*[،,\-–]\s*[0-9۰-۹]+)*"
_REF_PATTERNS = [
    re.compile(r"\s*\(\s*جلد\s*(?:اول|دوم|[12۱۲])[^)]*\)"),                    # (جلد دوم، صفحہ 127)
    re.compile(r"\s*جلد\s*(?:اول|دوم|[12۱۲])\s*[،,]?\s*(?:صفحہ|صفحات|ص)\s*" + _NUMS),
    re.compile(r"\s*\(?\s*صفح(?:ہ|ات)\s*" + _NUMS + r"\)?"),
    re.compile(r"\s*\[[0-9۰-۹]{1,2}\]"),                                           # [2] passage markers
    re.compile(r"کتاب\s*«?کلیات تحقیقات صابر ملتانی»?\s*(?:کے مطابق|میں)?[،,]?\s*"),
    re.compile(r"(?:حکیم\s*)?(?:دوست محمد\s*)?صابر ملتانی(?:\s*مرحوم)?"),
    re.compile(r"کتاب\s*(?:کے مطابق|میں)\s*[،,]?\s*"),
]


def strip_references(text: str | None) -> str | None:
    """Patient text without book names, author, volume/page references or passage markers."""
    if not text:
        return text
    for rx in _REF_PATTERNS:
        text = rx.sub("", text)
    text = re.sub(r"(?<![\n])[ \t]{2,}", " ", text)
    text = re.sub(r"\s+([۔،])", r"\1", text)
    text = re.sub(r"\bمستند حکیم\b|\bحکیم صاحب\b", "مستند معالج", text)
    return text.strip()
