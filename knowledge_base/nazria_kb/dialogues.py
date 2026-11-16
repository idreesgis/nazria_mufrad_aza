"""Rule-based (template) Hakeem <-> Patient conversation generator.

Every Hakeem turn is grounded in a book section and carries ``refs`` =
[(topic_index, section_index)], which the DB loader resolves to knowledge
chunk ids. Generation is deterministic (seeded per topic) so re-runs give
identical data.

Conversation types
* ``consultation``   – multi-turn: complaint -> intake questions -> explanation
                       (definition/causes, tehreek) -> treatment/recipe/dose -> diet -> safety note
* ``remedy_inquiry`` – patient asks about a named remedy: composition, preparation, dose, uses
* ``qa``             – single-turn question/answer for one section of any topic
"""
from __future__ import annotations

import random
import re
from dataclasses import dataclass, field

from .normalize import latin_ratio
from .normalize import search_key
from .structure import Topic, has_disease_cue, Treatise, classify_role, heading_subject, split_sentences

GENERATOR = "rule_template_v1"
BOOK_TITLE = "کلیات تحقیقات صابر ملتانی"
VOLUME_NAMES = {1: "جلد اول", 2: "جلد دوم"}

SYSTEM_PROMPT = (
    "آپ ایک تجربہ کار اور شفیق حکیم ہیں جو حکیم انقلاب دوست محمد صابر ملتانی کے نظریہ مفرد اعضاء "
    "(اعصابی، عضلاتی، غدی تحریکات) کے مطابق مریضوں کی رہنمائی کرتے ہیں۔ آپ سادہ اور شائستہ اردو میں "
    "بات کرتے ہیں، مریض سے ضروری سوالات پوچھتے ہیں، اپنی بات کتاب «کلیات تحقیقات صابر ملتانی» کے حوالے "
    "سے کرتے ہیں، اور ہمیشہ مشورہ دیتے ہیں کہ دوا شروع کرنے سے پہلے کسی مستند حکیم سے نبض و قارورہ کا "
    "معائنہ کروایا جائے۔ ہنگامی علامات میں فوراً قریبی ہسپتال جانے کا کہتے ہیں۔"
)

# --------------------------------------------------------------------------- template pools
GREETINGS = ["السلام علیکم حکیم صاحب۔", "حکیم صاحب، السلام علیکم۔", "آداب حکیم صاحب۔", "السلام علیکم۔"]
HAKEEM_WELCOME = ["وعلیکم السلام، تشریف رکھیں۔", "وعلیکم السلام، فرمائیے کیا تکلیف ہے؟",
                  "وعلیکم السلام۔ اطمینان سے اپنی تکلیف بتائیں۔"]
COMPLAINT_BY_NAME = ["مجھے کچھ عرصے سے {name} کی شکایت ہے۔", "میں {name} کی وجہ سے بہت پریشان ہوں۔",
                     "میرے گھر والوں کا خیال ہے کہ مجھے {name} ہے۔ اس بارے میں رہنمائی چاہیے۔"]
COMPLAINT_BY_SYMPTOMS = ["میری طبیعت کچھ دنوں سے ٹھیک نہیں، یہ تکالیف ہیں: {symptoms}",
                         "مجھے یہ مسائل محسوس ہو رہے ہیں: {symptoms}"]
INTAKE_QUESTIONS = [
    "یہ تکلیف کب سے ہے، اور کیا پہلے بھی کبھی ہوئی تھی؟",
    "آپ کی بھوک، نیند اور اجابت (قبض یا اسہال) کی کیا کیفیت ہے؟",
    "پیشاب کا رنگ کیسا رہتا ہے اور کیا اس میں جلن تو نہیں ہوتی؟",
    "آپ کی غذا عام طور پر کیا ہوتی ہے؟ چائے، گوشت، مرچ مصالحہ یا ٹھنڈی چیزیں زیادہ تو نہیں لیتے؟",
    "کیا کوئی دوا پہلے سے استعمال کر رہے ہیں؟",
]
PATIENT_INTAKE_ANSWERS = [
    "تقریباً دو ماہ سے ہے۔ بھوک کم ہے اور نیند بھی ٹھیک نہیں آتی۔",
    "کافی عرصے سے یہی حال ہے، کبھی کم کبھی زیادہ۔ قبض بھی رہتی ہے۔",
    "چند ہفتوں سے ہے۔ کھانا وقت پر نہیں کھاتا اور چائے زیادہ پیتا ہوں۔",
    "پہلے بھی ہو چکی ہے۔ ابھی کوئی خاص دوا استعمال نہیں کر رہا۔",
]
PULSE_LINE = "اچھا، ذرا اپنی کلائی دیجیے، میں نبض دیکھ لوں۔"
EXPLAIN_LEADS = ["دیکھیے، پہلے یہ سمجھ لیں کہ {name} کیا ہے۔", "{name} کی حقیقت یہ ہے:", "اس مرض کو یوں سمجھیں:"]
CAUSE_LEADS = ["اس کے اسباب یہ بیان کیے گئے ہیں:", "عام طور پر یہ حالت ان وجوہات سے پیدا ہوتی ہے:"]
SYMPTOM_LEADS = ["اس کی علامات یہ ہیں:", "ان علامات پر غور کریں:"]
DIAGNOSIS_LEADS = ["تشخیص کے لیے یہ دیکھا جاتا ہے:", "نبض و قارورہ کے لحاظ سے:"]
TEHREEK_LINE = "نظریہ مفرد اعضاء کے مطابق اس حالت میں عموماً «{tehreek}» تحریک پائی جاتی ہے، اور علاج اسی تحریک کو مدنظر رکھ کر کیا جاتا ہے۔"
ASK_TREATMENT = ["حکیم صاحب، اس کا علاج کیا ہے؟", "اس کے لیے کون سی دوا مفید ہے؟", "پھر مجھے کیا کرنا چاہیے؟"]
TREATMENT_LEADS = ["علاج کے بارے میں کتاب میں یہ ہدایت ہے:", "اصول علاج یہ ہے:"]
RECIPE_LEADS = ["اس کے لیے یہ نسخہ مجرب ہے:", "یہ نسخہ تیار کر لیں:"]
DOSE_LEADS = ["مقدار خوراک:", "استعمال کا طریقہ یہ ہے:"]
ASK_DIET = ["کھانے پینے میں کیا احتیاط کروں؟", "غذا اور پرہیز کیا رکھوں؟"]
DIET_LEADS = ["غذا کے بارے میں یہ ہدایات ہیں:", "خوراک کا خیال اس طرح رکھیں:"]
PATIENT_THANKS = ["بہت شکریہ حکیم صاحب۔", "جزاک اللہ، آپ نے بہت اچھی طرح سمجھایا۔", "شکریہ، میں ان ہدایات پر عمل کروں گا۔"]
SAFETY_CLOSE = ("یہ معلومات {book} ({volume}، صفحات {pages}) سے ماخوذ ہیں۔ کوئی بھی دوا شروع کرنے سے پہلے "
                "کسی مستند حکیم سے نبض اور قارورہ کا معائنہ ضرور کروائیں، اور اگر تکلیف شدید ہو یا بڑھ جائے تو فوراً "
                "قریبی ڈاکٹر یا ہسپتال سے رجوع کریں۔ اللہ آپ کو شفا دے۔")

REMEDY_ASK = ["حکیم صاحب، «{name}» کے بارے میں بتائیں، یہ کیسے بنتا ہے اور کس کام آتا ہے؟",
              "میں نے «{name}» کا نام سنا ہے، اس کے اجزاء اور فوائد کیا ہیں؟"]
REMEDY_COMPOSITION = ["اس کے اجزاء یہ ہیں:", "نسخہ یوں ہے:"]
REMEDY_ASK_PREP = ["اسے تیار کیسے کریں؟", "بنانے کا طریقہ بھی بتا دیجیے۔"]
REMEDY_ASK_DOSE = ["کتنی مقدار میں اور کب استعمال کروں؟", "اس کی خوراک کیا ہے؟"]
REMEDY_ASK_USES = ["یہ کن تکالیف میں فائدہ دیتا ہے؟", "اس کے فوائد کیا ہیں؟"]

QA_TEMPLATES = {
    "overview": ["{name} کے بارے میں وضاحت فرمائیں۔", "{name} سے کیا مراد ہے؟", "حکیم صاحب، {name} کے متعلق بتائیں۔"],
    "definition": ["{name} کی تعریف کیا ہے؟", "{name} کی حقیقت اور ماہیت کیا ہے؟"],
    "causes": ["{name} کے اسباب کیا ہیں؟", "{name} کیوں ہوتا ہے؟"],
    "symptoms": ["{name} کی علامات کیا ہیں؟", "کیسے پتا چلے کہ {name} ہے؟"],
    "diagnosis": ["{name} کی تشخیص کیسے کی جاتی ہے؟", "{name} میں نبض اور قارورہ کیسا ہوتا ہے؟"],
    "treatment": ["{name} کا علاج کیا ہے؟", "{name} میں کیا علاج کیا جائے؟"],
    "recipe": ["{name} کے لیے کون سا نسخہ مفید ہے؟", "{name} کا نسخہ بتائیں۔"],
    "dosage": ["{name} کی مقدار خوراک کیا ہے؟", "{name} کس طرح استعمال کریں؟"],
    "diet": ["{name} میں غذا اور پرہیز کیا ہونا چاہیے؟", "{name} میں کیا کھائیں اور کیا نہ کھائیں؟"],
    "properties": ["{name} کے خواص اور فوائد کیا ہیں؟", "{name} کا مزاج اور افعال و اثرات کیا ہیں؟"],
}
QA_ANSWER_LEADS = ["", "کتاب کے مطابق: ", "اس بارے میں یہ بیان کیا گیا ہے: "]

JUNK_TITLE_RE = re.compile(r"^(footnotes?|حاشیہ|حواشی|فہرست|فہرست عنوانات|نوٹ|خصوصی|ضروری|مزید|ایک دوسرا نکتہ|دیگر|دیگر اہم|لازمی"
                           r"|غیر ضروری|مزید تشریح|ایک انکشاف|ایک متعدد|دلچسپ بحث|غلط فہمی|خلاصہ|نتیجہ|تمہید|مقدمہ|پیش لفظ)$",
                           re.IGNORECASE)


# --------------------------------------------------------------------------- data classes
@dataclass
class Turn:
    role: str                       # patient | hakeem
    content: str
    refs: list[tuple[int, int]] = field(default_factory=list)   # (topic_index, section_index)


@dataclass
class Conversation:
    conv_type: str
    topic_index: int
    title: str
    template_id: str
    seed: int
    turns: list[Turn]
    pages: list[int]
    volume_no: int
    quality_score: float
    system_prompt: str = SYSTEM_PROMPT
    generator: str = GENERATOR


# --------------------------------------------------------------------------- helpers
def plain(text: str) -> str:
    text = re.sub(r"^#{1,6}\s*", "", text, flags=re.M)
    text = text.replace("**", "")
    text = re.sub(r"^- ", "• ", text, flags=re.M)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def excerpt(text: str, max_chars: int = 900, max_sentences: int = 8) -> str:
    text = plain(text)
    if len(text) <= max_chars:
        return text
    out = ""
    for s in split_sentences(text)[:max_sentences]:
        if len(out) + len(s) + 1 > max_chars:
            break
        out = (out + " " + s).strip()
    if not out:  # one giant sentence
        cut = text.rfind(" ", 0, max_chars)
        out = text[: cut if cut > 0 else max_chars] + " …"
    return out


def short_items(text: str, n: int = 3, max_len: int = 110) -> list[str]:
    raw = [l.strip("•- ").strip() for l in plain(text).split("\n") if l.strip()]
    if len(raw) < 2:
        raw = split_sentences(plain(text))
    if len(raw) < 2:
        raw = [x.strip() for x in plain(text).split("،")]
    items = [x.rstrip("۔. ") for x in raw if 8 <= len(x) <= max_len]
    return items[:n]


def good_title(t: Topic) -> bool:
    title = t.title.strip()
    if not (2 < len(title) <= 70) or latin_ratio(title) >= 0.5 or JUNK_TITLE_RE.match(search_key(title)):
        return False
    if re.match(r"^[\W\d]", title) or re.match(r"^\S\s", title):  # numbering / stray letter like 'ب پیپ…'
        return False
    role = classify_role(title)
    if role and not heading_subject(title, role):
        return False  # the title is only a role word, e.g. 'تعریف'
    return True


def is_condition(t: Topic) -> bool:
    return has_disease_cue(t.title) or (t.topic_type == "disease" and bool({"symptoms", "causes"} & set(t.roles)))


def pick(rng: random.Random, pool: list[str], **kw) -> str:
    return rng.choice(pool).format(**kw)


def _sec(t: Topic, role: str) -> tuple[int, str] | None:
    for i, s in enumerate(t.sections):
        if s.role == role and len(s.text) >= 40:
            return i, s.text
    return None


def page_span(pages: list[int]) -> str:
    if not pages:
        return "—"
    return str(pages[0]) if pages[0] == pages[-1] else f"{pages[0]}–{pages[-1]}"


def _quality(t: Topic, page_quality: dict[tuple[int, int], float], refs: list[tuple[int, int]]) -> float:
    ps = t.pages or [0]
    q = sum(page_quality.get((t.volume_no, p), 0.8) for p in ps) / len(ps)
    coverage = min(1.0, len({r for r in refs}) / 4)
    return round(0.7 * q + 0.3 * coverage, 3)


# --------------------------------------------------------------------------- generators
PRESENTATION = {"symptoms", "causes", "diagnosis"}
MANAGEMENT = ("treatment", "recipe", "dosage", "diet")
NO_TREATMENT_LINE = ("اس حالت کا علاج مریض کی نبض اور قارورہ دیکھ کر، غالب تحریک کے مطابق تجویز کیا جاتا ہے۔ "
                     "جب تک معائنہ نہ ہو جائے، غذا سادہ اور زود ہضم رکھیں اور اپنی علامات پر نظر رکھیں۔")


def _management(topics: list[Topic], ti: int, window: int = 4) -> dict[str, tuple[int, int, str]]:
    """Management sections of topic ti, else of the following topics of the same treatise
    (stopping at the next topic that presents a different condition)."""
    found: dict[str, tuple[int, int, str]] = {}
    t = topics[ti]
    for j in range(ti, min(ti + 1 + window, len(topics))):
        u = topics[j]
        if u.treatise_ordinal != t.treatise_ordinal:
            break
        if j > ti and set(u.roles) & PRESENTATION:
            break
        for role in MANAGEMENT:
            if role not in found:
                sec = _sec(u, role)
                if sec:
                    found[role] = (j, sec[0], sec[1])
        if j == ti and found:
            break  # the topic has its own management part; don't borrow
    return found


def consultation(ti: int, topics: list[Topic], rng: random.Random, variant: int, pq: dict) -> Conversation | None:
    t = topics[ti]
    sym = _sec(t, "symptoms")
    expl = _sec(t, "definition") or _sec(t, "overview")
    cause = _sec(t, "causes")
    diag = _sec(t, "diagnosis")
    mg = _management(topics, ti)
    treat, recipe, dose, diet = (mg.get(r) for r in MANAGEMENT)
    # a consultation needs a presentation (symptoms/causes/diagnosis) plus an explanation or a management part
    if not (sym or cause or diag) or not (mg or expl):
        return None
    name = t.title
    turns: list[Turn] = []
    turns.append(Turn("patient", pick(rng, GREETINGS)))
    turns.append(Turn("hakeem", pick(rng, HAKEEM_WELCOME)))
    if sym and variant % 2 == 1 and short_items(sym[1]):
        turns.append(Turn("patient", pick(rng, COMPLAINT_BY_SYMPTOMS, symptoms="، ".join(short_items(sym[1])) + "۔")))
    else:
        turns.append(Turn("patient", pick(rng, COMPLAINT_BY_NAME, name=name)))
    q1, q2 = rng.sample(INTAKE_QUESTIONS, 2)
    turns.append(Turn("hakeem", f"{q1} {q2}"))
    turns.append(Turn("patient", pick(rng, PATIENT_INTAKE_ANSWERS)))
    # explanation
    parts, refs = [], []
    if expl:
        parts.append(pick(rng, EXPLAIN_LEADS, name=name) + "\n" + excerpt(expl[1], 700, 5))
        refs.append((ti, expl[0]))
    if cause:
        parts.append(pick(rng, CAUSE_LEADS) + "\n" + excerpt(cause[1], 500, 4))
        refs.append((ti, cause[0]))
    if sym and (variant % 2 == 0 or not parts):
        parts.append(pick(rng, SYMPTOM_LEADS) + "\n" + excerpt(sym[1], 500, 5))
        refs.append((ti, sym[0]))
    if diag:
        parts.append(pick(rng, DIAGNOSIS_LEADS) + "\n" + excerpt(diag[1], 400, 3))
        refs.append((ti, diag[0]))
    if t.tehreek:
        parts.append(TEHREEK_LINE.format(tehreek=t.tehreek))
    if parts:
        turns.append(Turn("hakeem", PULSE_LINE + "\n\n" + "\n\n".join(parts), refs))
    # treatment
    turns.append(Turn("patient", pick(rng, ASK_TREATMENT)))
    if treat or recipe or dose:
        parts, refs = [], []
        if treat:
            parts.append(pick(rng, TREATMENT_LEADS) + "\n" + excerpt(treat[2], 700, 6)); refs.append(treat[:2])
        if recipe:
            parts.append(pick(rng, RECIPE_LEADS) + "\n" + excerpt(recipe[2], 600, 5)); refs.append(recipe[:2])
        if dose:
            parts.append(pick(rng, DOSE_LEADS) + " " + excerpt(dose[2], 300, 3)); refs.append(dose[:2])
        turns.append(Turn("hakeem", "\n\n".join(parts), refs))
    else:
        turns.append(Turn("hakeem", NO_TREATMENT_LINE))
    if diet:
        turns.append(Turn("patient", pick(rng, ASK_DIET)))
        turns.append(Turn("hakeem", pick(rng, DIET_LEADS) + "\n" + excerpt(diet[2], 600, 6), [diet[:2]]))
    all_refs = [r for x in turns for r in x.refs]
    pages = sorted({p for (j, si) in all_refs for p in topics[j].sections[si].pages} | set(t.pages))
    turns.append(Turn("patient", pick(rng, PATIENT_THANKS)))
    turns.append(Turn("hakeem", SAFETY_CLOSE.format(book=BOOK_TITLE, volume=VOLUME_NAMES[t.volume_no], pages=page_span(pages))))
    return Conversation("consultation", ti, name, f"consultation.v{variant}", rng.randint(0, 2**31), turns,
                        pages, t.volume_no, _quality(t, pq, all_refs))


def remedy_inquiry(ti: int, t: Topic, rng: random.Random, pq: dict) -> Conversation | None:
    comp = None
    prep = None
    for i, s in enumerate(t.sections):
        if s.role == "recipe" and len(s.text) >= 20:
            if "ترکیب" in s.heading and prep is None:
                prep = (i, s.text)
            elif comp is None:
                comp = (i, s.text)
    if comp is None:
        comp = _sec(t, "overview")
    dose = _sec(t, "dosage")
    uses = _sec(t, "properties") or _sec(t, "treatment")
    if comp is None or not (dose or uses or prep):
        return None
    name = t.title
    turns = [Turn("patient", pick(rng, GREETINGS) + " " + pick(rng, REMEDY_ASK, name=name)),
             Turn("hakeem", pick(rng, REMEDY_COMPOSITION) + "\n" + excerpt(comp[1], 600, 4), [(ti, comp[0])])]
    if prep:
        turns += [Turn("patient", pick(rng, REMEDY_ASK_PREP)), Turn("hakeem", excerpt(prep[1], 700, 6), [(ti, prep[0])])]
    if dose:
        turns += [Turn("patient", pick(rng, REMEDY_ASK_DOSE)), Turn("hakeem", excerpt(dose[1], 400, 4), [(ti, dose[0])])]
    if uses:
        turns += [Turn("patient", pick(rng, REMEDY_ASK_USES)), Turn("hakeem", excerpt(uses[1], 700, 6), [(ti, uses[0])])]
    if t.tehreek:
        turns[-1].content += "\n\n" + f"یہ دوا «{t.tehreek}» تحریک کے مطابق ہے۔"
    turns.append(Turn("patient", pick(rng, PATIENT_THANKS)))
    turns.append(Turn("hakeem", SAFETY_CLOSE.format(book=BOOK_TITLE, volume=VOLUME_NAMES[t.volume_no], pages=page_span(t.pages))))
    all_refs = [r for x in turns for r in x.refs]
    return Conversation("remedy_inquiry", ti, name, "remedy_inquiry.v1", rng.randint(0, 2**31), turns,
                        t.pages, t.volume_no, _quality(t, pq, all_refs))


def qa_pairs(ti: int, t: Topic, rng: random.Random, pq: dict) -> list[Conversation]:
    out = []
    seen_roles = set()
    for si, s in enumerate(t.sections):
        if s.role not in QA_TEMPLATES or s.role in seen_roles or len(s.text) < 120:
            continue
        if s.role == "overview" and t.topic_type == "concept" and len(s.text) < 250:
            continue
        seen_roles.add(s.role)
        q = pick(rng, QA_TEMPLATES[s.role], name=t.title)
        a = pick(rng, QA_ANSWER_LEADS) + excerpt(s.text, 1000, 8)
        if t.tehreek and s.role in ("treatment", "recipe", "properties", "definition"):
            a += "\n\n" + f"(نظریہ مفرد اعضاء: «{t.tehreek}» تحریک)"
        a += f"\n\nحوالہ: {BOOK_TITLE}، {VOLUME_NAMES[t.volume_no]}، صفحہ {page_span(s.pages)}۔"
        out.append(Conversation("qa", ti, t.title, f"qa.{s.role}", rng.randint(0, 2**31),
                                [Turn("patient", q), Turn("hakeem", a, [(ti, si)])],
                                s.pages, t.volume_no, _quality(t, pq, [(ti, si)] * 4)))
    return out


def generate(topics: list[Topic], treatises: list[Treatise], page_quality: dict[tuple[int, int], float],
             seed: int = 20251116) -> list[Conversation]:
    convs: list[Conversation] = []
    for ti, t in enumerate(topics):
        if not good_title(t):
            continue
        rng = random.Random(seed * 100003 + ti)
        if t.topic_type in ("disease", "concept") and set(t.roles) & PRESENTATION and is_condition(t):
            for v in range(2):
                c = consultation(ti, topics, rng, v, page_quality)
                if c:
                    convs.append(c)
        if t.topic_type == "remedy":
            c = remedy_inquiry(ti, t, rng, page_quality)
            if c:
                convs.append(c)
        convs.extend(qa_pairs(ti, t, rng, page_quality))
    return convs
