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

from nazria_kb.engine import (VOLUME_NAMES, Assessment, EngineConfig, QuestionnaireEngine, Session, _page_ref,
                              _pages_list)
from nazria_kb.llm_engine import (EXPLAIN_ASK, EXTERNAL_NOTICE, RagResponder, explanation_context, explanation_query,
                                  is_vulnerable)
from nazria_kb.providers import ProviderError, build_provider
from nazria_kb.questionnaire import SYSTEM_ORGANS, TEHREEK_MIZAJ, Question
from nazria_kb.safety import (DISCLAIMER, HAZARD_NAMES_UR, PRACTITIONER_ONLY, RED_FLAGS, VULNERABLE_NO_RECIPE,
                              detect_red_flags, emergency_message)

from .backends import KnowledgeBase

log = logging.getLogger("consultations")

API_VERSION = 1
COMPLAINT_MIN, COMPLAINT_MAX = 2, 1000
RED_FLAG_LABELS = dict(RED_FLAGS)


class ValidationFailed(Exception):
    def __init__(self, fields: dict[str, str]):
        super().__init__("invalid answers")
        self.fields = fields


# --------------------------------------------------------------------------- questionnaire
def skip_rule(q: Question) -> dict | None:
    """When the app must not ask a question (mirrors QuestionnaireEngine._skip)."""
    return {"question_id": "age_group", "equals": "child"} if q.id == "pregnancy" else None


def questionnaire_payload(questions: list[Question]) -> dict:
    """The question bank as the app renders it. Weights and source pages stay on the server."""
    qs = [{"id": q.id, "kind": q.kind, "stage": q.stage, "text": q.text,
           "options": [{"key": o.key, "label": o.label} for o in q.options],
           "skip_if": skip_rule(q),
           "emergency_unless": ["none"] if q.id == "red_flags" else None,
           "min_length": COMPLAINT_MIN if q.kind == "text" else None,
           "max_length": COMPLAINT_MAX if q.kind == "text" else None} for q in questions]
    version = hashlib.sha256(json.dumps(qs, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:16]
    return {"version": version, "disclaimer": DISCLAIMER, "questions": qs}


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
def triage(red_flags: list[str], complaint: str | None) -> dict:
    """Quick check the app calls right after the first screen(s): stop and refer if anything is an emergency."""
    flags = [f for f in red_flags if f != "none"]
    if complaint:
        flags += [f for f in detect_red_flags(complaint) if f not in flags]
    return {"emergency": bool(flags), "flags": flags,
            "flag_labels": [RED_FLAG_LABELS.get(f, f) for f in flags],
            "message": emergency_message(flags) if flags else None}


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


def run_consultation(kb: KnowledgeBase, questions: list[Question], answers: dict) -> Outcome:
    """Replay validated answers through the questionnaire engine; returns the stored session and the API payload."""
    engine = QuestionnaireEngine(kb.retriever(), questions)
    by_id = {q.id: q for q in questions}
    s = Session(engine="questionnaire")
    reply = engine.start(s)
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
    payload = build_payload(s, s.meta.get("assessment"))
    s.result["api"] = payload                         # what GET /consultations/{id}/ returns later
    return Outcome(s, payload, s.meta.get("assessment"))


def _citation(volume: int, pages: list[int]) -> dict:
    return {"volume": volume, "volume_name": VOLUME_NAMES.get(volume, ""), "pages": list(pages),
            "text": _pages_list(volume, pages) if len(pages) > 1 else _page_ref(volume, pages)}


def build_payload(s: Session, a: Assessment | None) -> dict:
    created = datetime.now(timezone.utc).isoformat(timespec="seconds")
    if s.status == "emergency":
        flags = s.result.get("red_flags", [])
        return {"status": "emergency", "created_at": created,
                "emergency": {"flags": flags, "flag_labels": [RED_FLAG_LABELS.get(f, f) for f in flags],
                              "message": emergency_message(flags)},
                "assessment": None, "book": None, "advice": [], "disclaimer": DISCLAIMER,
                "text": s.transcript[-1]["content"]}
    sc = a.score
    evidence = [{"question_id": qid, "option_key": key, "question": qtext, "answer": label, "system": system,
                 "citation": _citation(2, pages)}
                for (qtext, label, system, pages), (qid, key) in zip(sc.evidence, sc.evidence_keys)]
    assessment = {
        "conclusive": sc.conclusive, "primary_system": sc.primary,
        "primary_organs": SYSTEM_ORGANS.get(sc.primary) if sc.primary else None,
        "secondary_system": sc.secondary, "tehreek": sc.tehreek,
        "mizaj": TEHREEK_MIZAJ.get(sc.tehreek) if sc.tehreek else None,
        "confidence": sc.confidence, "totals": sc.totals, "evidence": evidence, "vulnerable": a.vulnerable,
    }
    book = None
    if a.topic:
        recipe = None
        if a.recipe_status:
            hazards = [{"code": h, "name": HAZARD_NAMES_UR.get(h, h)} for h in a.hazards]
            message = (VULNERABLE_NO_RECIPE if a.recipe_status == "withheld_vulnerable" else
                       PRACTITIONER_ONLY.format(items="، ".join(HAZARD_NAMES_UR[x] for x in a.hazards))
                       if a.recipe_status == "withheld_hazard" else None)
            recipe = {"status": a.recipe_status, "text": a.recipe, "dosage": a.dosage, "hazards": hazards,
                      "message": message}
        book = {"topic": {"id": a.topic.topic_id, "title": a.topic.title,
                          "citation": _citation(a.topic.volume_no, a.topic.pages)},
                "description": a.description, "recipe": recipe, "diet": a.diet, "passages": []}
    elif a.passages:
        book = {"topic": None, "description": None, "recipe": None, "diet": None,
                "passages": [{"context": p.context, "excerpt": ex, "citation": _citation(p.volume_no, p.pages)}
                             for p, ex in a.passages]}
    from nazria_kb.engine import CHRONIC_ADVICE
    return {"status": "completed", "created_at": created, "emergency": None, "assessment": assessment, "book": book,
            "advice": [CHRONIC_ADVICE] if a.chronic else [], "disclaimer": DISCLAIMER,
            "text": s.transcript[-1]["content"]}


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


def explain(kb: KnowledgeBase, s: Session) -> dict:
    """Ask the configured AI provider to explain a stored result in Urdu, from book passages only.

    status: shown | not_covered | rejected | unavailable | disabled. Only ``shown`` has text. A shown explanation
    is stored and returned again on later calls without a new AI request."""
    stored = s.result.get("explanation")
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
                               query=explanation_query(s) or EXPLAIN_ASK)
    except ProviderError as e:
        log.warning("explanation failed: %s", e.kind)
        return {"status": "unavailable", "reason": e.kind, "retryable": bool(e.retryable)}
    base = {"provider": ans.meta.get("provider") or provider.name, "model": ans.meta.get("model") or provider.model,
            "external_provider": bool(provider.external),
            "notice": EXTERNAL_NOTICE.format(provider=provider.name) if provider.external else None}
    if ans.kind == "llm":
        result = {"status": "shown", "text": ans.meta.get("body") or ans.text, "sources": [
            {"context": src["context"], "citation": _citation(src["volume"], src["pages"])}
            for src in ans.meta.get("sources", [])], **base}
        s.transcript.append({"role": "hakeem", "content": "وضاحت:\n" + ans.text, "question_id": None,
                             **{k: ans.meta[k] for k in ("prompt_tokens", "completion_tokens", "latency_ms",
                                                          "source_chunk_ids") if ans.meta.get(k) is not None}})
        s.engine, s.provider, s.model = "hybrid", base["provider"], base["model"]
        s.external_provider = s.external_provider or base["external_provider"]
    elif ans.kind == "not_covered":
        result = {"status": "not_covered", "reason": "the book passages found do not answer this", **base}
    else:
        reason = ans.meta.get("degenerate") and "unusable_output" or (
            "no_valid_citation" if ans.meta.get("citation_missing") else ans.kind)
        result = {"status": "rejected", "reason": reason, **base}
    s.result["explanation"] = result
    kb.save_session(s)
    return result
