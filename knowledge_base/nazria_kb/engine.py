"""Consultation engines behind one interface.

    app / CLI ──► ConsultationEngine ──► Retriever (book knowledge) ──► PostgreSQL (nazria schema)
                      │
                      ├── QuestionnaireEngine   (rule-based, no AI provider needed – the default)
                      ├── LLMEngine             (llm_engine.py: free-text RAG over the book)
                      └── HybridEngine          (llm_engine.py: questionnaire intake + LLM explanation/follow-ups)
                                                 providers: providers.py – see docs/AI_PROVIDER_ARCHITECTURE.md

Both kinds share the safety layer (red flags, hazard filter, disclaimer) and the same Session /
Reply objects, so the app never changes when the engine or provider is switched by configuration.
"""
from __future__ import annotations

import logging
import os
import re
import uuid
from dataclasses import asdict, dataclass, field
from typing import Protocol

from .dialogues import excerpt
from .normalize import search_key, to_int
from .providers import PROVIDERS  # noqa: F401  (re-exported for backward compatibility)
from .questionnaire import DEFAULT_QUESTIONS, SYSTEM_ORGANS, TEHREEK_MIZAJ, Question, Score, score
from .safety import (DISCLAIMER, HAZARD_NAMES_UR, PRACTITIONER_ONLY, VULNERABLE_NO_RECIPE, detect_red_flags,
                     emergency_message, hazard_flags, safe_for_patient)

log = logging.getLogger("nazria_kb.engine")
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
    # [{"role","content","question_id"} + for LLM turns: provider, model, prompt_tokens, completion_tokens,
    #   latency_ms, source_chunk_ids]
    transcript: list[dict] = field(default_factory=list)
    result: dict = field(default_factory=dict)
    phase: str = "intake"                # LLM engines: intake | chat | followup | questionnaire (fallback)
    external_provider: bool = False      # patient text is sent to an external AI service
    meta: dict = field(default_factory=dict)   # engine scratch state (not stored in the DB)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Session":
        known = cls.__dataclass_fields__
        return cls(**{k: v for k, v in d.items() if k in known})


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
        a = assess(self.questions, s.answers, self.retriever)
        s.meta["assessment"] = a            # structured form for the REST API (not stored in the DB)
        text = render_assessment(a)
        s.status = "completed"
        s.result = {"outcome": "completed", "totals": a.score.totals, "primary_system": a.score.primary,
                    "tehreek": a.score.tehreek, "confidence": a.score.confidence, "conclusive": a.score.conclusive,
                    "topic_id": a.topic.topic_id if a.topic else None, "recipe_hazards": a.hazards,
                    "vulnerable": a.vulnerable}
        s.transcript.append({"role": "hakeem", "content": text, "question_id": None})
        return Reply(text, done=True, data=s.result)


# --------------------------------------------------------------------------- assessment (shared by CLI and API)
CHRONIC_ADVICE = "چونکہ تکلیف پرانی ہے، کسی مستند حکیم سے باقاعدہ معائنہ ضرور کروائیں۔"


@dataclass
class Assessment:
    """Everything a finished questionnaire produces, before it is turned into text.

    ``recipe_status``: ``shown`` | ``withheld_vulnerable`` | ``withheld_hazard`` | None (the chapter has no recipe).
    ``passages`` is used only when no chapter matched the complaint: (passage, excerpt shown to the patient)."""
    score: Score
    vulnerable: bool
    chronic: bool
    topic: TopicHit | None = None
    description: str | None = None
    recipe_status: str | None = None
    recipe: str | None = None
    dosage: str | None = None
    hazards: list[str] = field(default_factory=list)
    diet: str | None = None
    passages: list[tuple[Passage, str]] = field(default_factory=list)


def is_vulnerable_answers(answers: dict) -> bool:
    return answers.get("age_group") in ("child", "elderly") or answers.get("pregnancy") == "yes"


def assess(questions: list[Question], answers: dict, retriever: Retriever) -> Assessment:
    """Score the answers and pick what the book may show this patient (all safety filters applied here)."""
    sc = score(questions, answers)
    vulnerable = is_vulnerable_answers(answers)
    a = Assessment(sc, vulnerable, answers.get("duration") == "chronic")
    hits = retriever.topics_for(answers.get("complaint", ""), sc.primary)
    if hits:
        h = a.topic = hits[0]
        by_role: dict[str, list[tuple[str, list[int]]]] = {}
        for role, content, pages in h.sections:
            by_role.setdefault(role, []).append((content, pages))
        inline_recipe = None
        for role in ("definition", "overview", "symptoms", "causes"):
            if role in by_role:
                desc, inline_recipe = split_inline_recipe(by_role[role][0][0])
                shown = excerpt(desc, 450, 4)
                if safe_for_patient(shown, vulnerable):
                    a.description = shown
                break
        recipe = "\n".join([c for c, _ in by_role.get("recipe", [])] + ([inline_recipe] if inline_recipe else []))
        if recipe:
            a.hazards = hazard_flags(recipe)
            if vulnerable:
                a.recipe_status = "withheld_vulnerable"
            elif a.hazards:
                a.recipe_status = "withheld_hazard"
            else:
                a.recipe_status, a.recipe = "shown", excerpt(recipe, 500, 4)
                if "dosage" in by_role and not inline_recipe:
                    a.dosage = excerpt(by_role["dosage"][0][0], 250, 2)
        if "diet" in by_role:
            diet = excerpt(by_role["diet"][0][0], 400, 4)
            if safe_for_patient(diet, vulnerable):
                a.diet = diet
    else:
        # passages are unvetted book text: they pass the same hazard / vulnerable-group checks as recipes
        for p in retriever.passages(answers.get("complaint", ""), limit=4):
            ex = excerpt(p.content, 350, 3)
            if safe_for_patient(ex, vulnerable):
                a.passages.append((p, ex))
            if len(a.passages) == 2:
                break
    return a


def render_assessment(a: Assessment) -> str:
    """The Urdu result text shown by the CLI (and returned by the API as ``text``)."""
    sc = a.score
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
    if a.topic:
        h = a.topic
        lines += ["", f"کتاب میں «{h.title}» کے بارے میں ({_page_ref(h.volume_no, h.pages)}):"]
        if a.description:
            lines.append(a.description)
        if a.recipe_status == "withheld_vulnerable":
            lines += ["", VULNERABLE_NO_RECIPE]
        elif a.recipe_status == "withheld_hazard":
            lines += ["", PRACTITIONER_ONLY.format(items="، ".join(HAZARD_NAMES_UR[x] for x in a.hazards))]
        elif a.recipe_status == "shown":
            lines += ["", "کتاب میں درج نسخہ:", a.recipe]
            if a.dosage:
                lines.append("مقدار خوراک: " + a.dosage)
        if a.diet:
            lines += ["", "غذا کے بارے میں: " + a.diet]
    elif a.passages:
        lines += ["", "اس موضوع پر کتاب کے متعلقہ اقتباسات:"]
        for p, ex in a.passages:
            lines.append(f"«{p.context}» ({_page_ref(p.volume_no, p.pages)}): {ex}")
    else:
        lines += ["", "کتاب میں اس تکلیف کے بارے میں کوئی واضح باب نہیں ملا۔"]
    if a.chronic:
        lines += ["", CHRONIC_ADVICE]
    lines += ["", DISCLAIMER]
    return "\n".join(lines)


# --------------------------------------------------------------------------- configuration
ENGINES = ("questionnaire", "llm", "hybrid")


@dataclass
class EngineConfig:
    engine: str = "questionnaire"          # questionnaire (default) | llm | hybrid
    provider: str | None = None            # one of providers.PROVIDERS for llm / hybrid
    model: str | None = None
    base_url: str | None = None            # overrides the provider / local-stack default endpoint
    local_stack: str | None = None         # vllm | ollama | lmstudio | llamacpp (provider=local)
    api_key_env: str | None = None         # NAME of the env var holding the key (never the key itself)
    temperature: float = 0.2
    max_tokens: int = 1024
    timeout_s: float = 60.0
    max_retries: int = 3
    allow_external: bool = False           # NAZRIA_ALLOW_EXTERNAL_PROVIDERS
    top_k: int = 4                         # retrieved passages per turn

    @classmethod
    def from_env(cls) -> "EngineConfig":
        from .providers import DEFAULT_MODELS, DEFAULT_PROVIDER, env_flag
        e = os.environ.get
        provider = (e("NAZRIA_LLM_PROVIDER") or DEFAULT_PROVIDER).strip().lower()
        return cls(engine=(e("NAZRIA_ENGINE") or "questionnaire").strip().lower(), provider=provider,
                   model=e("NAZRIA_LLM_MODEL") or DEFAULT_MODELS.get(provider), base_url=e("NAZRIA_LLM_BASE_URL"),
                   local_stack=e("NAZRIA_LOCAL_STACK"), api_key_env=e("NAZRIA_LLM_API_KEY_ENV"),
                   temperature=float(e("NAZRIA_LLM_TEMPERATURE", "0.2")),
                   max_tokens=int(e("NAZRIA_LLM_MAX_TOKENS", "1024")),
                   timeout_s=float(e("NAZRIA_LLM_TIMEOUT_S", "60")), max_retries=int(e("NAZRIA_LLM_MAX_RETRIES", "3")),
                   allow_external=env_flag("NAZRIA_ALLOW_EXTERNAL_PROVIDERS"), top_k=int(e("NAZRIA_RAG_TOP_K", "4")))

    def provider_config(self):
        from .providers import ProviderConfig
        return ProviderConfig(provider=(self.provider or "").strip().lower(), model=self.model or "",
                              base_url=self.base_url or None, local_stack=(self.local_stack or "").strip().lower() or None,
                              api_key_env=self.api_key_env, timeout_s=self.timeout_s, max_retries=self.max_retries,
                              allow_external=self.allow_external)

    def validate(self) -> None:
        """Raises ValueError for configuration mistakes (unknown engine/provider, missing model or endpoint).
        The external-provider policy and API keys are checked when the provider is built."""
        from .providers import ProviderError
        if self.engine not in ENGINES:
            raise ValueError(f"NAZRIA_ENGINE must be one of {ENGINES}, got {self.engine!r}")
        if self.engine != "questionnaire":
            try:
                pc = self.provider_config()
                pc.allow_external = True   # policy is enforced in build_provider, not a config error
                pc.validate()
            except ProviderError as e:
                raise ValueError(str(e)) from None


def build_engine(config: EngineConfig, retriever: Retriever, questions: list[Question] | None = None,
                 provider=None) -> ConsultationEngine:
    """Engine for the configuration. If the AI engine cannot be used – a configuration mistake (unknown engine
    or provider, missing model or endpoint), the external-provider policy, a missing key or SDK – this falls back
    to the questionnaire engine with a logged warning, so a patient always gets an answer.
    ``fallback_reason`` is set on the returned engine in that case."""
    def fallback(reason: str) -> QuestionnaireEngine:
        log.warning("AI engine unavailable, using the questionnaire engine: %s", reason)
        eng = QuestionnaireEngine(retriever, questions)
        eng.fallback_reason = reason
        return eng
    if config.engine == "questionnaire":
        return QuestionnaireEngine(retriever, questions)
    try:
        config.validate()
    except ValueError as e:
        return fallback(str(e))
    from .llm_engine import HybridEngine, LLMEngine
    from .providers import ProviderError, build_provider
    if provider is None:
        try:
            provider = build_provider(config.provider_config())
        except ProviderError as e:
            return fallback(str(e))
    cls = LLMEngine if config.engine == "llm" else HybridEngine
    return cls(provider, retriever, questions, top_k=config.top_k, max_tokens=config.max_tokens,
               temperature=config.temperature)
