"""AI reviewer (LLM-as-judge) for the generated conversations and a report on the questionnaire weights.

    python -m nazria_kb review --provider local --limit 200            # conversations (hazard-flagged first)
    python -m nazria_kb review --provider local --weights-only         # questionnaire-weights REPORT only

Conversations: each one is judged against the knowledge chunks its Hakeem turns were generated from:
groundedness, citation correctness, safety (hazardous recipes, missing referral) and Urdu quality. Deterministic
checks run as well and can only make the verdict stricter. Results go to ``nazria.conversation_reviews`` with
``reviewer_type='ai'`` and ``reviewer='ai:<provider>/<model>'``. The run is resumable (already reviewed
conversations are skipped), capped by ``--limit`` and uses temperature 0. It never overwrites a human review
(guarded three times: the selection, the upsert's WHERE clause and the table trigger).

Weights: each scored questionnaire option is checked against the book pages it cites. The result is a markdown
REPORT for the Hakeem; weights are never changed automatically.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

from .normalize import to_latin_digits
from .providers import LLMProvider, ProviderError, default_max_tokens
from .questionnaire import Question
from .safety import hazard_flags

log = logging.getLogger("nazria_kb.reviewer")

PROMPT_VERSION = "conv-judge-v1"
WEIGHTS_PROMPT_VERSION = "weights-judge-v1"
STATUSES = ("approved", "needs_edit", "rejected")
_SEVERITY = {s: i for i, s in enumerate(STATUSES)}
REFERRAL_RE = re.compile(r"حکیم|ڈاکٹر|ہسپتال|معالج")
PAGE_LIST_RE = re.compile(r"صفح(?:ہ|ات)\s*([0-9۰-۹][0-9۰-۹،,\s–\-]*)")

JUDGE_SYSTEM = """You are a strict medical-content reviewer for an Urdu dataset of Hakeem–patient conversations
generated from the book «کلیات تحقیقات صابر ملتانی». Judge the CONVERSATION only against the SOURCE PASSAGES given.
Check:
1. groundedness – is every Hakeem statement supported by the source passages? (1 = mostly unsupported … 5 = fully supported)
2. citations_correct – do the volume/page references in the Hakeem turns match the passages' pages?
3. safety – does the Hakeem give a hazardous recipe (arsenic/سنکھیا, mercury/پارہ/شنگرف, کشتہ, کچلہ, افیون, بھنگ,
   دھتورا …) to a patient, or end without advising a qualified Hakeem/doctor? ("ok", "hazardous_recipe",
   "missing_referral" or "other")
4. urdu_quality – grammar, clarity, natural phrasing (1 … 5)
Then choose status: "approved" (usable as training data as is), "needs_edit" (fixable) or "rejected".
Reply with ONE JSON object and nothing else:
{"status": "...", "groundedness": n, "citations_correct": true|false, "safety": "...", "urdu_quality": n,
 "notes": "at most 3 short sentences, in English or Urdu"}"""

WEIGHTS_SYSTEM = """You check a diagnostic questionnaire based on the Mufrad Aza theory (اعصابی / عضلاتی / غدی)
against the pages of «کلیات تحقیقات صابر ملتانی» it cites. For the given sign and the system it is weighted toward,
decide whether the cited page text supports that link. Reply with ONE JSON object and nothing else:
{"supported": "yes"|"partly"|"no"|"not_found", "system_in_text": "اعصابی"|"عضلاتی"|"غدی"|null,
 "quote": "a short quote (max 25 words) from the page that supports your answer, or empty",
 "notes": "one or two short sentences"}"""


# --------------------------------------------------------------------------- data access
@dataclass
class Chunk:
    chunk_id: int
    context: str
    content: str
    book_id: int
    pages: list[int]


@dataclass
class ConvItem:
    uid: str
    conversation_id: int
    conv_type: str
    title: str
    book_id: int
    pages: list[int]
    hazard_flags: list[str]
    turns: list[tuple[int, str, str, list[int]]]          # (turn_index, role, content, chunk_ids)
    chunks: dict[int, Chunk] = field(default_factory=dict)


class ReviewStore(Protocol):
    def pending(self, limit: int) -> list[ConvItem]: ...

    def save(self, uid: str, status: str, reviewer: str, notes: str, details: dict) -> bool: ...


def save_ai_review(conn, uid: str, status: str, reviewer: str, notes: str, details: dict) -> bool:
    """Insert or refresh an AI review. Returns False (and writes nothing) if a human review exists."""
    from psycopg.types.json import Jsonb
    assert reviewer.startswith("ai:") and status in STATUSES
    row = conn.execute(
        """INSERT INTO nazria.conversation_reviews
               (conversation_uid, review_status, reviewer, reviewer_type, notes, ai_details, reviewed_at)
           VALUES (%s, %s, %s, 'ai', %s, %s, now())
           ON CONFLICT (conversation_uid) DO UPDATE
               SET review_status = EXCLUDED.review_status, reviewer = EXCLUDED.reviewer, reviewer_type = 'ai',
                   notes = EXCLUDED.notes, ai_details = EXCLUDED.ai_details, reviewed_at = now()
               WHERE nazria.conversation_reviews.reviewer_type = 'ai'
                  OR (nazria.conversation_reviews.review_status = 'pending_review'
                      AND nazria.conversation_reviews.reviewer IS NULL)
           RETURNING reviewer_type""", (uid, status, reviewer, notes, Jsonb({**details, "status": status}))).fetchone()
    return bool(row and row[0] == "ai")


class PostgresReviewStore:
    def __init__(self, conn):
        self.conn = conn

    def pending(self, limit: int) -> list[ConvItem]:
        rows = self.conn.execute(
            """SELECT c.conversation_uid::text, c.conversation_id, c.conv_type, c.title, c.book_id, c.pages, c.hazard_flags
               FROM nazria.conversations c
               LEFT JOIN nazria.conversation_reviews r USING (conversation_uid)
               WHERE r.conversation_uid IS NULL OR (r.review_status = 'pending_review' AND r.reviewer IS NULL)
               ORDER BY cardinality(c.hazard_flags) > 0 DESC, c.conversation_id
               LIMIT %s""", (limit,)).fetchall()
        items = []
        for uid, cid, ctype, title, book, pages, haz in rows:
            turns = [(i, r, t, list(ch)) for i, r, t, ch in self.conn.execute(
                "SELECT turn_index, role, content, source_chunk_ids FROM nazria.conversation_turns "
                "WHERE conversation_id = %s ORDER BY turn_index", (cid,))]
            ids = sorted({x for *_, ch in turns for x in ch})
            chunks = {i: Chunk(i, ctx, txt, b, list(p)) for i, ctx, txt, b, p in self.conn.execute(
                "SELECT chunk_id, context_path, content, book_id, pages FROM nazria.knowledge_chunks "
                "WHERE chunk_id = ANY(%s)", (ids,))}
            items.append(ConvItem(uid, cid, ctype, title, book, list(pages), list(haz), turns, chunks))
        return items

    def save(self, uid, status, reviewer, notes, details) -> bool:
        with self.conn.transaction():
            return save_ai_review(self.conn, uid, status, reviewer, notes, details)


# --------------------------------------------------------------------------- checks
def _pages_in(text: str) -> set[int]:
    out = set()
    for m in PAGE_LIST_RE.finditer(text):
        for a, b in re.findall(r"(\d+)(?:\s*[–\-]\s*(\d+))?", to_latin_digits(m.group(1))):
            lo, hi = int(a), int(b or a)
            if hi - lo <= 50:
                out.update(range(lo, hi + 1))
    return out


def deterministic_checks(item: ConvItem) -> dict:
    hakeem = [t for t in item.turns if t[1] == "hakeem"]
    hazards = sorted(set(item.hazard_flags) | {h for t in hakeem for h in hazard_flags(t[2])})
    source_pages = set(item.pages) | {p for c in item.chunks.values() for p in c.pages}
    cited = {p for t in hakeem for p in _pages_in(t[2])}
    return {"hazards": hazards,
            "referral_present": bool(hakeem and REFERRAL_RE.search(hakeem[-1][2])),
            "cited_pages": sorted(cited),
            "uncited_pages": sorted(cited - source_pages),
            "ungrounded_turns": [t[0] for t in hakeem[1:-1] if not t[3]] if len(hakeem) > 2 else []}


def judge_messages(item: ConvItem, max_chunk_chars: int = 1400, max_total: int = 9000) -> list[dict]:
    vol = {1: "جلد اول", 2: "جلد دوم"}
    parts, used = [], 0
    for c in item.chunks.values():
        block = f"[chunk {c.chunk_id}] «{c.context}» ({vol.get(c.book_id, c.book_id)}، صفحات {', '.join(map(str, c.pages))})\n" \
                f"{c.content[:max_chunk_chars]}"
        if used + len(block) > max_total:
            break
        parts.append(block)
        used += len(block)
    conv = "\n".join(f"{'PATIENT' if r == 'patient' else 'HAKEEM'} [{i}]: {t}" for i, r, t, _ in item.turns)
    user = (f"SOURCE PASSAGES ({vol.get(item.book_id, item.book_id)}, conversation pages "
            f"{', '.join(map(str, item.pages))}):\n\n" + ("\n\n".join(parts) or "(no passages linked)") +
            f"\n\nCONVERSATION ({item.conv_type}: {item.title}):\n{conv}")
    return [{"role": "system", "content": JUDGE_SYSTEM}, {"role": "user", "content": user}]


def parse_json_object(text: str) -> dict | None:
    """First balanced {...} object in the model output (tolerates code fences and prose)."""
    text = (text or "").strip()
    start = text.find("{")
    while start >= 0:
        depth, in_str, esc = 0, False, False
        for i in range(start, len(text)):
            ch = text[i]
            if in_str:
                esc = (ch == "\\") and not esc
                if ch == '"' and not esc:
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        obj = json.loads(text[start:i + 1])
                        return obj if isinstance(obj, dict) else None
                    except json.JSONDecodeError:
                        break
        start = text.find("{", start + 1)
    return None


def normalise_judgement(obj: dict | None) -> dict | None:
    if not obj or obj.get("status") not in STATUSES:
        return None

    def score(v):
        try:
            return max(1, min(5, int(v)))
        except (TypeError, ValueError):
            return None
    return {"status": obj["status"], "groundedness": score(obj.get("groundedness")),
            "citations_correct": bool(obj.get("citations_correct")) if obj.get("citations_correct") is not None else None,
            "safety": str(obj.get("safety") or "other")[:40], "urdu_quality": score(obj.get("urdu_quality")),
            "notes": str(obj.get("notes") or "")[:400]}


def decide(judge: dict, det: dict) -> tuple[str, list[str]]:
    """Final status: the judge's verdict, made stricter (never looser) by the deterministic checks."""
    status, reasons = judge["status"], []

    def at_least(s, why):
        nonlocal status
        if _SEVERITY[s] > _SEVERITY[status]:
            status = s
        reasons.append(why)
    if det["hazards"]:
        at_least("needs_edit", "hazardous ingredients in Hakeem turns: " + ", ".join(det["hazards"]))
    if not det["referral_present"]:
        at_least("needs_edit", "final Hakeem turn has no referral to a Hakeem/doctor")
    if det["uncited_pages"]:
        at_least("needs_edit", "cites pages outside the sources: " + ", ".join(map(str, det["uncited_pages"][:8])))
    if judge.get("safety") not in (None, "ok"):
        at_least("needs_edit", f"judge safety: {judge['safety']}")
    if judge.get("groundedness") is not None and judge["groundedness"] <= 2:
        at_least("needs_edit", f"low groundedness ({judge['groundedness']}/5)")
    if judge.get("citations_correct") is False:
        at_least("needs_edit", "judge: citations incorrect")
    return status, reasons


# --------------------------------------------------------------------------- runs
def reviewer_id(provider: LLMProvider) -> str:
    return f"ai:{provider.name}/{provider.model}"


def review_conversations(store: ReviewStore, provider: LLMProvider, limit: int, *, max_tokens: int | None = None,
                         progress=None) -> dict:
    stats = {"reviewed": 0, "skipped_human": 0, "errors": 0, "by_status": {s: 0 for s in STATUSES},
             "prompt_tokens": 0, "completion_tokens": 0, "reviewer": reviewer_id(provider)}
    for n, item in enumerate(store.pending(limit), 1):
        det = deterministic_checks(item)
        judge, comp = None, None
        msgs = judge_messages(item)
        for attempt in range(2):     # one repair attempt if the output is not valid JSON
            try:
                comp = provider.complete(msgs, max_tokens=max_tokens or default_max_tokens(), temperature=0.0)
            except ProviderError as e:
                log.warning("review %s failed: %s", item.uid, e)
                break
            judge = normalise_judgement(parse_json_object(comp.text))
            if judge:
                break
            msgs = msgs + [{"role": "assistant", "content": comp.text},
                           {"role": "user", "content": "Reply with the JSON object only."}]
        if not judge:
            stats["errors"] += 1
            continue
        status, reasons = decide(judge, det)
        notes = "; ".join(filter(None, [judge["notes"]] + reasons))[:600]
        details = {"prompt_version": PROMPT_VERSION, "judge": judge, "deterministic": det, "provider": provider.name,
                   "model": comp.model, "prompt_tokens": comp.prompt_tokens, "completion_tokens": comp.completion_tokens,
                   "latency_ms": comp.latency_ms, "reviewed_at": datetime.now(timezone.utc).isoformat()}
        if store.save(item.uid, status, reviewer_id(provider), notes, details):
            stats["reviewed"] += 1
            stats["by_status"][status] += 1
        else:
            stats["skipped_human"] += 1
        stats["prompt_tokens"] += comp.prompt_tokens or 0
        stats["completion_tokens"] += comp.completion_tokens or 0
        if progress:
            progress(n, item, status)
    return stats


# --------------------------------------------------------------------------- questionnaire weights (report only)
def fetch_pages_pg(conn, book_id: int, pages: list[int]) -> dict[int, tuple[str, str]]:
    """{cited page: (label, text)}. Looks the number up as scan page_no and as printed_page_no."""
    out = {}
    for page_no, printed, text in conn.execute(
            "SELECT page_no, printed_page_no, clean_text FROM nazria.source_pages WHERE book_id = %s AND "
            "(page_no = ANY(%s) OR printed_page_no = ANY(%s)) ORDER BY page_no", (book_id, pages, pages)):
        for p in pages:
            if p == page_no:
                out.setdefault(p, (f"scan page {page_no}", text))
            elif p == printed and p not in out:
                out[p] = (f"printed page {printed} (scan {page_no})", text)
    return out


def review_weights(questions: list[Question], fetch_pages, provider: LLMProvider, out_path: str | Path,
                   book_id: int = 2, page_chars: int = 3500, max_tokens: int | None = None) -> Path:
    rows = []
    for q in questions:
        if q.stage != "signs":
            continue
        for o in q.options:
            for system, pts in o.weights.items():
                pages = fetch_pages(o.volume or book_id, o.pages)
                text = "\n\n".join(f"--- {lbl} ---\n{t[:page_chars]}" for lbl, t in pages.values())
                if not text:
                    rows.append((q, o, system, pts, {"supported": "not_found", "notes": "cited pages not in the DB"}))
                    continue
                msgs = [{"role": "system", "content": WEIGHTS_SYSTEM},
                        {"role": "user", "content": f"Question: {q.text}\nAnswer option (sign): {o.label}\n"
                                                    f"Weighted toward: {system} (+{pts})\nCited pages (volume {o.volume}): {o.pages}\n\n{text}"}]
                try:
                    res = parse_json_object(provider.complete(msgs, max_tokens=max_tokens or default_max_tokens(), temperature=0.0).text) or \
                        {"supported": "error", "notes": "unparseable reply"}
                except ProviderError as e:
                    res = {"supported": "error", "notes": str(e)[:200]}
                rows.append((q, o, system, pts, res))
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# Questionnaire weights — AI review (report only)", "",
             f"Reviewer: `{reviewer_id(provider)}` · prompt `{WEIGHTS_PROMPT_VERSION}` · "
             f"{datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC", "",
             "**Nothing was changed.** Weights live in `nazria.questionnaire_options`; a Hakeem decides on every "
             "change (see docs/REVIEW_GUIDE.md §3).", "",
             "| question | option | weight | pages | supported | system in text | quote / notes |",
             "|---|---|---|---|---|---|---|"]
    flagged = 0
    for q, o, system, pts, r in rows:
        sup = r.get("supported", "?")
        flagged += sup not in ("yes",)
        mismatch = r.get("system_in_text") and r.get("system_in_text") != system
        cell = (r.get("quote") or "") + (" — " if r.get("quote") and r.get("notes") else "") + (r.get("notes") or "")
        lines.append(f"| `{q.id}` | {o.label} | {system} +{pts} | vol {o.volume}: {', '.join(map(str, o.pages))} | "
                     f"{'⚠️ ' if sup != 'yes' or mismatch else ''}{sup} | {r.get('system_in_text') or '—'} | "
                     f"{cell.replace('|', '/').replace(chr(10), ' ')} |")
    lines += ["", f"{len(rows)} weighted links checked; **{flagged} need a Hakeem's attention** (not 'yes')."]
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out
