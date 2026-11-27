"""Book-grounded intake questionnaire and Mufrad Aza scoring.

Every scored option cites the volume and pages of «کلیات تحقیقات صابر ملتانی» where the sign is described
for that system:
* vol 2 (جلد دوم) p.125–126 (light fever from muscular / glandular / nervous inflammation), p.127–128 (three kinds
  of constipation), p.132–134 (cough and asthma types): the first nine sign questions;
* vol 1 (جلد اول) «تحقیقات امراض و علامات» p.549–562, the book's list of signs and the tehreek of each
  (appetite, thirst, pain, joints, skin, hair, feelings and other signs). The first-named system of the tehreek
  the book gives (e.g. «عضلاتی اعصابی تحریک» → عضلاتی) gets the point; labels name the book's term in brackets.
Weights are seeded into ``nazria.questionnaire_options`` so a Hakeem can tune them in the DB.

Page numbers are scan pages (``source_pages.page_no``; in vol 2 the printed number is 3 higher). Every weighted
link was checked against the book text of those pages.

Scoring is an *indication* of the dominant system (اعصابی / عضلاتی / غدی), not a diagnosis.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .safety import RED_FLAGS

SYSTEMS = ("اعصابی", "عضلاتی", "غدی")
SOURCE_BOOK = 2

# mizaj per tehreek, as worded in the book (same values as the nazria.tehreek table)
TEHREEK_MIZAJ = {
    "اعصابی عضلاتی": "سرد تر", "اعصابی غدی": "تر گرم", "عضلاتی اعصابی": "سرد خشک",
    "عضلاتی غدی": "خشک گرم", "غدی عضلاتی": "گرم خشک", "غدی اعصابی": "گرم تر",
}
SYSTEM_ORGANS = {"اعصابی": "دماغ و اعصاب", "عضلاتی": "قلب و عضلات", "غدی": "جگر و غدد"}


@dataclass
class Option:
    key: str
    label: str
    weights: dict[str, int] = field(default_factory=dict)   # system -> points
    pages: list[int] = field(default_factory=list)          # source pages (scan pages of ``volume``)
    volume: int = SOURCE_BOOK                                # 1 or 2


@dataclass
class Question:
    id: str
    kind: str            # single | multi | text
    text: str
    stage: str           # triage | profile | signs
    options: list[Option] = field(default_factory=list)


UNKNOWN = Option("unknown", "معلوم نہیں / ایسا کچھ نہیں")

DEFAULT_QUESTIONS: list[Question] = [
    Question("red_flags", "multi", "پہلے یہ بتائیں: کیا آپ کو ان میں سے کوئی علامت ہے؟ (جو لاگو ہوں ان کے نمبر لکھیں)", "triage",
             [Option(k, label) for k, label in RED_FLAGS] + [Option("none", "ان میں سے کوئی نہیں")]),
    Question("complaint", "text", "اپنی بنیادی تکلیف مختصراً بتائیں (مثلاً قبض، کھانسی، نزلہ، بخار، دمہ)۔", "profile"),
    Question("duration", "single", "یہ تکلیف کب سے ہے؟", "profile",
             [Option("days", "چند دن سے"), Option("weeks", "چند ہفتوں سے"), Option("chronic", "کئی مہینوں سے یا پرانی ہے")]),
    Question("age_group", "single", "آپ کی عمر؟", "profile",
             [Option("child", "12 سال سے کم"), Option("adult", "12 سے 60 سال"), Option("elderly", "60 سال سے زیادہ")]),
    Question("pregnancy", "single", "کیا آپ حاملہ ہیں یا بچے کو دودھ پلاتی ہیں؟", "profile",
             [Option("yes", "ہاں"), Option("no", "نہیں"), Option("na", "لاگو نہیں")]),
    # ---- signs (vol 2)
    Question("urine_color", "single", "آپ کے پیشاب (قارورہ) کا رنگ عام طور پر کیسا رہتا ہے؟", "signs", [
        Option("red", "سرخ یا سرخی مائل", {"عضلاتی": 2}, [125, 127, 133]),
        Option("yellow", "زرد یا زردی مائل", {"غدی": 2}, [125, 127, 134]),
        Option("white", "سفید یا سفیدی مائل", {"اعصابی": 2}, [126, 128, 134]),
        UNKNOWN]),
    Question("bowel", "single", "اجابت (پاخانہ) کی کیا کیفیت ہے؟", "signs", [
        Option("constipation", "قبض رہتی ہے، اکثر شدید یا پرانی", {"عضلاتی": 2}, [125, 127]),
        Option("incomplete", "پاخانہ تسلی سے نہیں ہوتا، مروڑ یا پیچش", {"غدی": 2}, [125, 127]),
        Option("loose", "اسہال یا پتلا پاخانہ", {"اعصابی": 2}, [126]),
        Option("normal", "معمول کے مطابق")]),
    Question("body", "single", "اپنے جسم کی عمومی کیفیت کیسی محسوس کرتے ہیں؟", "signs", [
        Option("dry", "جسم میں خشکی، دبلا پن", {"عضلاتی": 1}, [125, 127]),
        Option("heat", "جسم میں حرارت، ہاتھ پاؤں جلتے ہیں", {"غدی": 1}, [125, 127]),
        Option("phlegmatic", "بلغم زیادہ، جسم بھاری یا موٹا", {"اعصابی": 1}, [126]),
        UNKNOWN]),
    Question("abdomen", "single", "پیٹ کی کیا کیفیت رہتی ہے؟", "signs", [
        Option("gas", "گیس (ریاح) اور اپھارہ زیادہ", {"عضلاتی": 1}, [125, 127, 133, 134]),
        Option("heat_after_meal", "کھانے کے بعد حرارت بڑھ جاتی ہے یا پیٹ میں رکاوٹ محسوس ہوتی ہے", {"غدی": 1}, [125, 127]),
        UNKNOWN]),
    Question("taste", "single", "منہ کا ذائقہ عام طور پر کیسا رہتا ہے؟", "signs", [
        Option("sour", "ترش (کھٹا)", {"عضلاتی": 1}, [125]),
        Option("sweet", "میٹھا", {"غدی": 1}, [125]),
        Option("bitter", "کڑوا", {"اعصابی": 1}, [126]),
        UNKNOWN]),
    Question("heart", "single", "کیا دل گھبراتا ہے یا دھڑکن تیز رہتی ہے؟", "signs", [
        Option("yes", "ہاں", {"عضلاتی": 1}, [133, 134]),
        Option("no", "نہیں")]),
    Question("burning_urine", "single", "کیا پیشاب میں جلن ہوتی ہے؟", "signs", [
        Option("yes", "ہاں", {"غدی": 1}, [132, 134]),
        Option("no", "نہیں")]),
    Question("catarrh", "single", "کیا نزلہ، سر درد یا جسم میں سوجن اکثر رہتی ہے؟", "signs", [
        Option("yes", "ہاں", {"اعصابی": 1}, [128]),
        Option("no", "نہیں")]),
    Question("phlegm", "single", "اگر بلغم آتا ہے تو کیسا ہے؟", "signs", [
        Option("thick", "گاڑھا، مشکل سے نکلتا ہے", {"عضلاتی": 1}, [133]),
        Option("yellowish", "زردی مائل", {"غدی": 1}, [134]),
        Option("profuse", "بہت زیادہ رطوبت، اعضاء ڈھیلے محسوس ہوتے ہیں", {"اعصابی": 1}, [134]),
        Option("none", "بلغم نہیں آتا")]),
    # ---- signs (vol 1, «تحقیقات امراض و علامات»)
    Question("appetite", "single", "بھوک کیسی رہتی ہے؟", "signs", [
        Option("none", "بھوک بالکل نہیں لگتی، کھانے کو جی نہیں چاہتا (جوع البقر)", {"اعصابی": 1}, [555], 1),
        Option("excessive", "بہت بھوک لگتی ہے، کھانے کے بعد بھی پیٹ نہیں بھرتا (جوع الکلب)", {"عضلاتی": 1}, [556], 1),
        Option("normal", "معمول کے مطابق")]),
    Question("thirst", "single", "پیاس کیسی رہتی ہے؟", "signs", [
        Option("unquenched", "بہت پیاس لگتی ہے اور پانی پینے سے بھی نہیں بجھتی", {"غدی": 1}, [556, 583], 1),
        Option("normal", "معمول کے مطابق")]),
    Question("pain_timing", "single", "اگر جسم میں درد رہتا ہے تو کب بڑھتا ہے؟", "signs", [
        Option("movement", "حرکت کرنے سے بڑھتا ہے، آرام سے سکون ملتا ہے", {"عضلاتی": 1}, [551], 1),
        Option("rest", "آرام کرنے سے بڑھتا ہے، چلنے پھرنے سے سکون ملتا ہے", {"اعصابی": 1}, [551], 1),
        Option("none", "درد نہیں رہتا")]),
    Question("joints", "single", "جوڑوں کی کیا کیفیت ہے؟", "signs", [
        Option("swelling", "سوجن زیادہ اور درد کم، خاص طور پر بڑے جوڑوں میں (وجع المفاصل)", {"اعصابی": 1}, [559], 1),
        Option("sharp_pain", "شدید درد مگر سوجن نہیں، چھوٹے جوڑوں سے شروع ہوتا ہے (نقرس)", {"عضلاتی": 1}, [559], 1),
        Option("stiff", "جوڑ اکڑ جاتے ہیں اور سخت ہو جاتے ہیں (تحجر المفاصل)", {"عضلاتی": 1}, [559], 1),
        Option("none", "جوڑوں میں کوئی تکلیف نہیں")]),
    Question("skin", "multi", "جلد پر ان میں سے کیا ہے؟ (جو لاگو ہوں)", "signs", [
        Option("cracks", "جلد پھٹتی ہے، جیسے ایڑیاں یا ہاتھ (شقاق)", {"عضلاتی": 1}, [549], 1),
        Option("scaly_patches", "خشک کھردرے دھبے جن میں خارش ہو اور چھلکے اتریں (داد)", {"عضلاتی": 1}, [560, 561], 1),
        Option("acne", "چہرے پر کیل مہاسے", {"عضلاتی": 1}, [560], 1),
        Option("hives", "جسم پر سرخ ابھار جن میں خارش ہو (شری، پتی اچھلنا)", {"غدی": 1}, [560], 1),
        Option("burning_boils", "سرخ یا زردی مائل جلن والی پھنسیاں یا پھوڑے (جمرہ، دمل)", {"غدی": 1}, [560], 1),
        Option("white_patches", "جلد پر سفید داغ (برص)", {"اعصابی": 1}, [561], 1),
        Option("none", "ان میں سے کوئی نہیں")]),
    Question("hair", "single", "بالوں کی کیا کیفیت ہے؟", "signs", [
        Option("greying", "وقت سے پہلے سفید ہو رہے ہیں", {"اعصابی": 1}, [561], 1),
        Option("falling", "تیزی سے گر رہے ہیں (داء الثعلب)", {"عضلاتی": 1}, [561], 1),
        Option("normal", "معمول کے مطابق")]),
    Question("feeling", "single", "آج کل طبیعت پر کون سی کیفیت زیادہ رہتی ہے؟", "signs", [
        Option("fear", "ڈر، خوف یا گھبراہٹ", {"اعصابی": 1}, [551, 552], 1),
        Option("grief", "غم اور اداسی", {"غدی": 1}, [551, 552], 1),
        Option("none", "ان میں سے کوئی خاص نہیں")]),
    Question("other_signs", "multi", "ان میں سے کیا اکثر ہوتا ہے؟ (جو لاگو ہوں)", "signs", [
        Option("dizziness", "سر چکراتا ہے (دوار)", {"عضلاتی": 1}, [552], 1),
        Option("tremor", "ہاتھ پاؤں کانپتے ہیں (رعشہ)", {"عضلاتی": 1}, [554], 1),
        Option("night_blindness", "رات کو کم دکھائی دیتا ہے (شب کوری)", {"اعصابی": 1}, [554], 1),
        Option("sneezing", "چھینکیں بہت آتی ہیں (عطاس)", {"اعصابی": 1}, [555], 1),
        Option("hoarse_voice", "آواز بیٹھ جاتی ہے", {"عضلاتی": 1}, [556], 1),
        Option("hiccups", "ہچکی بار بار آتی ہے (فواق)", {"عضلاتی": 1}, [556], 1),
        Option("nausea", "متلی یا قے", {"اعصابی": 1}, [556], 1),
        Option("bedwetting", "نیند میں پیشاب نکل جاتا ہے (بول فی الفراش)", {"اعصابی": 1}, [557, 558], 1),
        Option("none", "ان میں سے کوئی نہیں")]),
]


@dataclass
class Score:
    totals: dict[str, int]
    primary: str | None
    secondary: str | None
    tehreek: str | None
    confidence: float           # 0..1, margin of the leader over the runner-up
    conclusive: bool
    evidence: list[tuple[str, str, str, list[int]]]   # (question text, answer label, system, pages)
    evidence_keys: list[tuple[str, str]] = field(default_factory=list)   # (question id, option key), same order
    evidence_volumes: list[int] = field(default_factory=list)            # book volume of each evidence row


def score(questions: list[Question], answers: dict[str, object], min_points: int = 3) -> Score:
    totals = {s: 0 for s in SYSTEMS}
    evidence, evidence_keys, volumes = [], [], []
    for q in questions:
        if q.stage != "signs" or q.id not in answers:
            continue
        keys = answers[q.id] if isinstance(answers[q.id], list) else [answers[q.id]]
        for opt in q.options:
            if opt.key in keys:
                for system, pts in opt.weights.items():
                    totals[system] += pts
                    evidence.append((q.text, opt.label, system, opt.pages))
                    evidence_keys.append((q.id, opt.key))
                    volumes.append(opt.volume)
    ranked = sorted(SYSTEMS, key=lambda s: (-totals[s], SYSTEMS.index(s)))
    total = sum(totals.values())
    lead, second = totals[ranked[0]], totals[ranked[1]]
    conclusive = total >= min_points and lead > second
    primary = ranked[0] if conclusive else None
    secondary = ranked[1] if conclusive and second > 0 else None
    tehreek = f"{primary} {secondary}" if primary and secondary else None
    confidence = round((lead - second) / total, 2) if total else 0.0
    return Score(totals, primary, secondary, tehreek, confidence, conclusive, evidence, evidence_keys, volumes)
