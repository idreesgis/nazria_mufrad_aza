"""Book structure: treatises (running titles) -> topics -> role sections -> chunks."""
from __future__ import annotations

import difflib
import re
from collections import Counter
from dataclasses import dataclass, field

from .clean import Block, CleanPage
from .normalize import search_key

# --------------------------------------------------------------------------- roles
# Order matters: the first role whose keyword appears in a heading wins.
ROLE_KEYWORDS: list[tuple[str, tuple[str, ...]]] = [
    ("dosage", ("مقدار خوراک", "طریق استعمال", "طریقہ استعمال", "ترکیب استعمال", "مقدار", "خوراک دوا")),
    ("recipe", ("نسخہ", "نسخے", "نسخہ جات", "ترکیب تیاری", "ترکیب", "اجزاء", "اجزا", "ہوالشافی", "ھوالشافی", "ہو الشافی", "مجربات", "مجرب",
                "مرکبات", "کشتہ جات", "مفرد ادویہ", "ادویات", "ادویہ")),
    ("treatment", ("اصول علاج", "علاج", "معالجہ", "تدبیر", "تدابیر")),
    ("symptoms", ("علامات", "علامت", "نشانیاں")),
    ("causes", ("اسباب", "سبب", "وجوہات", "وجوہ")),
    ("diagnosis", ("تشخیص", "نبض", "قارورہ", "پہچان")),
    ("diet", ("پرہیز", "اغذیہ", "غذائیں", "غذا", "خوراک")),
    ("properties", ("خواص", "افعال و اثرات", "افعال", "اثرات", "فوائد", "مزاج", "رنگت", "ذائقہ", "مضر", "مصلح",
                    "بدل", "شناخت", "ماہیت دوا")),
    ("definition", ("تعریف", "تعارف", "تشریح", "ماہیت", "حقیقت", "کیفیت", "مفہوم", "اقسام")),
    ("note", ("نوٹ", "حواشی", "ہدایت", "ہدایات", "احتیاط", "تنبیہ", "ضروری")),
]
ROLE_ORDER = ["overview", "definition", "causes", "symptoms", "diagnosis", "treatment", "recipe", "dosage",
              "diet", "properties", "note"]
CONNECTORS = re.compile(r"\b(کے لیے|کے لئے|کےلئے|کا|کی|کے|میں|اور|و|سے|برائے|مرض|امراض)\b")
DOSE_UNITS_RE = re.compile(r"(رتی|ماشہ|ماشے|تولہ|تولے|گرام|چمچ|چمچہ|گولی|گولیاں|قطرے|بار|دن میں)")

REMEDY_FORMS = ("حب", "حبوب", "سفوف", "معجون", "شربت", "جوارش", "کشتہ", "روغن", "تیل", "اکسیر", "تریاق", "خمیرہ",
                "قرص", "اطریفل", "عرق", "مربہ", "لعوق", "ضماد", "مرہم", "گولیاں", "گولی", "طلاء", "سرمہ", "منجن",
                "جوشاندہ", "قہوہ", "چٹنی", "دوا", "نسخہ", "مجرب", "اکسیرِ", "ماء اللحم", "شیاف", "حقنہ", "پاک")
DISEASE_CUES = ("مرض", "امراض", "درد", "ورم", "اورام", "بخار", "حمی", "سوزش", "دق", "سل", "زکام", "نزلہ", "قبض",
                "اسہال", "پیچش", "کھانسی", "دمہ", "ضعف", "کمزوری", "سوزاک", "آتشک", "بواسیر", "جریان", "احتلام",
                "سرعت", "بانجھ", "اٹھرا", "یرقان", "ذیابیطس", "شوگر", "فالج", "لقوہ", "مرگی", "جنون", "خارش", "داد",
                "پھوڑے", "زخم", "ہیضہ", "قے", "ملیریا", "ٹی بی", "سرطان", "کینسر", "رسولی", "پتھری", "استسقاء",
                "سیلان", "حیض", "رحم", "نامردی", "ضعف باہ", "بلڈ پریشر", "دل", "جگر", "گردہ", "معدہ", "سر درد")
_CUE_RE = re.compile(r"(?:^|\s)(" + "|".join(sorted(map(re.escape, DISEASE_CUES), key=len, reverse=True)) + r")(?=$|\s)")


def has_disease_cue(title: str) -> bool:
    return bool(_CUE_RE.search(search_key(title)))


SINGLE_DRUG_TREATISES = ("خواص المفردات", "علم الادویہ", "فارما کو پیا")
NUM_WORDS = ("ایک", "دو", "تین", "چار", "پانچ", "چھ", "سات", "آٹھ", "نو", "دس", "گیارہ", "بارہ", "پندرہ", "بیس",
             "پچیس", "تیس", "چالیس", "پچاس", "ساٹھ", "سو", "نصف", "آدھا", "آدھ", "ڈیڑھ", "ڈھائی", "اڑھائی", "پاؤ", "سوا", "نیم")
UNITS = ("تولہ", "تولے", "ماشہ", "ماشے", "رتی", "رتیاں", "گرام", "کلو", "کلوگرام", "سیر", "چھٹانک", "پاؤ", "حصہ",
         "حصے", "عدد", "دانے", "دانہ", "چمچ", "چمچے", "چمچہ", "گلاس", "پیالی", "قطرے", "قطرہ", "ملی لیٹر", "لیٹر",
         "اونس", "درم", "مثقال", "اوقیہ", "من", "گولی", "گولیاں", "بوتل", "کپ")
QUANTITY_RE = re.compile(
    rf"((?:\d+(?:[./]\d+)?|{'|'.join(NUM_WORDS)})(?:\s+(?:{'|'.join(NUM_WORDS)}))?\s*(?:{'|'.join(sorted(UNITS, key=len, reverse=True))}))(?=$|[\s،,۔)])")


TITLE_NUMBERING_RE = re.compile(r"^\s*(?:[①-⑳❶-❿]|[0-9\u06f0-\u06f9]{1,3}\s*[-۔.)]|\(?[0-9\u06f0-\u06f9]{1,3}\))\s*")


def clean_title(title: str) -> str:
    return TITLE_NUMBERING_RE.sub("", title).strip(" -:،") or title


def classify_role(heading: str) -> str | None:
    k = search_key(heading)
    for role, words in ROLE_KEYWORDS:
        for w in words:
            if re.search(rf"(^|\s){re.escape(w)}($|\s)", k):
                return role
    return None


def heading_subject(heading: str, role: str | None) -> str:
    """'آتشک کے اسباب' -> 'آتشک';  'جریان کے لیے مفرد ادویہ' -> 'جریان'."""
    k = search_key(heading)
    if role:
        for r, words in ROLE_KEYWORDS:
            if r == role:
                for w in sorted(words, key=len, reverse=True):
                    k = re.sub(rf"(^|\s){re.escape(w)}($|\s)", " ", k)
    k = CONNECTORS.sub(" ", k)
    return re.sub(r"\s+", " ", k).strip()


def detect_tehreek(text: str) -> tuple[str | None, dict[str, int]]:
    """Mufrad Aza tehreek (organ-system combination) mentions, e.g. 'عضلاتی اعصابی'."""
    counts: Counter[str] = Counter()
    for m in re.finditer(r"(اعصابی|عضلاتی|غدی)[\s\-]+(اعصابی|عضلاتی|غدی)", text):
        if m.group(1) != m.group(2):
            counts[f"{m.group(1)} {m.group(2)}"] += 1
    for s in ("اعصابی", "عضلاتی", "غدی"):
        counts[s] = len(re.findall(s, text))
    combos = {k: v for k, v in counts.items() if " " in k}
    primary = max(combos, key=combos.get) if combos else None
    return primary, {k: v for k, v in counts.items() if v}


# --------------------------------------------------------------------------- data classes
@dataclass
class Treatise:
    ordinal: int
    volume_no: int
    title: str
    variants: list[str]
    pages: list[int] = field(default_factory=list)


@dataclass
class Section:
    role: str
    heading: str
    blocks: list[Block] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "\n\n".join(b.render() if b.kind != "para" else b.text for b in self.blocks).strip()

    @property
    def pages(self) -> list[int]:
        return sorted({p for b in self.blocks for p in b.pages})


@dataclass
class Topic:
    volume_no: int
    treatise_ordinal: int
    title: str
    sections: list[Section] = field(default_factory=list)
    topic_type: str = "concept"
    tehreek: str | None = None
    tehreek_counts: dict[str, int] = field(default_factory=dict)

    @property
    def pages(self) -> list[int]:
        return sorted({p for s in self.sections for p in s.pages})

    @property
    def roles(self) -> list[str]:
        return [s.role for s in self.sections]

    @property
    def text(self) -> str:
        return "\n\n".join((f"### {s.heading}\n\n" if s.heading else "") + s.text for s in self.sections).strip()

    def section(self, role: str) -> Section | None:
        for s in self.sections:
            if s.role == role and s.text:
                return s
        return None


@dataclass
class Chunk:
    volume_no: int
    treatise_ordinal: int
    topic_index: int
    section_index: int
    ordinal: int
    role: str
    context: str
    text: str
    pages: list[int]


# --------------------------------------------------------------------------- treatises
def assign_treatises(pages: list[CleanPage]) -> tuple[list[Treatise], dict[tuple[int, int], int]]:
    counts = Counter(search_key(p.running_title) for p in pages if p.running_title)
    display: dict[str, Counter[str]] = {}
    for p in pages:
        if p.running_title:
            display.setdefault(search_key(p.running_title), Counter())[p.running_title] += 1
    canon = [k for k, c in counts.most_common() if c >= 8]
    # merge near-identical canonicals (OCR variants like 'میں'/'تین انسانی زہر')
    merged: dict[str, str] = {}
    for k in canon:
        target = next((c for c in merged.values() if difflib.SequenceMatcher(None, k, c).ratio() >= 0.85), None)
        merged[k] = target or k

    def resolve(raw: str | None) -> str | None:
        if not raw:
            return None
        k = search_key(raw)
        if k in merged:
            return merged[k]
        best = difflib.get_close_matches(k, canon, n=1, cutoff=0.72)
        return merged[best[0]] if best else None

    by_vol: dict[int, list[CleanPage]] = {}
    for p in pages:
        by_vol.setdefault(p.volume_no, []).append(p)

    treatises: list[Treatise] = []
    page_map: dict[tuple[int, int], int] = {}
    for vol, vpages in sorted(by_vol.items()):
        labels = [resolve(p.running_title) for p in vpages]
        # smoothing: an isolated label between two agreeing neighbours is an OCR slip
        for i in range(1, len(labels) - 1):
            if labels[i - 1] and labels[i - 1] == labels[i + 1] and labels[i] != labels[i - 1]:
                labels[i] = labels[i - 1]
        # forward fill, then back fill the front matter
        last = None
        for i, l in enumerate(labels):
            labels[i] = l or last
            last = labels[i]
        labels = _smooth_runs(labels)
        current: Treatise | None = None
        for p, l in zip(vpages, labels):
            key = l or "__front__"
            if current is None or current.variants[0] != key:
                title = "ابتدائیہ و پیش لفظ" if key == "__front__" else max(
                    (display[v] for v in display if merged.get(v) == key or v == key), key=lambda c: sum(c.values())
                ).most_common(1)[0][0]
                variants = [key] + sorted({d for v, cnt in display.items() if merged.get(v) == key for d in cnt})
                current = Treatise(len(treatises) + 1, vol, title, variants)
                treatises.append(current)
            current.pages.append(p.page_no)
            page_map[(vol, p.page_no)] = current.ordinal
    return treatises, page_map


def _smooth_runs(labels: list[str | None]) -> list[str | None]:
    """Absorb a run sandwiched between two runs of the same treatise when it is
    tiny (<=3 pages) or is an OCR variant of that treatise's title."""
    changed = True
    while changed:
        changed = False
        runs: list[list] = []  # [label, start, end)
        for i, l in enumerate(labels):
            if runs and runs[-1][0] == l:
                runs[-1][2] = i + 1
            else:
                runs.append([l, i, i + 1])
        for j in range(1, len(runs) - 1):
            prev, cur, nxt = runs[j - 1], runs[j], runs[j + 1]
            if prev[0] and prev[0] == nxt[0] and cur[0] != prev[0]:
                size = cur[2] - cur[1]
                similar = cur[0] and difflib.SequenceMatcher(None, cur[0], prev[0]).ratio() >= 0.7
                if size <= 3 or (similar and size <= 30):
                    for i in range(cur[1], cur[2]):
                        labels[i] = prev[0]
                    changed = True
                    break
    return labels


# --------------------------------------------------------------------------- topics
EXCLUDE_FLAGS = {"ocr_failed", "table_of_contents"}


def _merge_cross_page(blocks_per_page: list[list[Block]]) -> list[Block]:
    out: list[Block] = []
    for blocks in blocks_per_page:
        for j, b in enumerate(blocks):
            if (j == 0 and out and b.kind == "para" and out[-1].kind == "para"
                    and not out[-1].text.endswith(("۔", "؟", "!", ".", "?", ":"))):
                prev = out[-1]
                out[-1] = Block("para", prev.text + " " + b.text, page_no=prev.page_no, volume_no=b.volume_no,
                                extra_pages=prev.extra_pages + [b.page_no])
                continue
            out.append(Block(b.kind, b.text, b.label, b.level, b.page_no, b.volume_no, list(b.extra_pages)))
    return out


def build_topics(pages: list[CleanPage], treatises: list[Treatise], page_map: dict[tuple[int, int], int]) -> list[Topic]:
    topics: list[Topic] = []
    tr_by_ord = {t.ordinal: t for t in treatises}
    for tr in treatises:
        tpages = [p for p in pages if p.volume_no == tr.volume_no and page_map[(p.volume_no, p.page_no)] == tr.ordinal
                  and not (set(p.flags) & EXCLUDE_FLAGS)]
        stream = _merge_cross_page([p.blocks for p in tpages])
        topic = Topic(tr.volume_no, tr.ordinal, tr.title, [Section("overview", "")])

        def new_topic(title: str) -> Topic:
            t = Topic(tr.volume_no, tr.ordinal, clean_title(title), [Section("overview", "")])
            topics.append(t)
            return t

        topics.append(topic)
        for b in stream:
            if b.kind == "heading":
                role = classify_role(b.text)
                subject = heading_subject(b.text, role)
                cur_key = search_key(topic.title)
                if role and (not subject or len(subject.split()) <= 1 and subject in cur_key or subject in cur_key):
                    topic.sections.append(Section(role, b.text))
                elif role and subject:
                    topic = new_topic(subject if len(subject) > 2 else b.text)
                    topic.sections.append(Section(role, b.text))
                else:
                    topic = new_topic(b.text)
                continue
            if b.kind == "label":
                role = classify_role(b.label)
                if role == "diet" and search_key(b.label) == "خوراک" and DOSE_UNITS_RE.search(b.text):
                    role = "dosage"
                if role:
                    topic.sections.append(Section(role, b.label, [Block("para", b.text, page_no=b.page_no, volume_no=b.volume_no)]))
                    continue
            topic.sections[-1].blocks.append(b)

    # drop empty sections/topics, classify
    result: list[Topic] = []
    for t in topics:
        t.sections = [s for s in t.sections if s.text]
        if not t.sections or len(t.text) < 60:
            continue
        tr = tr_by_ord[t.treatise_ordinal]
        t.topic_type = classify_topic(t, tr.title)
        t.tehreek, t.tehreek_counts = detect_tehreek(t.text)
        result.append(t)
    return result


def classify_topic(t: Topic, treatise_title: str) -> str:
    title = search_key(t.title)
    first = title.split(" ")[0] if title else ""
    roles = set(t.roles)
    recipe_text = " ".join(s.text for s in t.sections if s.role in ("recipe", "dosage"))
    has_quantities = bool(QUANTITY_RE.search(recipe_text))
    is_disease_title = has_disease_cue(title)
    if (first in REMEDY_FORMS and (has_quantities or "recipe" in roles or "properties" in roles)) or (
            ("dosage" in roles or ("recipe" in roles and has_quantities))
            and not roles & {"symptoms", "causes"} and not is_disease_title):
        return "remedy"
    in_materia_medica = any(s in search_key(treatise_title) for s in SINGLE_DRUG_TREATISES)
    if in_materia_medica and "properties" in roles and len(title.split()) <= 4:
        return "single_drug"
    if roles & {"symptoms", "causes"} or (is_disease_title and roles & {"treatment", "recipe", "definition", "diet"}):
        return "disease"
    return "concept"


# --------------------------------------------------------------------------- chunks
SENT_SPLIT_RE = re.compile(r"(?<=[۔؟!?])\s+")


def split_sentences(text: str) -> list[str]:
    return [s.strip() for s in SENT_SPLIT_RE.split(text) if s.strip()]


def build_chunks(topics: list[Topic], treatises: list[Treatise], max_chars: int = 1400, min_chars: int = 250) -> list[Chunk]:
    tr_by_ord = {t.ordinal: t for t in treatises}
    chunks: list[Chunk] = []
    for ti, t in enumerate(topics):
        tr = tr_by_ord[t.treatise_ordinal]
        for si, s in enumerate(t.sections):
            context = " › ".join(x for x in (tr.title, t.title if t.title != tr.title else "", s.heading) if x)
            buf: list[str] = []
            pages: set[int] = set()
            ordinal = 0

            def emit() -> None:
                nonlocal ordinal
                if buf:
                    chunks.append(Chunk(t.volume_no, t.treatise_ordinal, ti, si, ordinal, s.role, context,
                                        "\n\n".join(buf).strip(), sorted(pages)))
                    ordinal += 1
                    buf.clear()
                    pages.clear()

            for b in s.blocks:
                bpages = b.pages
                piece = b.render() if b.kind != "para" else b.text
                pieces = [piece] if len(piece) <= max_chars else _split_long(piece, max_chars)
                for pc in pieces:
                    if buf and sum(len(x) for x in buf) + len(pc) > max_chars:
                        emit()
                    buf.append(pc)
                    pages |= bpages
            # merge a tiny tail into the previous chunk of the same section
            if buf and chunks and sum(len(x) for x in buf) < min_chars and chunks[-1].topic_index == ti \
                    and chunks[-1].section_index == si and len(chunks[-1].text) + len(buf[0]) < max_chars * 1.3:
                chunks[-1].text += "\n\n" + "\n\n".join(buf)
                chunks[-1].pages = sorted(set(chunks[-1].pages) | pages)
                buf.clear()
            emit()
    return chunks


def _split_long(text: str, max_chars: int) -> list[str]:
    out, cur = [], ""
    for s in split_sentences(text) or [text]:
        while len(s) > max_chars:  # no sentence boundary at all
            cut = s.rfind(" ", 0, max_chars)
            cut = cut if cut > max_chars // 2 else max_chars
            out.append((cur + " " + s[:cut]).strip()) if cur else out.append(s[:cut])
            cur, s = "", s[cut:].strip()
        if cur and len(cur) + len(s) + 1 > max_chars:
            out.append(cur)
            cur = s
        else:
            cur = (cur + " " + s).strip()
    if cur:
        out.append(cur)
    return out
