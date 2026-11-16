"""LLM-backed consultation engines (behind the same ConsultationEngine interface).

* ``LLMEngine`` ("llm"): triage + age/pregnancy intake (deterministic), then free-text questions answered by
  retrieval-augmented generation (RAG) over ``knowledge_chunks``.
* ``HybridEngine`` ("hybrid", recommended once a provider is configured): the questionnaire does triage, intake
  and the tehreek indication; the LLM then explains the result in natural Urdu and answers follow-up questions.

Every generated answer goes through ``RagResponder``:

    patient text ─► red-flag check ─► retrieve passages ─► (external provider: remove identifying details)
                ─► prompt (answer ONLY from the passages, cite جلد/صفحہ, or say [NOT_COVERED])
                ─► provider.complete ─► guard_answer (hazardous recipes → practitioner-only notice;
                   vulnerable patients → no recipes) ─► citation check (only pages that were retrieved;
                   none valid → deterministic book excerpts) ─► sources line + disclaimer/referral

Any provider failure (or any unexpected error) falls back to the questionnaire engine / deterministic book
excerpts, so the patient always gets an answer and the engine never raises.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from .dialogues import SYSTEM_PROMPT, excerpt
from .engine import (Passage, QuestionnaireEngine, Reply, Retriever, Session, _page_ref, _parse_choice)
from .normalize import search_key, to_latin_digits
from .privacy import redact_messages, redact_pii
from .providers import LLMProvider, ProviderError, classify_error
from .questionnaire import Question
from .safety import (BOOK_DISCLAIMER_LLM, emergency_message, detect_red_flags, guard_answer, hazard_flags,
                     safe_for_patient)

log = logging.getLogger("nazria_kb.llm_engine")

NOT_COVERED = "[NOT_COVERED]"
NOT_COVERED_MESSAGE = ("کتاب کے جو حصے مجھے ملے ان میں آپ کے اس سوال کا واضح جواب موجود نہیں ہے۔ "
                       "اس بارے میں براہ کرم کسی مستند حکیم سے براہ راست رجوع کریں۔")
EXTERNAL_NOTICE = ("اطلاع: آپ کے سوالات کے جواب کے لیے ایک بیرونی AI سروس ({provider}) استعمال ہو رہی ہے۔ "
                   "آپ کا نام، فون نمبر، شناختی کارڈ نمبر اور ای میل بھیجنے سے پہلے حذف کر دیے جاتے ہیں، "
                   "پھر بھی براہ کرم اپنی ذاتی معلومات نہ لکھیں۔")
AI_UNAVAILABLE = "معذرت، اس وقت AI سروس دستیاب نہیں ہے۔"
GREETING = "السلام علیکم! میں نظریہ مفرد اعضاء اور کتاب «کلیات تحقیقات صابر ملتانی» کی روشنی میں آپ کی رہنمائی کروں گا۔"
ASK_COMPLAINT = "شکریہ۔ اب اپنی تکلیف یا سوال تفصیل سے لکھیں۔ گفتگو ختم کرنے کے لیے «ختم» لکھیں۔"
FOLLOWUP_INVITE = "اگر اس بارے میں آپ کا کوئی اور سوال ہو تو لکھیں، ورنہ «ختم» لکھیں۔"
CLOSING = "اللہ آپ کو شفا دے۔"
END_WORDS = {"ختم", "بس", "شکریہ", "خدا حافظ", "اللہ حافظ", "end", "exit", "quit", "bye"}
VULNERABLE_TEXT_RE = re.compile(r"حامل[ہے]|حمل سے|دودھ پلا|میر[اے] بچ|میری بچی|بچے کے لیے|بچی کے لیے|شیر خوار|نوزائیدہ")

RAG_RULES = """
ہدایات (لازمی):
1. صرف نیچے دیے گئے «کتاب کے اقتباسات» سے جواب دیں۔ اپنی طرف سے یا عام طبی معلومات سے کوئی بات نہ لکھیں۔
2. ہر طبی بات کے ساتھ حوالہ اسی شکل میں لکھیں: (جلد دوم، صفحہ 127) — صرف وہی جلد اور صفحات جو اقتباسات کے ساتھ لکھے ہیں۔
3. اگر اقتباسات میں سوال کا جواب موجود نہ ہو تو صرف یہ لکھیں: [NOT_COVERED]
4. سنکھیا، پارہ، شنگرف، کچلہ، افیون، بھنگ، دھتورا یا کسی بھی کشتے والا نسخہ کبھی نہ لکھیں۔
5. تشخیص کا دعویٰ نہ کریں؛ آخر میں مستند حکیم سے نبض و قارورہ کے معائنے کا مشورہ دیں۔
6. جواب سادہ، شائستہ اور مختصر اردو میں دیں (زیادہ سے زیادہ 8 جملے)۔
Rules (English summary): answer ONLY from the passages; cite (جلد …، صفحہ N) for every clinical statement using only
the cited pages given; if the passages do not answer the question output exactly [NOT_COVERED]; never give hazardous
recipes; no diagnosis; answer in Urdu.
""".strip()
VULNERABLE_RULE = "7. یہ مریض بچہ، حاملہ/دودھ پلانے والی خاتون یا بزرگ ہے: کوئی نسخہ، دوا یا مقدار خوراک ہرگز نہ لکھیں۔"

_VOL = {"اول": 1, "1": 1, "دوم": 2, "2": 2}
CITATION_RE = re.compile(r"\(?\s*جلد\s*(اول|دوم|[12۱۲])\s*[،,]?\s*(?:صفحہ|صفحات|ص)\s*([0-9۰-۹]+)"
                         r"(?:\s*[–\-]\s*([0-9۰-۹]+))?\s*\)?")


def parse_citations(text: str) -> list[tuple[int, int, int, re.Match]]:
    out = []
    for m in CITATION_RE.finditer(text or ""):
        vol = _VOL.get(to_latin_digits(m.group(1)))
        a = int(to_latin_digits(m.group(2)))
        b = int(to_latin_digits(m.group(3))) if m.group(3) else a
        if vol:
            out.append((vol, min(a, b), max(a, b), m))
    return out


def check_citations(text: str, passages: list[Passage]) -> tuple[str, list[Passage], int, int]:
    """Remove citations to pages that were not retrieved. Returns (text, cited passages, n_invalid, n_valid)."""
    allowed = {(p.volume_no, pg) for p in passages for pg in p.pages}
    cited: list[Passage] = []
    invalid = valid = 0
    for vol, a, b, m in reversed(parse_citations(text)):
        pages = set(range(a, b + 1))
        if any((vol, pg) in allowed for pg in pages):
            valid += 1
            for p in passages:
                if p.volume_no == vol and pages & set(p.pages) and p not in cited:
                    cited.append(p)
        else:
            invalid += 1
            text = text[:m.start()] + text[m.end():]
    return re.sub(r"[ \t]{2,}", " ", text).strip(), list(reversed(cited)), invalid, valid


def is_vulnerable(s: Session) -> bool:
    a = s.answers
    return a.get("age_group") in ("child", "elderly") or a.get("pregnancy") == "yes" or bool(s.meta.get("vulnerable_text"))


# --------------------------------------------------------------------------- responder
@dataclass
class Answer:
    text: str
    kind: str                         # llm | not_covered | excerpt_fallback
    meta: dict = field(default_factory=dict)


class RagResponder:
    def __init__(self, provider: LLMProvider, retriever: Retriever, *, top_k: int = 4, max_tokens: int = 1024,
                 temperature: float | None = 0.2, history_messages: int = 6, passage_chars: int = 1400):
        self.provider, self.retriever = provider, retriever
        self.top_k, self.max_tokens, self.temperature = top_k, max_tokens, temperature
        self.history_messages, self.passage_chars = history_messages, passage_chars

    # ---- prompt
    def _passage_block(self, ps: list[Passage]) -> str:
        parts = []
        for i, p in enumerate(ps, 1):
            warn = ("\n(تنبیہ: اس اقتباس میں خطرناک اجزاء والا نسخہ ہے — اسے ہرگز بیان نہ کریں۔)"
                    if hazard_flags(p.content) else "")
            parts.append(f"[{i}] «{p.context}» — ({_page_ref(p.volume_no, p.pages)}){warn}\n"
                         f"{p.content[:self.passage_chars]}")
        return "کتاب کے اقتباسات:\n\n" + "\n\n".join(parts)

    def build_messages(self, s: Session, question: str, ps: list[Passage], vulnerable: bool,
                       context_note: str = "") -> list[dict]:
        rules = RAG_RULES + ("\n" + VULNERABLE_RULE if vulnerable else "")
        system = SYSTEM_PROMPT + "\n\n" + rules + (f"\n\n{context_note}" if context_note else "") + \
            "\n\n" + self._passage_block(ps)
        history = s.meta.get("chat", [])[-self.history_messages:]
        msgs = [{"role": "system", "content": system}] + [dict(m) for m in history] + \
               [{"role": "user", "content": question}]
        if self.provider.external:
            msgs, names = redact_messages(msgs, s.meta.get("pii_names"))
            s.meta["pii_names"] = names
        return msgs

    # ---- deterministic, grounded fallback
    @staticmethod
    def excerpt_answer(ps: list[Passage], vulnerable: bool, lead: str = "") -> Answer:
        lines = [lead] if lead else []
        shown = []
        for p in ps:
            ex = excerpt(p.content, 350, 3)
            if safe_for_patient(ex, vulnerable):
                shown.append(p)
                lines.append(f"«{p.context}» ({_page_ref(p.volume_no, p.pages)}): {ex}")
            if len(shown) == 2:
                break
        if not shown:
            return Answer("\n".join(lines + [NOT_COVERED_MESSAGE]).strip(), "not_covered",
                          {"source_chunk_ids": [p.chunk_id for p in ps if p.chunk_id is not None]})
        if not lead:
            lines.insert(0, "کتاب کے متعلقہ اقتباسات:")
        return Answer("\n".join(lines), "excerpt_fallback",
                      {"source_chunk_ids": [p.chunk_id for p in shown if p.chunk_id is not None]})

    # ---- main entry
    def answer(self, s: Session, question: str, *, vulnerable: bool, context_note: str = "",
               query: str | None = None) -> Answer:
        """Raises ProviderError on provider failure (the engine decides the fallback).
        ``query`` is the retrieval query (default: the question itself)."""
        ps = self.retriever.passages((query or question).strip(), limit=self.top_k)
        if not ps:
            return Answer(NOT_COVERED_MESSAGE, "not_covered", {"retrieved": 0, "source_chunk_ids": []})
        if self.provider.external and context_note:
            context_note, _ = redact_pii(context_note, s.meta.get("pii_names"))
        msgs = self.build_messages(s, question, ps, vulnerable, context_note)
        c = self.provider.complete(msgs, max_tokens=self.max_tokens, temperature=self.temperature)
        meta = {"provider": c.provider or self.provider.name, "model": c.model, "prompt_tokens": c.prompt_tokens,
                "completion_tokens": c.completion_tokens, "latency_ms": c.latency_ms, "retrieved": len(ps),
                "source_chunk_ids": [p.chunk_id for p in ps if p.chunk_id is not None]}
        raw = c.text.strip()
        if NOT_COVERED in raw:
            return Answer(NOT_COVERED_MESSAGE, "not_covered", meta)
        # citation accuracy is measured on what the model wrote, before any paragraph is removed
        _, _, meta["invalid_citations"], meta["valid_citations"] = check_citations(raw, ps)
        guarded, ginfo = guard_answer(raw, vulnerable)
        meta.update(ginfo)
        text, cited, _, _ = check_citations(guarded, ps)
        if not cited:   # an uncited answer is treated as ungrounded: show the book text itself instead
            fb = self.excerpt_answer(ps, vulnerable)
            fb.meta = {**meta, **fb.meta, "citation_missing": True}
            return fb
        meta["cited_chunk_ids"] = [p.chunk_id for p in cited if p.chunk_id is not None]
        sources = "ماخذ: " + "؛ ".join(f"«{p.context}» ({_page_ref(p.volume_no, p.pages)})" for p in cited)
        return Answer(text + "\n\n" + sources, "llm", meta)


# --------------------------------------------------------------------------- engines
class _LLMEngineBase:
    name = "llm"

    def __init__(self, provider: LLMProvider, retriever: Retriever, questions: list[Question] | None = None, *,
                 top_k: int = 4, max_tokens: int = 1024, temperature: float | None = 0.2, max_turns: int = 8):
        self.provider = provider
        self.q = QuestionnaireEngine(retriever, questions)
        self.responder = RagResponder(provider, retriever, top_k=top_k, max_tokens=max_tokens, temperature=temperature)
        self.max_turns = max_turns

    # ---- shared helpers
    def _init_session(self, s: Session) -> str:
        s.engine, s.provider, s.model = self.name, self.provider.name, self.provider.model
        s.external_provider = bool(self.provider.external)
        if s.external_provider:
            s.meta["external_notice_shown"] = True
            return EXTERNAL_NOTICE.format(provider=self.provider.name)
        return ""

    @staticmethod
    def _patient(s: Session, message: str, qid: str | None = None) -> None:
        s.transcript.append({"role": "patient", "content": message, "question_id": qid})
        if VULNERABLE_TEXT_RE.search(search_key(message)):
            s.meta["vulnerable_text"] = True

    @staticmethod
    def _hakeem(s: Session, text: str, meta: dict | None = None) -> None:
        entry = {"role": "hakeem", "content": text, "question_id": None}
        for k in ("provider", "model", "prompt_tokens", "completion_tokens", "latency_ms", "source_chunk_ids"):
            if meta and meta.get(k) is not None:
                entry[k] = meta[k]
        s.transcript.append(entry)

    def _emergency(self, s: Session, flags: list[str]) -> Reply:
        s.status, s.phase = "emergency", "done"
        s.result = {**s.result, "outcome": "emergency_referral", "red_flags": flags}
        msg = emergency_message(flags)
        self._hakeem(s, msg)
        return Reply(msg, done=True, data=s.result)

    def _close(self, s: Session, prefix: str = "") -> Reply:
        s.status, s.phase = "completed", "done"
        s.result.setdefault("outcome", "completed")
        text = (prefix + "\n\n" if prefix else "") + CLOSING + "\n" + BOOK_DISCLAIMER_LLM
        self._hakeem(s, text)
        return Reply(text, done=True, data=s.result)

    def _respond(self, s: Session, question: str, **kw) -> tuple[Answer, str | None]:
        """Generated answer, or (deterministic excerpts, error kind) if the provider fails."""
        vulnerable = is_vulnerable(s)
        try:
            ans = self.responder.answer(s, question, vulnerable=vulnerable, **kw)
            return ans, None
        except Exception as exc:  # noqa: BLE001 - a provider failure must never crash a consultation
            err = exc if isinstance(exc, ProviderError) else classify_error(self.provider.name, exc)
            log.warning("LLM answer failed, falling back: %s", err)
            return None, err.kind

    def _record_answer(self, s: Session, question: str, ans: Answer) -> str:
        text = ans.text + "\n\n" + BOOK_DISCLAIMER_LLM
        self._hakeem(s, text, ans.meta)
        chat = s.meta.setdefault("chat", [])
        chat += [{"role": "user", "content": question}, {"role": "assistant", "content": ans.text[:1500]}]
        s.meta["turns"] = s.meta.get("turns", 0) + 1
        s.result.setdefault("answers", []).append({"kind": ans.kind, **{k: ans.meta.get(k) for k in (
            "hazards", "invalid_citations", "valid_citations", "citation_missing", "cited_chunk_ids")
            if ans.meta.get(k)}})
        return text

    def _finished_reply(self) -> Reply:
        return Reply("یہ مشاورت مکمل ہو چکی ہے۔ نئی مشاورت شروع کریں۔", done=True)


class LLMEngine(_LLMEngineBase):
    """Free-text RAG consultation. Intake (triage, age group, pregnancy) stays deterministic because the
    safety rules depend on it; afterwards every patient message is answered from retrieved book passages."""
    name = "llm"
    INTAKE = ("red_flags", "age_group", "pregnancy")

    def _intake_question(self, s: Session) -> Question | None:
        i = s.meta.get("intake", 0)
        while i < len(self.INTAKE):
            q = self.q.by_id.get(self.INTAKE[i])
            if q and not (q.id == "pregnancy" and s.answers.get("age_group") == "child"):
                s.meta["intake"] = i
                return q
            i += 1
        s.meta["intake"] = i
        return None

    def start(self, s: Session) -> Reply:
        notice = self._init_session(s)
        s.phase = "intake"
        intro = "\n".join(x for x in (GREETING, BOOK_DISCLAIMER_LLM, notice) if x)
        q = self._intake_question(s)
        if q is None:
            s.phase = "chat"
            text = intro + "\n\n" + ASK_COMPLAINT
            self._hakeem(s, text)
            return Reply(text)
        return self.q._ask(s, q, intro)

    def reply(self, s: Session, message: str) -> Reply:
        try:
            return self._reply(s, message)
        except Exception as exc:  # noqa: BLE001 - last line of defence: never leave the patient without an answer
            log.exception("llm engine error, switching to the questionnaire: %s", type(exc).__name__)
            return self._to_questionnaire(s, "internal")

    def _reply(self, s: Session, message: str) -> Reply:
        if s.status != "in_progress":
            return self._finished_reply()
        if s.phase == "questionnaire":
            return self.q.reply(s, message)
        q = self._intake_question(s) if s.phase == "intake" else None
        self._patient(s, message, q.id if q else None)
        flags = detect_red_flags(message)
        if flags:
            return self._emergency(s, flags)
        if s.phase == "intake" and q is not None:
            chosen = _parse_choice(message, len(q.options), q.kind == "multi")
            if chosen is None:
                return self.q._ask(s, q, f"براہ کرم 1 سے {len(q.options)} تک کا نمبر لکھیں۔")
            keys = [q.options[i].key for i in chosen]
            if q.kind == "multi":
                s.answers[q.id] = [k for k in keys if k != "none"] or ["none"]
                if s.answers[q.id] != ["none"]:
                    return self._emergency(s, s.answers[q.id])
            else:
                s.answers[q.id] = keys[0]
            s.meta["intake"] = s.meta.get("intake", 0) + 1
            nxt = self._intake_question(s)
            if nxt:
                return self.q._ask(s, nxt)
            s.phase = "chat"
            self._hakeem(s, ASK_COMPLAINT)
            return Reply(ASK_COMPLAINT)
        # chat
        if search_key(message).lower() in END_WORDS:
            return self._close(s)
        s.answers.setdefault("complaint", message.strip())
        ans, err = self._respond(s, message)
        if ans is None:
            return self._to_questionnaire(s, err)
        text = self._record_answer(s, message, ans)
        if s.meta["turns"] >= self.max_turns:
            s.status, s.phase = "completed", "done"
            s.result.setdefault("outcome", "completed")
            return Reply(text, done=True, data=s.result)
        return Reply(text + "\n\n" + FOLLOWUP_INVITE, data={"phase": "chat"})

    def _to_questionnaire(self, s: Session, kind: str | None) -> Reply:
        """Continue the consultation with the rule-based questionnaire (answers given so far are kept)."""
        s.phase = "questionnaire"
        s.result["ai_fallback"] = kind or "unknown"
        qs = self.q.questions
        s.step = next((i for i, q in enumerate(qs) if q.id not in s.answers and not self.q._skip(q, s.answers)), len(qs))
        nxt = self.q._current(s)
        lead = AI_UNAVAILABLE + " اب میں چند سوالات کے ذریعے آپ کی رہنمائی کروں گا۔"
        if nxt is None:
            r = self.q._finish(s)
            r.text = lead + "\n\n" + r.text
            return r
        return self.q._ask(s, nxt, lead)


class HybridEngine(_LLMEngineBase):
    """Questionnaire intake and tehreek indication (deterministic), then an LLM explanation and follow-ups
    constrained to retrieved passages. Without a working provider it behaves exactly like the questionnaire."""
    name = "hybrid"

    def start(self, s: Session) -> Reply:
        notice = self._init_session(s)
        r = self.q.start(s)
        s.engine, s.phase = self.name, "intake"
        if notice:
            r.text = notice + "\n\n" + r.text
            s.transcript[-1]["content"] = r.text
        return r

    def _context_note(self, s: Session) -> str:
        res = s.result
        lines = ["سوالنامے کا نتیجہ (قواعد پر مبنی، تشخیص نہیں):",
                 f"- مریض کی شکایت: {s.answers.get('complaint', '')}"]
        if res.get("conclusive"):
            lines.append(f"- غالب نظام: {res.get('primary_system')}؛ اندازاً تحریک: {res.get('tehreek') or '—'}")
        else:
            lines.append("- کوئی واضح تحریک ظاہر نہیں ہوئی۔")
        return "\n".join(lines)

    def _query_extra(self, s: Session) -> str:
        return " ".join(x for x in (s.answers.get("complaint", ""), s.result.get("primary_system") or "") if x)

    def reply(self, s: Session, message: str) -> Reply:
        try:
            return self._reply(s, message)
        except Exception as exc:  # noqa: BLE001
            log.exception("hybrid engine error: %s", type(exc).__name__)
            if s.phase == "followup":
                return self._close(s, AI_UNAVAILABLE)
            return self.q.reply(s, message)

    def _reply(self, s: Session, message: str) -> Reply:
        if s.status != "in_progress":
            return self._finished_reply()
        if s.phase != "followup":
            r = self.q.reply(s, message)
            if s.status != "completed":
                return r                      # next question, re-ask, or emergency (done)
            return self._explain(s, r)
        self._patient(s, message)
        flags = detect_red_flags(message)
        if flags:
            return self._emergency(s, flags)
        if search_key(message).lower() in END_WORDS:
            return self._close(s)
        query = f"{message} {self._query_extra(s)}"
        ans, err = self._respond(s, message, context_note=self._context_note(s), query=query)
        if ans is None:
            ps = self.responder.retriever.passages(query, limit=4)
            ans = RagResponder.excerpt_answer(ps, is_vulnerable(s), lead=AI_UNAVAILABLE)
            s.result["ai_fallback"] = err
        text = self._record_answer(s, message, ans)
        if s.meta["turns"] >= self.max_turns:
            s.status, s.phase = "completed", "done"
            return Reply(text, done=True, data=s.result)
        return Reply(text + "\n\n" + FOLLOWUP_INVITE, data={"phase": "followup", **s.result})

    def _explain(self, s: Session, r: Reply) -> Reply:
        """Questionnaire finished: keep its deterministic summary, add the LLM explanation, open follow-ups."""
        summary_entry = s.transcript[-1]
        ask = ("سوالنامے کے اس نتیجے اور میری شکایت کو کتاب کے اقتباسات کی روشنی میں آسان اردو میں سمجھائیں۔ "
               "نسخہ دوبارہ نہ لکھیں۔")
        ans, err = self._respond(s, ask, context_note=self._context_note(s), query=self._query_extra(s) or ask)
        s.status, s.phase = "in_progress", "followup"
        if ans is None or ans.kind != "llm":
            s.result["ai_fallback" if ans is None else "ai_explanation"] = err or ans.kind
            text = r.text + "\n\n" + FOLLOWUP_INVITE
            summary_entry["content"] = text
            return Reply(text, data={"phase": "followup", **s.result})
        explanation = ans.text
        text = r.text + "\n\nوضاحت:\n" + explanation + "\n\n" + FOLLOWUP_INVITE
        summary_entry["content"] = text
        for k in ("provider", "model", "prompt_tokens", "completion_tokens", "latency_ms", "source_chunk_ids"):
            if ans.meta.get(k) is not None:
                summary_entry[k] = ans.meta[k]
        s.meta.setdefault("chat", []).extend([{"role": "user", "content": ask},
                                              {"role": "assistant", "content": explanation[:1500]}])
        return Reply(text, data={"phase": "followup", **s.result})
