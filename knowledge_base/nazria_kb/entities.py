"""Structured entities derived from topics: diseases, remedies (+ingredients), diet guidance."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .normalize import search_key, to_latin_digits
from .structure import NUM_WORDS, QUANTITY_RE, REMEDY_FORMS, Topic, split_sentences

NUM_VALUES = {"ایک": 1, "دو": 2, "تین": 3, "چار": 4, "پانچ": 5, "چھ": 6, "سات": 7, "آٹھ": 8, "نو": 9, "دس": 10,
              "گیارہ": 11, "بارہ": 12, "پندرہ": 15, "بیس": 20, "پچیس": 25, "تیس": 30, "چالیس": 40, "پچاس": 50,
              "ساٹھ": 60, "سو": 100, "نصف": 0.5, "آدھا": 0.5, "آدھ": 0.5, "ڈیڑھ": 1.5, "ڈھائی": 2.5, "اڑھائی": 2.5,
              "پاؤ": 0.25, "سوا": 1.25, "نیم": 0.5}
UNIT_CANON = {"تولے": "تولہ", "ماشے": "ماشہ", "رتیاں": "رتی", "حصے": "حصہ", "دانہ": "دانے", "چمچے": "چمچ",
              "چمچہ": "چمچ", "قطرہ": "قطرے", "گولیاں": "گولی", "کلوگرام": "کلو"}
AVOID_RE = re.compile(r"(پرہیز|نہ کھائیں|نہ دیں|منع|مضر|بچیں|ممنوع|نقصان دہ|اجتناب)")
SYMPTOM_LEAD_RE = re.compile(r"^(علامات|علامت)\s*[:：]?\s*")


@dataclass
class Ingredient:
    ordinal: int
    name: str
    quantity_text: str | None
    quantity_value: float | None
    unit: str | None


@dataclass
class Remedy:
    topic_index: int
    name: str
    dosage_form: str | None
    composition_text: str
    preparation_text: str | None
    dosage_text: str | None
    actions_text: str | None
    caution_text: str | None
    indication: str | None
    tehreek: str | None
    pages: list[int]
    ingredients: list[Ingredient] = field(default_factory=list)


@dataclass
class DietGuideline:
    topic_index: int
    kind: str          # recommended | avoid | general
    text: str
    items: list[str]
    pages: list[int]


@dataclass
class Disease:
    topic_index: int
    name: str
    tehreek: str | None
    definition: str | None
    causes: str | None
    symptoms: str | None
    diagnosis: str | None
    treatment: str | None
    pages: list[int]


def parse_quantity(q: str) -> tuple[float | None, str | None]:
    q = to_latin_digits(q).strip()
    m = re.match(r"^(\d+(?:[./]\d+)?)\s*(.+)$", q)
    if m:
        num = m.group(1)
        if "/" in num:
            a, b = num.split("/")
            value = float(a) / float(b) if float(b) else None
        else:
            value = float(num)
        unit = m.group(2).strip()
    else:
        parts = q.split()
        if len(parts) == 1:  # glued form, e.g. 'دوسیر'
            w = next((w for w in sorted(NUM_VALUES, key=len, reverse=True) if parts[0].startswith(w) and len(parts[0]) > len(w)), None)
            if w:
                parts = [w, parts[0][len(w):]]
        # the last token is the unit; everything before it is the number phrase ('دو نیم پاؤ' = 2.5 پاؤ)
        unit = parts[-1] if parts else None
        value = None
        for p in parts[:-1]:
            if p not in NUM_VALUES:
                continue
            v = NUM_VALUES[p]
            value = v if value is None else (value * v if v >= 100 else value + v)
    if unit:
        unit = UNIT_CANON.get(unit, unit)
    return value, unit


def parse_ingredients(text: str) -> list[Ingredient]:
    """'ٹماٹر ۴ سیر، کشمش نیم سیر، ادرک نیم پاؤ' -> [(ٹماٹر, 4, سیر), ...]"""
    text = re.sub(r"^\W*(ھوالشافی|ہوالشافی|نسخہ|اجزاء|اجزا)\W*", "", text.strip())
    first_sentence = re.split(r"[۔\n](?=\s*\S)", text, maxsplit=1)[0] if "۔" in text[:400] else text[:600]
    items = [i.strip(" -*•.") for i in re.split(r"[،,؛;\n]|\s-\s", first_sentence) if i.strip(" -*•.")]
    out: list[Ingredient] = []
    for it in items:
        m = QUANTITY_RE.search(it)
        qty = m.group(1) if m else None
        name = (it[: m.start()] + it[m.end():]).strip() if m else it
        name = re.sub(r"\b(ہر ایک|ہر یک|ہمراہ|حسب ضرورت|حسب ذائقہ|تا)\b", " ", name)
        name = re.sub(r"\s+", " ", name).strip(" -:،۔.")
        if not name or len(name.split()) > 5 or len(name) < 2:
            continue
        if not qty and not re.search(r"(حسب ضرورت|حسب ذائقہ|ہم وزن|برابر)", it):
            continue
        value, unit = parse_quantity(qty) if qty else (None, None)
        out.append(Ingredient(len(out) + 1, name, qty or re.search(r"حسب \S+|ہم وزن|برابر", it).group(0), value, unit))
    return out


def _first(t: Topic, *roles: str, max_sentences: int | None = None) -> str | None:
    texts = [s.text for s in t.sections if s.role in roles and s.text]
    if not texts:
        return None
    txt = "\n\n".join(texts)
    if max_sentences:
        txt = " ".join(split_sentences(txt)[:max_sentences])
    return txt.strip() or None


def dosage_form(title: str) -> str | None:
    first = search_key(title).split(" ")[0] if title else ""
    return first if first in REMEDY_FORMS and first not in ("دوا", "نسخہ", "مجرب") else None


def extract_entities(topics: list[Topic]) -> tuple[list[Disease], list[Remedy], list[DietGuideline]]:
    diseases: list[Disease] = []
    remedies: list[Remedy] = []
    diets: list[DietGuideline] = []
    for ti, t in enumerate(topics):
        if t.topic_type == "disease":
            diseases.append(Disease(
                ti, t.title, t.tehreek,
                definition=_first(t, "definition", "overview", max_sentences=6),
                causes=_first(t, "causes"),
                symptoms=_first(t, "symptoms"),
                diagnosis=_first(t, "diagnosis"),
                treatment=_first(t, "treatment"),
                pages=t.pages,
            ))
        # remedies: whole remedy topics, plus every recipe section inside disease topics
        recipe_sections = [s for s in t.sections if s.role == "recipe" and QUANTITY_RE.search(s.text)]
        if t.topic_type == "remedy":
            comp = _first(t, "recipe") or _first(t, "overview") or ""
            prep = [s.text for s in t.sections if s.role == "recipe" and "ترکیب" in s.heading]
            ingredients_src = next((s.text for s in t.sections if s.role == "recipe" and "ترکیب" not in s.heading), comp)
            r = Remedy(ti, t.title, dosage_form(t.title), comp,
                       preparation_text="\n\n".join(prep) or None,
                       dosage_text=_first(t, "dosage"),
                       actions_text=_first(t, "properties", "treatment"),
                       caution_text=_first(t, "note"),
                       indication=None, tehreek=t.tehreek, pages=t.pages)
            r.ingredients = parse_ingredients(ingredients_src)
            remedies.append(r)
        elif t.topic_type == "disease" and recipe_sections:
            dose = _first(t, "dosage")
            for n, s in enumerate(recipe_sections, 1):
                name = f"نسخہ برائے {t.title}" + (f" ({n})" if len(recipe_sections) > 1 else "")
                r = Remedy(ti, name, None, s.text, None, dose, None, None, indication=t.title,
                           tehreek=t.tehreek, pages=s.pages)
                r.ingredients = parse_ingredients(s.text)
                remedies.append(r)
        for s in t.sections:
            if s.role != "diet" or not s.text:
                continue
            kind = "avoid" if AVOID_RE.search(s.heading) else ("recommended" if t.topic_type in ("disease", "remedy") else "general")
            items = [i.strip(" -۔.") for i in re.split(r"[،,\n]", s.text) if 0 < len(i.strip()) < 40] if len(s.text) < 1200 else []
            diets.append(DietGuideline(ti, kind, s.text, items[:60], s.pages))
    return diseases, remedies, diets
