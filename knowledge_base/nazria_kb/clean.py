"""Page-level cleaning: strip OCR/LLM artefacts and running headers, and turn
each page into a list of typed blocks (heading / label / paragraph / list).
"""
from __future__ import annotations

import html
import re
from collections import Counter
from dataclasses import dataclass, field

from .normalize import URDU_DIGIT_RE, latin_ratio, normalize_urdu, search_key, to_int

# --------------------------------------------------------------------------- regexes
FENCE_RE = re.compile(r"^\s*```[a-zA-Z]*\s*$")
INLINE_FENCE_RE = re.compile(r"```[a-zA-Z]*")
PREAMBLE_RE = re.compile(
    r"(here is|here's|extracted text|the text (from|in) the image|markdown formatting|sure[,!]"
    r"|یہاں .{0,40}متن|یہ رہا .{0,30}متن|تصویر سے نکال)",
    re.IGNORECASE,
)
HTML_TAG_RE = re.compile(r"</?[a-zA-Z][^>]*>")
BR_RE = re.compile(r"<br\s*/?>", re.IGNORECASE)
UNCLEAR_RE = re.compile(r"\[\s*غیر\s*واضح\s*\]")
DEGENERATE_RE = re.compile(r"([-_=~*.·…])\1{5,}|(?:\.\s){5,}")
SEPARATOR_RE = re.compile(r"^\s*(\*\s*){3,}\s*$|^\s*-{3,}\s*$|^\s*_{3,}\s*$")
COLUMN_LABEL_RE = re.compile(r"^\W*(دائیں|بائیں)\s*کالم\W*$")
PAGE_NO_RE = re.compile(rf"^\W*{URDU_DIGIT_RE}{{1,4}}\W*$")
BOOK_TITLE_RE = re.compile(r"ک\S{0,3}یات\s+تحقیقات|ملتانی|ادارہ مطبوعات سلیمانی")
MD_HEADING_RE = re.compile(r"^(#{1,6})\s*(.+?)\s*#*\s*$")
FULL_BOLD_RE = re.compile(r"^\*\*(.+?)\*\*\s*[:：]?\s*$")
LABEL_RE = re.compile(r"^\*\*([^*]{1,60}?)\s*[:：]?\s*\*\*\s*[:：]?\s*(.+)$")
PLAIN_LABEL_RE = re.compile(r"^([^\s:：][^:：۔]{0,40}?)\s*[:：]\s*(.*)$")
LIST_RE = re.compile(rf"^\s*(?:[-*•▪●◦]\s+|{URDU_DIGIT_RE}{{1,3}}\s*[-۔.)]\s*|[①-⑳❶-❿]\s*)(.+)$")
TOKEN_LOOP_RE = re.compile(r"((?:\S{1,8}\s+){1,5}?)\1{9,}")
CODE_RE = re.compile(r"(\bdef\s+\w+\(|\bimport\s+\w+|\bprint\(|\breturn\b|^\s*(if|for|try|except|class)\b.*:\s*$"
                     r"|\bREST API\b|\bjson\b|\bresponse\.|^\s*[A-Za-z_]\w*\s*=\s*[A-Za-z_][\w.]*\(|\w+\.\w+\(.*\))")
LONG_LATIN_RE = re.compile(r"[A-Za-z][A-Za-z ,:;()'`\"\-.]{70,}")
SPACED_LETTERS_RE = re.compile(r"(?:(?<!\S)\S\s+){6,}")
TOC_LEADER_RE = re.compile(rf"^(\.{{2,}}|…|//)|\.{{2,}}\s*$|\s(\.{{2,}}|…)\s*{URDU_DIGIT_RE}+$")
TERMINAL = ("۔", ".", "؟", "?", "!", "،", ",", "؛")


@dataclass
class Block:
    kind: str           # heading | label | para | list
    text: str
    label: str = ""     # for kind == label: the label (e.g. "خوراک")
    level: int = 2      # for headings
    page_no: int = 0
    volume_no: int = 0
    extra_pages: list[int] = field(default_factory=list)  # pages a merged paragraph continues onto

    @property
    def pages(self) -> set[int]:
        return {self.page_no, *self.extra_pages}

    def render(self) -> str:
        if self.kind == "heading":
            return "#" * self.level + " " + self.text
        if self.kind == "label":
            return f"**{self.label}:** {self.text}".rstrip()
        if self.kind == "list":
            return "- " + self.text
        return self.text


@dataclass
class CleanPage:
    volume_no: int
    page_no: int
    blocks: list[Block]
    printed_page_no: int | None
    running_title: str | None
    flags: list[str] = field(default_factory=list)
    unclear_count: int = 0
    raw_chars: int = 0

    @property
    def text(self) -> str:
        return "\n\n".join(b.render() for b in self.blocks)

    @property
    def quality_score(self) -> float:
        s = 1.0
        s -= min(0.3, 0.05 * self.unclear_count)
        penalties = {"degenerate_output": 0.35, "near_empty": 0.3, "two_column_layout": 0.1,
                     "llm_preamble": 0.05, "high_latin_ratio": 0.15, "table_of_contents": 0.2,
                     "hallucinated_text": 0.3, "ocr_failed": 1.0}
        for f in self.flags:
            s -= penalties.get(f, 0.0)
        return round(max(0.0, s), 2)


def _strip_md(s: str) -> str:
    s = re.sub(r"^#{1,6}\s*", "", s.strip())
    s = s.replace("**", "").replace("__", "")
    s = re.sub(r"^\*\s+", "", s)
    return s.strip(" *_#:：")


def _pre_clean(raw: str, flags: list[str]) -> tuple[list[str], int]:
    text = normalize_urdu(raw)
    if "<" in text and ">" in text:
        text = BR_RE.sub("\n", text)
        text = HTML_TAG_RE.sub("", text)
        text = html.unescape(text)
    unclear = len(UNCLEAR_RE.findall(text))
    text = UNCLEAR_RE.sub("[غیر واضح]", text)
    if DEGENERATE_RE.search(text):
        if len(raw) > 10000:
            flags.append("degenerate_output")
        text = DEGENERATE_RE.sub(" … ", text)
    if TOKEN_LOOP_RE.search(text):
        # the OCR model got stuck repeating a few tokens; drop the loops
        flags.append("degenerate_output")
        text = TOKEN_LOOP_RE.sub("\n", text)
    lines = []
    in_hallucination = False
    for i, line in enumerate(text.split("\n")):
        if FENCE_RE.match(line):
            continue
        if CODE_RE.search(line) and latin_ratio(line) > 0.8:
            # invented code / English prose: drop it and the English lines that follow
            in_hallucination = True
            if "hallucinated_text" not in flags:
                flags.append("hallucinated_text")
            continue
        if in_hallucination:
            if latin_ratio(line) > 0.5 or not re.search(r"[؀-ۿ]", line):
                continue
            in_hallucination = False
        line = INLINE_FENCE_RE.sub("", line).strip()
        if i < 4 and line and PREAMBLE_RE.search(line) and len(line) < 120:
            flags.append("llm_preamble")
            continue
        if SEPARATOR_RE.match(line):
            line = ""
        if line and COLUMN_LABEL_RE.match(_strip_md(line)):
            if "two_column_layout" not in flags:
                flags.append("two_column_layout")
            continue
        lines.append(re.sub(r"[ \t]{2,}", " ", line))
    return lines, unclear


class HeaderModel:
    """Learns which short lines are *running titles* (repeated page headers)."""

    HEADER_ZONE = 6

    def __init__(self) -> None:
        self.counts: Counter[str] = Counter()
        self.display: dict[str, str] = {}

    @staticmethod
    def _candidate(line: str) -> str | None:
        s = _strip_md(line)
        if not s or len(s) > 60 or PAGE_NO_RE.match(s) or s.endswith(("۔",)):
            return None
        return search_key(s)

    def fit(self, raw_texts: list[str]) -> "HeaderModel":
        for raw in raw_texts:
            lines, _ = _pre_clean(raw, [])
            nonempty = [l for l in lines if l.strip()][: self.HEADER_ZONE]
            for l in nonempty:
                k = self._candidate(l)
                if k and not BOOK_TITLE_RE.search(k):
                    self.counts[k] += 1
                    self.display.setdefault(k, _strip_md(l))
        return self

    def is_running_title(self, line: str) -> bool:
        k = self._candidate(line)
        if not k:
            return False
        if k.startswith("تحقیقات") and len(k) < 45:
            return True
        n = self.counts.get(k, 0)
        if n < 3:
            return False
        # a section heading such as 'علامات' / 'اصول علاج' that merely happens to open several
        # pages is content, not a running header – unless it repeats like a real header (20+ pages)
        from .structure import classify_role  # local import: structure depends on this module
        if n < 20 and len(k.split()) <= 3 and classify_role(k):
            return False
        return True


def _is_plain_heading(line: str, prev: str, nxt: str) -> bool:
    s = line.strip()
    if not s or len(s) > 55 or len(s.split()) > 9 or s.endswith(TERMINAL) or s.startswith(("(", "[")):
        return False
    if PAGE_NO_RE.match(s) or latin_ratio(s) > 0.5:
        return False
    prev_ok = (not prev.strip()) or prev.strip().endswith(TERMINAL) or prev.strip().endswith(":")
    return prev_ok and bool(nxt.strip() or True)


def clean_page(raw: str, volume_no: int, page_no: int, headers: HeaderModel) -> CleanPage:
    flags: list[str] = []
    lines, unclear = _pre_clean(raw, flags)

    # ---- strip running headers from the head zone (and page numbers at the foot)
    printed_no: int | None = None
    running: str | None = None
    idx = [i for i, l in enumerate(lines) if l.strip()]
    for i in idx[: HeaderModel.HEADER_ZONE]:
        s = _strip_md(lines[i])
        if not s:
            continue
        if PAGE_NO_RE.match(s):
            printed_no = printed_no or to_int(s)
            lines[i] = ""
        elif BOOK_TITLE_RE.search(s) and len(s) < 70:
            lines[i] = ""
        elif headers.is_running_title(lines[i]):
            running = running or s
            lines[i] = ""
        else:
            break  # first content line reached
    for i in reversed(idx[-2:]):
        s = _strip_md(lines[i])
        if PAGE_NO_RE.match(s):
            printed_no = printed_no or to_int(s)
            lines[i] = ""
        elif BOOK_TITLE_RE.search(s) and len(s) < 50:
            lines[i] = ""
    # mid-page header pairs (page number next to a running title, e.g. two-page spreads)
    for i, l in enumerate(lines):
        s = _strip_md(l)
        if PAGE_NO_RE.match(s):
            near = [lines[j] for j in (i - 1, i + 1) if 0 <= j < len(lines)]
            if any(headers.is_running_title(n) or BOOK_TITLE_RE.search(_strip_md(n)) for n in near if n.strip()):
                lines[i] = ""
        elif headers.is_running_title(l) and len(s) < 45 and headers.counts.get(search_key(s), 0) >= 8:
            lines[i] = ""

    # ---- typed blocks
    blocks: list[Block] = []
    para: list[str] = []

    def flush() -> None:
        if para:
            blocks.append(Block("para", " ".join(para).strip(), page_no=page_no, volume_no=volume_no))
            para.clear()

    for i, line in enumerate(lines):
        s = line.strip()
        if not s:
            flush()
            continue
        prev = lines[i - 1] if i else ""
        nxt = lines[i + 1] if i + 1 < len(lines) else ""
        m = MD_HEADING_RE.match(s)
        if m:
            flush()
            t = _strip_md(m.group(2))
            if t:
                blocks.append(Block("heading", t, level=min(len(m.group(1)) + 1, 4), page_no=page_no, volume_no=volume_no))
            continue
        m = LABEL_RE.match(s)
        if m and m.group(2).strip(" *"):
            flush()
            blocks.append(Block("label", _strip_md(m.group(2)) if m.group(2).startswith("**") else m.group(2).replace("**", "").strip(),
                                label=_strip_md(m.group(1)), page_no=page_no, volume_no=volume_no))
            continue
        m = FULL_BOLD_RE.match(s)
        if m:
            flush()
            t = _strip_md(m.group(1))
            if t:
                blocks.append(Block("heading", t, level=3, page_no=page_no, volume_no=volume_no))
            continue
        m = LIST_RE.match(s)
        if m and not s.startswith("**"):
            flush()
            blocks.append(Block("list", m.group(1).replace("**", "").strip(), page_no=page_no, volume_no=volume_no))
            continue
        plain = s.replace("**", "")
        m = PLAIN_LABEL_RE.match(plain)
        if m and m.group(2).strip() and len(m.group(1).split()) <= 4 and not para:
            flush()
            blocks.append(Block("label", m.group(2).strip(), label=m.group(1).strip(), page_no=page_no, volume_no=volume_no))
            continue
        standalone = not para or (prev.strip().endswith(TERMINAL) and not nxt.strip())
        if standalone and _is_plain_heading(plain, prev, nxt):
            flush()
            blocks.append(Block("heading", plain.strip(" :"), level=3, page_no=page_no, volume_no=volume_no))
            continue
        para.append(plain)
    flush()

    # drop English-only blocks that are hallucinated prose (keep short glosses/footnotes)
    if "hallucinated_text" in flags or "degenerate_output" in flags:
        for b in blocks:
            b.text = LONG_LATIN_RE.sub(" ", b.text)
            b.text = SPACED_LETTERS_RE.sub(" ", b.text)
            b.text = re.sub(r"\s{2,}", " ", b.text).strip(" -")
        blocks = [b for b in blocks if b.text and not (len(b.text) > 60 and latin_ratio(b.text) > 0.85)]
    body = " ".join(b.text for b in blocks)
    if len(body) < 80:
        flags.append("near_empty")
        if "degenerate_output" in flags or "hallucinated_text" in flags:
            flags.append("ocr_failed")
    if latin_ratio(body) > 0.3:
        flags.append("high_latin_ratio")
    dots = sum(1 for b in blocks if "…" in b.text)
    leaders = sum(1 for b in blocks if TOC_LEADER_RE.search(b.text))
    if dots >= 5 or (leaders >= 4 and leaders >= len(blocks) * 0.4) or sum(1 for b in blocks if b.kind == "list" and re.match(rf"^{URDU_DIGIT_RE}+|^//", b.text)) >= 6:
        flags.append("table_of_contents")

    return CleanPage(volume_no, page_no, blocks, printed_no, running, sorted(set(flags)), unclear, len(raw))
