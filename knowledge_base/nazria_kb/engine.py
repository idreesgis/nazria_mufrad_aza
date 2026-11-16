"""Consultation engines behind one interface.

    app / CLI ──► ConsultationEngine ──► Retriever (book knowledge) ──► PostgreSQL (nazria schema)
                      │
                      ├── QuestionnaireEngine   (implemented: rule-based, no AI provider needed)
                      └── LLMEngine             (planned: OpenAI / DeepSeek / local OpenAI-compatible,
                                                 Claude, Gemini – see docs/AI_PROVIDER_ARCHITECTURE.md)

Both kinds share the safety layer (red flags, hazard filter, disclaimer) and the same Session /
Reply objects, so the app never changes when the engine or provider is switched by configuration.
"""
from __future__ import annotations

import os
import re
import uuid
from dataclasses import asdict, dataclass, field
from typing import Protocol

from .dialogues import excerpt
from .normalize import search_key, to_int
from .questionnaire import DEFAULT_QUESTIONS, SYSTEM_ORGANS, TEHREEK_MIZAJ, Question, score
from .safety import (DISCLAIMER, EMERGENCY_MESSAGE, HAZARD_NAMES_UR, PRACTITIONER_ONLY, SELF_HARM_MESSAGE,
                     VULNERABLE_NO_RECIPE, detect_red_flags, emergency_message, hazard_flags, safe_for_patient)

VOLUME_NAMES = {1: "جلد اول", 2: "جلد دوم"}
STOPWORDS = set("مجھے میرا میری میرے ہے ہیں ہو ہوتا ہوتی ہوتے رہتا رہتی رہتے کی کا کے کو میں سے اور بھی بہت زیادہ "
                "شکایت تکلیف مسئلہ مرض بیماری ہے؟ کیا آج کل دن سے ہفتوں مہینوں پرانی حکیم صاحب".split())


# --------------------------------------------------------------------------- shared objects
@dataclass
class Reply:
    text: str
    options: list[tuple[str, str]] | None = None   # (key, label) – numbered in the UI
    multi: bool = False
    done: bool = False
    data: dict = field(default_factory=dict)


@dataclass
class Session:
    session_uid: str = field(default_factory=lambda: str(uuid.uuid4()))
    engine: str = "questionnaire"
    provider: str | None = None
    model: str | None = None
    status: str = "in_progress"          # in_progress | completed | emergency
    step: int = 0
    answers: dict = field(default_factory=dict)
    transcript: list[dict] = field(default_factory=list)   # [{"role","content","question_id"}]
    result: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Session":
        return cls(**d)


class ConsultationEngine(Protocol):
    name: str

    def start(self, session: Session) -> Reply: ...

    def reply(self, session: Session, message: str) -> Reply: ...


# --------------------------------------------------------------------------- retrieval
@dataclass
class TopicHit:
    topic_id: int
    title: str
    volume_no: int
    pages: list[int]
    tehreek: str | None
    sections: list[tuple[str, str, list[int]]]    # (role, content, pages)


@dataclass
class Passage:
    context: str
    content: str
    volume_no: int
    pages: list[int]
    chunk_id: int | None = None


class Retriever(Protocol):
    def topics_for(self, complaint: str, system: str | None, limit: int = 3) -> list[TopicHit]: ...

    def passages(self, query: str, limit: int = 3) -> list[Passage]: ...


def complaint_tokens(text: str) -> list[str]:
    return [t for t in search_key(text).split() if len(t) >= 2 and t not in STOPWORDS][:8]


class PostgresRetriever:
    def __init__(self, conn):
        self.conn = conn

    def topics_for(self, complaint: str, system: str | None, limit: int = 3) -> list[TopicHit]:
        toks = complaint_tokens(complaint)
        if not toks:
            return []
        rows = self.conn.execute(
            """WITH toks AS (SELECT unnest(%(toks)s::text[]) AS tok)
               SELECT t.topic_id, t.title, t.book_id, t.pages, t.tehreek_code,
                      (SELECT count(*) FROM toks WHERE t.title_key LIKE '%%' || tok || '%%') AS hits,
                      (%(sys)s::text IS NOT NULL AND t.title_key LIKE '%%' || %(sys)s || '%%') AS sys_hit
               FROM nazria.topics t
               WHERE t.topic_type IN ('disease', 'remedy', 'concept')
                 AND EXISTS (SELECT 1 FROM toks WHERE t.title_key LIKE '%%' || tok || '%%')
               ORDER BY sys_hit DESC, hits DESC, cardinality(t.roles) DESC, t.char_count DESC
               LIMIT %(lim)s""", {"toks": toks, "sys": system, "lim": limit}).fetchall()
        hits = []
        for tid, title, vol, pages, teh, _, _ in rows:
            secs = self.conn.execute("SELECT role, content, pages FROM nazria.topic_sections WHERE topic_id=%s ORDER BY ordinal",
                                     (tid,)).fetchall()
            hits.append(TopicHit(tid, title, vol, list(pages), teh, [(r, c, list(p)) for r, c, p in secs]))
        return hits

    def passages(self, query: str, limit: int = 3) -> list[Passage]:
        toks = complaint_tokens(query)
        if not toks:
            return []
        rows = self.conn.execute(
            """SELECT context_path, content, book_id, pages, chunk_id FROM nazria.knowledge_chunks,
                      to_tsquery('simple', %s) q
               WHERE tsv @@ q ORDER BY ts_rank(tsv, q) DESC, quality_score DESC, chunk_id LIMIT %s""",
            (" | ".join(toks), limit)).fetchall()
        return [Passage(c, t, v, list(p), cid) for c, t, v, p, cid in rows]


class DatasetRetriever:
    """In-memory retriever over a built Dataset (offline use and tests)."""

    def __init__(self, ds):
        self.ds = ds

    def topics_for(self, complaint: str, system: str | None, limit: int = 3) -> list[TopicHit]:
        toks = complaint_tokens(complaint)
        scored = []
        for i, t in enumerate(self.ds.topics):
            key = search_key(t.title)
            hits = sum(1 for tok in toks if tok in key)
            if hits and t.topic_type in ("disease", "remedy", "concept"):
                scored.append(((bool(system and system in key), hits, len(set(t.roles)), len(t.text)), i, t))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [TopicHit(i, t.title, t.volume_no, t.pages, t.tehreek, [(s.role, s.text, s.pages) for s in t.sections])
                for _, i, t in scored[:limit]]

    def passages(self, query: str, limit: int = 3) -> list[Passage]:
        toks = complaint_tokens(query)
        scored = sorted(((sum(c.text.count(t) for t in toks), i, c) for i, c in enumerate(self.ds.chunks)),
                        key=lambda x: -x[0])
        return [Passage(c.context, c.text, c.volume_no, c.pages, i) for n, i, c in scored[:limit] if n]


# --------------------------------------------------------------------------- questionnaire engine
def _page_ref(volume: int, pages: list[int]) -> str:
    if not pages:
        return VOLUME_NAMES.get(volume, "")
    span = str(pages[0]) if pages[0] == pages[-1] else f"{pages[0]}–{pages[-1]}"
    return f"{VOLUME_NAMES.get(volume, '')}، صفحہ {span}"


def _pages_list(volume: int, pages: list[int]) -> str:
    return f"{VOLUME_NAMES.get(volume, '')}، صفحات " + "، ".join(str(p) for p in pages) if len(pages) > 1 \
        else _page_ref(volume, pages)


INLINE_RECIPE_RE = re.compile(r"(?:^|[\s•\-*])(?:نسخہ|ھوالشافی|ہوالشافی|ھو الشافی|اجزاء)\s*[:：]")


def split_inline_recipe(text: str) -> tuple[str, str | None]:
    """A description paragraph sometimes carries the recipe inline ('… • نسخہ: سناکی …').
    Return (description, recipe) so the recipe goes through the same safety checks."""
    m = INLINE_RECIPE_RE.search(text)
    if not m:
        return text, None
    return text[: m.start()].rstrip(" •-*\n"), text[m.start():].strip(" •-*\n")


def _parse_choice(message: str, n: int, multi: bool) -> list[int] | None:
    parts = [p for p in re.split(r"[\s,،]+", message.strip()) if p]
    idx = [to_int(p) for p in parts]
    if not idx or any(i is None or not 1 <= i <= n for i in idx) or (not multi and len(idx) != 1):
        return None
    return sorted(set(i - 1 for i in idx))


class QuestionnaireEngine:
    name = "questionnaire"

    def __init__(self, retriever: Retriever, questions: list[Question] | None = None):
        self.retriever = retriever
        self.questions = questions or DEFAULT_QUESTIONS
        self.by_id = {q.id: q for q in self.questions}

    # ---- helpers
    def _skip(self, q: Question, answers: dict) -> bool:
        return q.id == "pregnancy" and answers.get("age_group") == "child"

    def _current(self, s: Session) -> Question | None:
        while s.step < len(self.questions) and self._skip(self.questions[s.step], s.answers):
            s.step += 1
        return self.questions[s.step] if s.step < len(self.questions) else None

    def _ask(self, s: Session, q: Question, prefix: str = "") -> Reply:
        text = (prefix + "\n\n" if prefix else "") + q.text
        s.transcript.append({"role": "hakeem", "content": text, "question_id": q.id})
        opts = [(o.key, o.label) for o in q.options] or None
        return Reply(text, opts, q.kind == "multi", data={"question_id": q.id, "step": s.step})

    # ---- interface
    def start(self, s: Session) -> Reply:
        s.engine = self.name
        intro = ("السلام علیکم! میں نظریہ مفرد اعضاء کے مطابق چند سوالات کے ذریعے آپ کی رہنمائی کروں گا۔\n" + DISCLAIMER)
        return self._ask(s, self._current(s), intro)

    def reply(self, s: Session, message: str) -> Reply:
        if s.status != "in_progress":
            return Reply("یہ مشاورت مکمل ہو چکی ہے۔ نئی مشاورت شروع کریں۔", done=True, data=s.result)
        q = self._current(s)
        s.transcript.append({"role": "patient", "content": message, "question_id": q.id})
        if q.kind == "text":
            if len(message.strip()) < 2:
                return self._ask(s, q, "براہ کرم اپنی تکلیف چند الفاظ میں لکھیں۔")
            s.answers[q.id] = message.strip()
            flags = detect_red_flags(message)
            if flags:   # free text is screened too, not only the numbered triage question
                return self._emergency(s, flags)
        else:
            chosen = _parse_choice(message, len(q.options), q.kind == "multi")
            if chosen is None:
                return self._ask(s, q, f"براہ کرم 1 سے {len(q.options)} تک کا نمبر لکھیں۔")
            keys = [q.options[i].key for i in chosen]
            if q.kind == "multi":
                keys = [k for k in keys if k != "none"] or ["none"]
                s.answers[q.id] = keys
            else:
                s.answers[q.id] = keys[0]
        # triage stops the consultation immediately
        if q.id == "red_flags" and s.answers["red_flags"] != ["none"]:
            return self._emergency(s, s.answers["red_flags"])
        s.step += 1
        nxt = self._current(s)
        if nxt:
            return self._ask(s, nxt)
        return self._finish(s)

    def _emergency(self, s: Session, flags: list[str]) -> Reply:
        s.status = "emergency"
        msg = emergency_message(flags)
        s.result = {"outcome": "emergency_referral", "red_flags": flags}
        s.transcript.append({"role": "hakeem", "content": msg, "question_id": None})
        return Reply(msg, done=True, data=s.result)

    def _finish(self, s: Session) -> Reply:
        sc = score(self.questions, s.answers)
        a = s.answers
        vulnerable = a.get("age_group") in ("child", "elderly") or a.get("pregnancy") == "yes"
        lines = ["شکریہ۔ آپ کے جوابات کی بنیاد پر:"]
        if sc.conclusive:
            lines.append(f"• غالب نظام: {sc.primary} ({SYSTEM_ORGANS[sc.primary]})")
            if sc.tehreek:
                lines.append(f"• اندازاً تحریک: «{sc.tehreek}» — مزاج: {TEHREEK_MIZAJ[sc.tehreek]}")
            lines.append("• یہ نتیجہ ان علامات سے اخذ کیا گیا:")
            for qtext, label, system, pages in sc.evidence:
                shown = f"{qtext.rstrip('؟?')}: {label}" if label in ("ہاں", "نہیں") else label
                lines.append(f"   - {shown} → {system} ({_pages_list(2, pages)})")
        else:
            lines.append("• آپ کے جوابات سے کوئی واضح تحریک ظاہر نہیں ہوتی۔ نبض اور قارورہ کا براہ راست معائنہ ضروری ہے۔")

        hits = self.retriever.topics_for(a.get("complaint", ""), sc.primary)
        hazards: list[str] = []
        shown_topic = None
        if hits:
            h = hits[0]
            shown_topic = h.topic_id
            lines += ["", f"کتاب میں «{h.title}» کے بارے میں ({_page_ref(h.volume_no, h.pages)}):"]
            by_role: dict[str, list[tuple[str, list[int]]]] = {}
            for role, content, pages in h.sections:
                by_role.setdefault(role, []).append((content, pages))
            inline_recipe = None
            for role in ("definition", "overview", "symptoms", "causes"):
                if role in by_role:
                    desc, inline_recipe = split_inline_recipe(by_role[role][0][0])
                    shown = excerpt(desc, 450, 4)
                    if safe_for_patient(shown, vulnerable):
                        lines.append(shown)
                    break
            recipe = "\n".join([c for c, _ in by_role.get("recipe", [])] + ([inline_recipe] if inline_recipe else []))
            if recipe:
                hazards = hazard_flags(recipe)
                if vulnerable:
                    lines += ["", VULNERABLE_NO_RECIPE]
                elif hazards:
                    lines += ["", PRACTITIONER_ONLY.format(items="، ".join(HAZARD_NAMES_UR[x] for x in hazards))]
                else:
                    lines += ["", "کتاب میں درج نسخہ:", excerpt(recipe, 500, 4)]
                    if "dosage" in by_role and not inline_recipe:
                        lines.append("مقدار خوراک: " + excerpt(by_role["dosage"][0][0], 250, 2))
            if "diet" in by_role:
                diet = excerpt(by_role["diet"][0][0], 400, 4)
                if safe_for_patient(diet, vulnerable):
                    lines += ["", "غذا کے بارے میں: " + diet]
        else:
            # passages are unvetted book text: they pass the same hazard / vulnerable-group checks as recipes
            ps = [p for p in self.retriever.passages(a.get("complaint", ""), limit=4)
                  if safe_for_patient(excerpt(p.content, 350, 3), vulnerable)][:2]
            if ps:
                lines += ["", "اس موضوع پر کتاب کے متعلقہ اقتباسات:"]
                for p in ps:
                    lines.append(f"«{p.context}» ({_page_ref(p.volume_no, p.pages)}): {excerpt(p.content, 350, 3)}")
            else:
                lines += ["", "کتاب میں اس تکلیف کے بارے میں کوئی واضح باب نہیں ملا۔"]
        if a.get("duration") == "chronic":
            lines += ["", "چونکہ تکلیف پرانی ہے، کسی مستند حکیم سے باقاعدہ معائنہ ضرور کروائیں۔"]
        lines += ["", DISCLAIMER]
        text = "\n".join(lines)
        s.status = "completed"
        s.result = {"outcome": "completed", "totals": sc.totals, "primary_system": sc.primary,
                    "tehreek": sc.tehreek, "confidence": sc.confidence, "conclusive": sc.conclusive,
                    "topic_id": shown_topic, "recipe_hazards": hazards, "vulnerable": vulnerable}
        s.transcript.append({"role": "hakeem", "content": text, "question_id": None})
        return Reply(text, done=True, data=s.result)


# --------------------------------------------------------------------------- provider configuration (seam)
PROVIDERS = {
    "openai": "OpenAI Chat Completions API",
    "deepseek": "DeepSeek (OpenAI-compatible API)",
    "local": "Locally deployed model behind an OpenAI-compatible server (vLLM, Ollama, LM Studio, llama.cpp)",
    "anthropic": "Anthropic Claude Messages API",
    "gemini": "Google Gemini API",
}


@dataclass
class EngineConfig:
    engine: str = "questionnaire"          # questionnaire | llm
    provider: str | None = None            # one of PROVIDERS when engine == llm
    model: str | None = None
    base_url: str | None = None            # OpenAI-compatible endpoint for deepseek/local
    api_key_env: str | None = None         # NAME of the env var holding the key (never the key itself)
    temperature: float = 0.2
    max_tokens: int = 1024

    @classmethod
    def from_env(cls) -> "EngineConfig":
        e = os.environ.get
        return cls(engine=e("NAZRIA_ENGINE", "questionnaire"), provider=e("NAZRIA_LLM_PROVIDER"),
                   model=e("NAZRIA_LLM_MODEL"), base_url=e("NAZRIA_LLM_BASE_URL"),
                   api_key_env=e("NAZRIA_LLM_API_KEY_ENV"),
                   temperature=float(e("NAZRIA_LLM_TEMPERATURE", "0.2")),
                   max_tokens=int(e("NAZRIA_LLM_MAX_TOKENS", "1024")))

    def validate(self) -> None:
        if self.engine not in ("questionnaire", "llm"):
            raise ValueError(f"NAZRIA_ENGINE must be 'questionnaire' or 'llm', got {self.engine!r}")
        if self.engine == "llm":
            if self.provider not in PROVIDERS:
                raise ValueError(f"NAZRIA_LLM_PROVIDER must be one of {sorted(PROVIDERS)}, got {self.provider!r}")
            if not self.model:
                raise ValueError("NAZRIA_LLM_MODEL is required for the llm engine")
            if self.provider in ("deepseek", "local") and not self.base_url:
                raise ValueError("NAZRIA_LLM_BASE_URL is required for OpenAI-compatible providers")


def build_engine(config: EngineConfig, retriever: Retriever, questions: list[Question] | None = None) -> ConsultationEngine:
    config.validate()
    if config.engine == "questionnaire":
        return QuestionnaireEngine(retriever, questions)
    raise NotImplementedError(
        f"LLM engine with provider '{config.provider}' is planned but not implemented yet "
        "(see docs/AI_PROVIDER_ARCHITECTURE.md). Use NAZRIA_ENGINE=questionnaire.")
