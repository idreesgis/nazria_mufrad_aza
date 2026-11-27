"""Diet plan for the tehreek the questionnaire finds.

Source (for review only, never shown to the patient): vol 1 «تحقیقات علاج بالغذاء», «ترتیب غذا بالنظریہ مفرد اعضاء»
pp.685–687 (scan pages). The book gives six food groups, one per tehreek, and says for which condition of the body
each group is given; the corrective group is the next tehreek in the cycle:

    patient's tehreek     foods of           page
    اعصابی عضلاتی  →  عضلاتی اعصابی     685
    عضلاتی اعصابی  →  عضلاتی غدی       685  (the line naming the condition is cut in the OCR: from the cycle)
    عضلاتی غدی     →  غدی عضلاتی       686
    غدی عضلاتی     →  غدی اعصابی       686
    غدی اعصابی     →  اعصابی غدی       687
    اعصابی غدی     →  اعصابی عضلاتی     687

Meals (p.688): the day's food in three parts, morning, midday and night; foods of one group only, never mixed with
another group's. General rules: pp.683–684, 688. Qehwa herbs and their tehreek: اجوائن دیسی p.710, ادرک/سونٹھ and
ہلدی pp.706–709, املی pp.711–712, چھوٹی/بڑی الائچی p.713 (vol 1); دارچینی and لونگ vol 2 p.300.
Only foods the book lists are used; OCR-garbled words were left out.
"""
from __future__ import annotations

from .questionnaire import TEHREEK_MIZAJ

NEXT_TEHREEK = {
    "اعصابی عضلاتی": "عضلاتی اعصابی", "عضلاتی اعصابی": "عضلاتی غدی", "عضلاتی غدی": "غدی عضلاتی",
    "غدی عضلاتی": "غدی اعصابی", "غدی اعصابی": "اعصابی غدی", "اعصابی غدی": "اعصابی عضلاتی",
}

# the six food groups, keyed by the tehreek whose foods they are
FOOD_GROUPS: dict[str, dict] = {
    "عضلاتی اعصابی": {
        "breakfast": ["لسی", "جوار یا باجرے کی روٹی"],
        "lunch": ["لوبیا", "آلو مٹر", "گوبھی یا بینگن", "جوار یا باجرے کی روٹی"],
        "dinner": ["مچھلی یا بھینس کا گوشت (یا سری پائے)", "اروی یا آلو کی سبزی"],
        "fruits": ["سیب", "جامن", "فالسہ", "انناس", "سنگترہ", "آلوچہ", "بیر", "ترش آڑو"],
        "dry_fruits": ["مونگ پھلی"],
        "qehwa": {"name": "املی کا قہوہ", "ingredients": ["املی ایک چھوٹا ٹکڑا"],
                  "how": "ایک کپ پانی میں املی ڈال کر پانچ منٹ ابالیں، چھان کر نیم گرم پی لیں۔"},
    },
    "عضلاتی غدی": {
        "breakfast": ["کھجور خشک یا انجیر", "اخروٹ"],
        "lunch": ["پالک یا سرسوں کا ساگ", "کریلے", "پیاز"],
        "dinner": ["گائے یا کبوتر کا گوشت", "شلجم کی سبزی"],
        "fruits": ["شیریں آڑو", "کھجور", "انجیر"],
        "dry_fruits": ["پستہ", "اخروٹ", "کشمش", "منقی", "خشک انجیر", "خشک کھجور"],
        "qehwa": {"name": "دارچینی اور لونگ کا قہوہ", "ingredients": ["دارچینی کا ایک چھوٹا ٹکڑا", "دو لونگ"],
                  "how": "ایک کپ پانی میں دارچینی اور لونگ ڈال کر پانچ منٹ ابالیں، چھان کر نیم گرم پی لیں۔"},
    },
    "غدی عضلاتی": {
        "breakfast": ["انڈے", "چنے"],
        "lunch": ["چنے کی دال یا سالن", "میتھی کا ساگ", "ادرک، لہسن اور پیاز کے ساتھ"],
        "dinner": ["بکری یا دیسی مرغی کا گوشت", "میتھی کا ساگ"],
        "fruits": ["آم", "کھجور", "شیریں خوبانی", "آلو بخارا", "شہتوت"],
        "dry_fruits": ["چلغوزہ"],
        "qehwa": {"name": "اجوائن کا قہوہ", "ingredients": ["دیسی اجوائن آدھا چائے کا چمچ"],
                  "how": "ایک کپ پانی میں اجوائن ڈال کر پانچ منٹ ابالیں، چھان کر نیم گرم پی لیں۔"},
    },
    "غدی اعصابی": {
        "breakfast": ["بکری کا دودھ", "انڈے", "گندم کی روٹی یا دلیہ"],
        "lunch": ["مونگ کی دال", "بھنڈی", "گندم کی روٹی"],
        "dinner": ["بٹیر، تیتر یا بطخ کا گوشت", "گندم کی روٹی"],
        "fruits": ["شیریں انگور", "خربوزہ"],
        "dry_fruits": ["بادام"],
        "qehwa": {"name": "ادرک اور ہلدی کا قہوہ", "ingredients": ["ادرک کا چھوٹا ٹکڑا یا سونٹھ ایک چٹکی",
                                                             "ہلدی ایک چٹکی"],
                  "how": "ایک کپ پانی میں ادرک اور ہلدی ڈال کر پانچ منٹ ابالیں، چھان کر نیم گرم پی لیں۔"},
    },
    "اعصابی غدی": {
        "breakfast": ["گائے کا دودھ", "ساگودانہ"],
        "lunch": ["ماش کی دال", "کدو یا لوکی", "گاجر"],
        "dinner": ["لوکی یا حلوا کدو کی سبزی", "مولی", "ضرورت ہو تو مچھلی (گوشت نہیں)"],
        "fruits": ["ناشپاتی", "شیریں کیلا", "آلو بخارا", "زرد امرود"],
        "dry_fruits": [],
        "qehwa": {"name": "چھوٹی الائچی کا قہوہ", "ingredients": ["دو چھوٹی الائچی"],
                  "how": "ایک کپ پانی میں الائچی کچل کر ڈالیں، پانچ منٹ ابالیں، چھان کر نیم گرم پی لیں۔"},
    },
    "اعصابی عضلاتی": {
        "breakfast": ["بھینس کا دودھ", "انڈے کی سفیدی"],
        "lunch": ["چاول", "کھیرا اور ککڑی", "شلجم یا چقندر"],
        "dinner": ["مچھلی یا سری پائے، بغیر نمک مرچ کے (گوشت نہیں)", "چقندر یا شلجم کی سبزی"],
        "fruits": [],
        "dry_fruits": [],
        "qehwa": {"name": "بڑی الائچی کا قہوہ", "ingredients": ["ایک بڑی الائچی"],
                  "how": "ایک کپ پانی میں بڑی الائچی کچل کر ڈالیں، پانچ منٹ ابالیں، چھان کر نیم گرم پی لیں۔"},
    },
}

GENERAL_RULES = [
    "کھانا صرف اصل بھوک لگنے پر اور مقررہ وقت پر کھائیں؛ دو کھانوں کے درمیان کم از کم چھ گھنٹے کا وقفہ رکھیں۔",
    "اس پلان کی غذائیں آپس میں ملا سکتے ہیں، مگر دوسری قسم کی غذائیں ان کے ساتھ نہ ملائیں۔",
    "غذا تازہ ہو اور اچھی طرح گلا کر پکائی جائے؛ باسی کھانا نہ کھائیں۔",
    "تھکن کی حالت میں کھانا نہ کھائیں، پہلے آرام کریں۔",
    "پیٹ بوجھل ہو یا گیس اور بے چینی ہو تو کھانا چھوڑ دیں؛ کمزوری ہو تو قہوہ، پھلوں کا رس یا ہلکا شوربہ لیں۔",
    "قہوہ دن میں ایک یا دو بار، کھانے کے بعد نیم گرم پئیں؛ قہوے میں لیموں بھی نچوڑ سکتے ہیں۔",
]
NO_DRY_FRUITS = "اس حالت میں میوہ جات نہ لیں۔"
NO_FRUITS = "اس حالت میں پھل کم سے کم لیں؛ اوپر دی گئی غذاؤں پر ہی رہیں۔"

CHOOSE_IF = {   # when only the dominant system is known: how the patient picks between its two tehreeks
    "اعصابی عضلاتی": "اگر جسم میں سردی اور تری (بلغم، رطوبت) زیادہ محسوس ہو",
    "اعصابی غدی": "اگر جسم میں تری کے ساتھ گرمی محسوس ہو",
    "عضلاتی اعصابی": "اگر جسم میں خشکی کے ساتھ سردی محسوس ہو",
    "عضلاتی غدی": "اگر جسم میں خشکی کے ساتھ گرمی محسوس ہو",
    "غدی عضلاتی": "اگر جسم میں گرمی کے ساتھ خشکی محسوس ہو",
    "غدی اعصابی": "اگر جسم میں گرمی کے ساتھ تری محسوس ہو",
}

SWEET_ITEMS = ("کھجور", "کشمش", "منقی", "انجیر", "آم", "شیریں", "کیلا", "انگور", "خربوزہ", "ساگودانہ")


def _notes(group: dict, conditions: list[str], caution: bool, vulnerable: bool) -> list[str]:
    notes = []
    if "diabetes" in conditions and any(s in item for k in ("fruits", "dry_fruits", "breakfast") for item in group[k]
                                        for s in SWEET_ITEMS):
        notes.append("شوگر کی وجہ سے میٹھے پھل، کھجور، کشمش، منقی اور ساگودانہ بہت کم لیں، اور قہوہ بغیر چینی کے پئیں۔")
    if "hypertension" in conditions:
        notes.append("بلند فشار خون کی وجہ سے نمک کم استعمال کریں۔")
    if set(conditions) & {"kidney", "liver", "heart"}:
        notes.append("گردے، جگر یا دل کی بیماری کی وجہ سے غذا میں بڑی تبدیلی سے پہلے اپنے معالج سے مشورہ کریں۔")
    if caution:
        notes.append("جس چیز سے الرجی ہو وہ نہ لیں؛ دوائیں چل رہی ہوں تو قہوہ شروع کرنے سے پہلے معالج سے پوچھ لیں۔")
    if vulnerable:
        notes.append("بچوں، حاملہ یا دودھ پلانے والی خواتین اور بزرگوں کے لیے مقدار کم رکھیں اور معالج سے مشورہ کریں۔")
    return notes


def plan_for(tehreek: str, conditions: list[str] | None = None, caution: bool = False,
             vulnerable: bool = False, choose_if: str | None = None) -> dict:
    """The diet plan for a patient whose tehreek is ``tehreek``."""
    foods_of = NEXT_TEHREEK[tehreek]
    g = FOOD_GROUPS[foods_of]
    return {
        "tehreek": tehreek, "mizaj": TEHREEK_MIZAJ[tehreek], "choose_if": choose_if,
        "breakfast": list(g["breakfast"]), "lunch": list(g["lunch"]), "dinner": list(g["dinner"]),
        "fruits": list(g["fruits"]), "dry_fruits": list(g["dry_fruits"]), "qehwa": dict(g["qehwa"]),
        "rules": list(GENERAL_RULES) + ([NO_DRY_FRUITS] if not g["dry_fruits"] else [])
                 + ([NO_FRUITS] if not g["fruits"] else []),
        "notes": _notes(g, list(conditions or []), caution, vulnerable),
    }


def diet_plans(tehreek: str | None, primary: str | None, conditions: list[str] | None = None,
               caution: bool = False, vulnerable: bool = False) -> list[dict]:
    """One plan when the tehreek is known; when only the dominant system is known, its two tehreeks, each with the
    feeling that tells the patient which one applies; none when the result is inconclusive."""
    if tehreek in NEXT_TEHREEK:
        return [plan_for(tehreek, conditions, caution, vulnerable)]
    if primary:
        return [plan_for(t, conditions, caution, vulnerable, CHOOSE_IF[t])
                for t in NEXT_TEHREEK if t.split()[0] == primary]
    return []


def localize_plan(p: dict, lang: str) -> dict:
    """A plan (built in Urdu) in ur | en | ar, with language-neutral codes added."""
    from .i18n import tehreek_code, tehreek_name, tr, tr_list
    q = p["qehwa"]
    return {"tehreek": tehreek_name(p["tehreek"], lang), "tehreek_code": tehreek_code(p["tehreek"]),
            "mizaj": tr(p["mizaj"], lang), "choose_if": tr(p["choose_if"], lang) if p["choose_if"] else None,
            **{k: tr_list(p[k], lang) for k in ("breakfast", "lunch", "dinner", "fruits", "dry_fruits", "rules",
                                                 "notes")},
            "qehwa": {"name": tr(q["name"], lang), "ingredients": tr_list(q["ingredients"], lang),
                      "how": tr(q["how"], lang)}}


def render_plans(plans: list[dict], lang: str = "ur") -> str:
    """Text of the plans (appended to the result text)."""
    from .i18n import msg, sep, tr
    if not plans:
        return ""
    lines = [msg("diet_title", lang)]
    j = sep(lang)
    for p in (localize_plan(x, lang) for x in plans):
        lines.append("")
        head = msg("diet_head", lang, tehreek=p["tehreek"], mizaj=p["mizaj"])
        lines.append(msg("diet_choose", lang, choose_if=p["choose_if"], head=head) if p["choose_if"]
                     else head + ":")
        lines.append(msg("breakfast", lang) + j.join(p["breakfast"]))
        lines.append(msg("lunch", lang) + j.join(p["lunch"]))
        lines.append(msg("dinner", lang) + j.join(p["dinner"]))
        lines.append(msg("fruits", lang) + (j.join(p["fruits"]) if p["fruits"] else tr(NO_FRUITS, lang)))
        lines.append(msg("dry_fruits", lang) + (j.join(p["dry_fruits"]) if p["dry_fruits"] else tr(NO_DRY_FRUITS, lang)))
        q = p["qehwa"]
        lines.append(msg("qehwa", lang, name=q["name"], ingredients=j.join(q["ingredients"]), how=q["how"]))
        for n in p["notes"]:
            lines.append("• " + n)
    lines += ["", msg("diet_rules", lang)] + ["• " + tr(r, lang) for r in GENERAL_RULES]
    return "\n".join(lines)
