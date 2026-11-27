"""Consultation logic for the REST API, on top of ``nazria_kb`` (nothing clinical is re-implemented here).

A consultation is evaluated by replaying the patient's answers through the same ``QuestionnaireEngine`` the CLI
uses, so the API applies exactly the same triage, scoring, book selection and safety filters, and stores the same
transcript in ``nazria.consultation_sessions`` / ``consultation_messages``.
"""
from __future__ import annotations

import hashlib
import json
import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone

from nazria_kb.engine import Assessment, EngineConfig, QuestionnaireEngine, Session, passage_title
from nazria_kb.llm_engine import (EXPLAIN_ASK, EXTERNAL_NOTICE, RagResponder, explanation_context, explanation_query,
                                  is_vulnerable)
from nazria_kb.providers import ProviderError, build_provider
from nazria_kb.questionnaire import SYSTEM_ORGANS, TEHREEK_MIZAJ, Question
from nazria_kb.safety import (CONDITION_NO_RECIPE, DISCLAIMER, HAZARD_NAMES_UR, PRACTITIONER_ONLY, RED_FLAGS,
                              TEXT_FLAG_LABELS, VULNERABLE_NO_RECIPE, detect_red_flags, emergency_message,
                              strip_references)
from nazria_kb.i18n import (DIRECTION, LANGUAGES, complaint_urdu_terms, msg, option_label, question_text, sep, system_code,
                            system_name, tehreek_code, tehreek_name, tr)

from .backends import KnowledgeBase

log = logging.getLogger("consultations")

API_VERSION = 1
COMPLAINT_MIN, COMPLAINT_MAX = 2, 1000
RED_FLAG_LABELS = {**dict(RED_FLAGS), **TEXT_FLAG_LABELS}


def flag_labels(flags: list[str], lang: str) -> list[str]:
    return [tr(RED_FLAG_LABELS.get(f, f), lang) for f in flags]


class ValidationFailed(Exception):
    def __init__(self, fields: dict[str, str]):
        super().__init__("invalid answers")
        self.fields = fields


# --------------------------------------------------------------------------- questionnaire
def skip_rule(q: Question) -> dict | None:
    """When the app must not ask a question (mirrors QuestionnaireEngine._skip)."""
    return {"question_id": "age_group", "equals": "child"} if q.id == "pregnancy" else None


def questionnaire_payload(questions: list[Question], lang: str = "ur") -> dict:
    """The question bank as the app renders it, in ur | en | ar. Weights and source pages stay on the server."""
    qs = [{"id": q.id, "kind": q.kind, "stage": q.stage, "text": question_text(q.id, q.text, lang),
           "options": [{"key": o.key, "label": option_label(q.id, o.key, o.label, lang)} for o in q.options],
           "skip_if": skip_rule(q),
           "emergency_unless": ["none"] if q.id == "red_flags" else None,
           "min_length": COMPLAINT_MIN if q.kind == "text" else None,
           "max_length": COMPLAINT_MAX if q.kind == "text" else None} for q in questions]
    version = hashlib.sha256(json.dumps(qs, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:16]
    return {"version": version, "language": lang, "direction": DIRECTION[lang], "disclaimer": tr(DISCLAIMER, lang),
            "questions": qs}


# --------------------------------------------------------------------------- validation
def validate_answers(questions: list[Question], raw: dict) -> dict:
    """App answers ({question_id: option key | [keys] | text}) -> engine answers. Raises ValidationFailed.

    An emergency answer to the triage question needs nothing else; otherwise every question is required
    except those the skip rule removes (pregnancy for children)."""
    if not isinstance(raw, dict):
        raise ValidationFailed({"answers": "must be an object {question_id: answer}"})
    by_id = {q.id: q for q in questions}
    errors: dict[str, str] = {}
    for qid in raw:
        if qid not in by_id:
            errors[qid] = "unknown question"
    answers: dict = {}
    for q in questions:
        if q.id not in raw:
            continue
        v = raw[q.id]
        keys = [o.key for o in q.options]
        if q.kind == "text":
            if not isinstance(v, str) or not (COMPLAINT_MIN <= len(v.strip()) <= COMPLAINT_MAX):
                errors[q.id] = f"text of {COMPLAINT_MIN}–{COMPLAINT_MAX} characters"
            else:
                answers[q.id] = v.strip()
        elif q.kind == "multi":
            if not isinstance(v, list) or not v or not all(isinstance(x, str) for x in v):
                errors[q.id] = f"a non-empty list of option keys: {keys}"
            elif bad := [x for x in v if x not in keys]:
                errors[q.id] = f"unknown option(s) {bad}; expected {keys}"
            else:
                answers[q.id] = list(dict.fromkeys(v))
        else:
            if not isinstance(v, str) or v not in keys:
                errors[q.id] = f"one option key: {keys}"
            else:
                answers[q.id] = v
    triage = next((q for q in questions if q.stage == "triage"), None)
    emergency = triage is not None and any(k != "none" for k in answers.get(triage.id, []))
    if not emergency and triage is not None and "complaint" in answers and detect_red_flags(answers["complaint"]):
        emergency = True                                  # the complaint itself describes an emergency
    if emergency:
        # an emergency referral is never blocked by a mistake in an answer the referral does not need
        errors = {k: v for k, v in errors.items() if triage is not None and k == triage.id}
    for q in questions:
        if q.id in answers or q.id in errors:
            continue
        if emergency and q.stage != "triage":
            continue
        rule = skip_rule(q)
        if rule and answers.get(rule["question_id"]) == rule["equals"]:
            continue
        errors[q.id] = "required"
    if errors:
        raise ValidationFailed(errors)
    return answers


# --------------------------------------------------------------------------- triage
def triage(red_flags: list[str], complaint: str | None, lang: str = "ur") -> dict:
    """Quick check the app calls right after the first screen(s): stop and refer if anything is an emergency.
    The complaint is screened in Urdu, English and Arabic."""
    flags = [f for f in red_flags if f != "none"]
    if complaint:
        flags += [f for f in detect_red_flags(complaint) if f not in flags]
    return {"emergency": bool(flags), "flags": flags, "flag_labels": flag_labels(flags, lang),
            "message": emergency_message(flags, lang) if flags else None, "language": lang}


# --------------------------------------------------------------------------- consultation
@dataclass
class Outcome:
    session: Session
    payload: dict
    assessment: Assessment | None = None
    extra: dict = field(default_factory=dict)


def _message_for(q: Question, answer) -> str:
    if q.kind == "text":
        return answer
    keys = answer if isinstance(answer, list) else [answer]
    return " ".join(str(i + 1) for i, o in enumerate(q.options) if o.key in keys)


def run_consultation(kb: KnowledgeBase, questions: list[Question], answers: dict,
                     health: dict | None = None) -> Outcome:
    """Replay validated answers through the questionnaire engine; returns the stored session and the API payload.
    ``health``: from the patient's general info, {"conditions": [keys], "caution": bool} (safety filters)."""
    engine = QuestionnaireEngine(GlossaryRetriever(kb.retriever()), questions)
    by_id = {q.id: q for q in questions}
    s = Session(engine="questionnaire")
    reply = engine.start(s)
    if health:
        s.meta["health_conditions"] = list(health.get("conditions") or [])
        s.meta["medication_caution"] = bool(health.get("caution"))
    for _ in range(len(questions) + 1):
        if reply.done:
            break
        qid = reply.data.get("question_id")
        if qid not in answers:                       # validation guarantees this never happens
            raise RuntimeError(f"no answer for {qid}")
        before = len(s.transcript)
        reply = engine.reply(s, _message_for(by_id[qid], answers[qid]))
        if not reply.done and reply.data.get("question_id") == qid and len(s.transcript) > before + 1:
            raise RuntimeError(f"engine rejected the answer to {qid}")
    if not reply.done:
        raise RuntimeError("questionnaire did not finish")
    a = s.meta.get("assessment")
    payloads = {lang: build_payload(s, a, lang) for lang in LANGUAGES}
    s.result["api"] = payloads["ur"]                  # older readers
    s.result["api_i18n"] = payloads                   # what GET /consultations/{id}/ returns, per language
    return Outcome(s, payloads["ur"], a)


class GlossaryRetriever:
    """The book is Urdu: an English or Arabic complaint also searches the Urdu words of its complaint glossary."""

    def __init__(self, inner):
        self.inner = inner

    def topics_for(self, complaint: str, system: str | None, limit: int = 3):
        extra = complaint_urdu_terms(complaint)
        return self.inner.topics_for(f"{complaint} {extra}".strip() if extra else complaint, system, limit)

    def passages(self, query: str, limit: int = 3):
        extra = complaint_urdu_terms(query)
        return self.inner.passages(f"{query} {extra}".strip() if extra else query, limit)


def payload_for(result: dict, lang: str) -> dict:
    """The stored payload in the requested language (results saved before i18n exist in Urdu only)."""
    by_lang = result.get("api_i18n") or {}
    return dict(by_lang.get(lang) or by_lang.get("ur") or result.get("api") or {})


def build_payload(s: Session, a: Assessment | None, lang: str = "ur") -> dict:
    from nazria_kb.diet import localize_plan
    from nazria_kb.engine import CHRONIC_ADVICE, render_assessment
    from nazria_kb.safety import MEDICATION_ADVICE
    created = datetime.now(timezone.utc).isoformat(timespec="seconds")
    base = {"language": lang, "direction": DIRECTION[lang], "created_at": created, "disclaimer": tr(DISCLAIMER, lang)}
    if s.status == "emergency":
        flags = s.result.get("red_flags", [])
        message = emergency_message(flags, lang)
        return {**base, "status": "emergency",
                "emergency": {"flags": flags, "flag_labels": flag_labels(flags, lang), "message": message},
                "assessment": None, "book": None, "diet_plans": [], "advice": [],
                "text": s.transcript[-1]["content"] if lang == "ur" else message}
    sc = a.score
    evidence = [{"question_id": qid, "option_key": key, "question": question_text(qid, qtext, lang),
                 "answer": option_label(qid, key, label, lang), "system": system_name(system, lang),
                 "system_code": system_code(system)}
                for (qtext, label, system, _pages), (qid, key) in zip(sc.evidence, sc.evidence_keys)]
    assessment = {
        "conclusive": sc.conclusive,
        "primary_system": system_name(sc.primary, lang), "primary_system_code": system_code(sc.primary),
        "primary_organs": tr(SYSTEM_ORGANS.get(sc.primary), lang) if sc.primary else None,
        "secondary_system": system_name(sc.secondary, lang), "secondary_system_code": system_code(sc.secondary),
        "tehreek": tehreek_name(sc.tehreek, lang), "tehreek_code": tehreek_code(sc.tehreek),
        "mizaj": tr(TEHREEK_MIZAJ.get(sc.tehreek), lang) if sc.tehreek else None,
        "confidence": sc.confidence, "totals": {system_code(k): v for k, v in sc.totals.items()},
        "evidence": evidence, "vulnerable": a.vulnerable,
    }
    book = None
    if a.topic:
        recipe = None
        if a.recipe_status:
            hazards = [{"code": h, "name": tr(HAZARD_NAMES_UR.get(h, h), lang)} for h in a.hazards]
            message = (tr(VULNERABLE_NO_RECIPE, lang) if a.recipe_status == "withheld_vulnerable" else
                       tr(CONDITION_NO_RECIPE, lang) if a.recipe_status == "withheld_condition" else
                       tr(PRACTITIONER_ONLY, lang).format(
                           items=sep(lang).join(tr(HAZARD_NAMES_UR[x], lang) for x in a.hazards))
                       if a.recipe_status == "withheld_hazard" else None)
            recipe = {"status": a.recipe_status, "text": a.recipe, "dosage": a.dosage, "hazards": hazards,
                      "message": message}
        book = {"language": "ur", "topic": {"id": a.topic.topic_id, "title": a.topic.title},
                "description": a.description, "recipe": recipe, "diet": a.diet, "passages": []}
    elif a.passages:
        book = {"language": "ur", "topic": None, "description": None, "recipe": None, "diet": None,
                "passages": [{"title": passage_title(p.context), "excerpt": ex} for p, ex in a.passages]}
    advice = ([tr(CHRONIC_ADVICE, lang)] if a.chronic else []) + ([tr(MEDICATION_ADVICE, lang)] if a.caution else [])
    return {**base, "status": "completed", "emergency": None, "assessment": assessment, "book": book,
            "diet_plans": [localize_plan(p, lang) for p in a.diet_plans], "advice": advice,
            "text": s.transcript[-1]["content"] if lang == "ur" else render_assessment(a, lang)}


# --------------------------------------------------------------------------- AI explanation
_provider_lock = threading.Lock()
_provider_cache: dict[tuple, object] = {}
_provider_override = None


def set_provider(provider) -> None:
    """Use this provider for explanations (tests); None restores the configured one."""
    global _provider_override
    _provider_override = provider
    _provider_cache.clear()


def explanation_config() -> EngineConfig:
    return EngineConfig.from_env()


def explanation_enabled() -> bool:
    return explanation_config().engine in ("hybrid", "llm")


def _provider(cfg: EngineConfig):
    if _provider_override is not None:
        return _provider_override
    pc = cfg.provider_config()
    key = (pc.provider, pc.model, pc.base_url, pc.local_stack, pc.api_key_env, pc.allow_external)
    with _provider_lock:
        if key not in _provider_cache:
            _provider_cache[key] = build_provider(pc)     # ProviderError: config / policy / key / SDK
        return _provider_cache[key]


def stored_explanation(result: dict, lang: str) -> dict | None:
    by_lang = result.get("explanations") or {}
    if lang in by_lang:
        return by_lang[lang]
    return result.get("explanation") if lang == "ur" else None        # saved before i18n: Urdu


def explain(kb: KnowledgeBase, s: Session, lang: str = "ur") -> dict:
    """Ask the configured AI provider to explain a stored result in ur | en | ar, from book passages only.

    status: shown | not_covered | rejected | unavailable | disabled. Only ``shown`` has text. A shown explanation
    is stored (per language) and returned again on later calls without a new AI request."""
    stored = stored_explanation(s.result, lang)
    if stored and stored.get("status") == "shown":
        return stored
    cfg = explanation_config()
    if cfg.engine not in ("hybrid", "llm"):
        return {"status": "disabled", "reason": "AI explanations are switched off on the server (NAZRIA_ENGINE)"}
    try:
        provider = _provider(cfg)
    except ProviderError as e:
        log.warning("explanation provider unavailable: %s", e.kind)
        return {"status": "unavailable", "reason": e.kind, "retryable": False}
    responder = RagResponder(provider, kb.retriever(), top_k=cfg.top_k, max_tokens=cfg.max_tokens,
                             temperature=cfg.temperature)
    s.meta = {}
    try:
        ans = responder.answer(s, EXPLAIN_ASK, vulnerable=is_vulnerable(s), context_note=explanation_context(s),
                               query=explanation_query(s) or EXPLAIN_ASK, language=lang)
    except ProviderError as e:
        log.warning("explanation failed: %s", e.kind)
        return {"status": "unavailable", "reason": e.kind, "retryable": bool(e.retryable)}
    base = {"provider": ans.meta.get("provider") or provider.name, "model": ans.meta.get("model") or provider.model,
            "external_provider": bool(provider.external),
            "notice": tr(EXTERNAL_NOTICE, lang).format(provider=provider.name) if provider.external else None,
            "language": lang}
    if ans.kind == "llm":
        # the citations proved the text is grounded; the patient sees it without book, author or page references
        result = {"status": "shown", "text": strip_references(ans.meta.get("body") or ans.text), **base}
        s.result["explanation_sources"] = [{"context": src["context"], "volume": src["volume"], "pages": src["pages"]}
                                           for src in ans.meta.get("sources", [])]        # kept for review only
        s.transcript.append({"role": "hakeem", "content": msg("explanation", lang) + "\n" + ans.text, "question_id": None,
                             **{k: ans.meta[k] for k in ("prompt_tokens", "completion_tokens", "latency_ms",
                                                          "source_chunk_ids") if ans.meta.get(k) is not None}})
        s.engine, s.provider, s.model = "hybrid", base["provider"], base["model"]
        s.external_provider = s.external_provider or base["external_provider"]
    elif ans.kind == "not_covered":
        result = {"status": "not_covered", "reason": "the passages found do not answer this", **base}
    else:
        reason = ans.meta.get("degenerate") and "unusable_output" or (
            "no_valid_citation" if ans.meta.get("citation_missing") else ans.kind)
        result = {"status": "rejected", "reason": reason, **base}
    s.result.setdefault("explanations", {})[lang] = result
    if lang == "ur":
        s.result["explanation"] = result
    kb.save_session(s)
    return result
