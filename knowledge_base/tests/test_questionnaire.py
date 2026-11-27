"""Questionnaire engine, safety layer and provider configuration."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nazria_kb.engine import (EngineConfig, Passage, QuestionnaireEngine, Session, TopicHit,  # noqa: E402
                              build_engine, split_inline_recipe)
from nazria_kb.questionnaire import DEFAULT_QUESTIONS, SYSTEMS, score  # noqa: E402
from nazria_kb.safety import RED_FLAGS, hazard_flags  # noqa: E402

NONE_FLAG = str(len(RED_FLAGS) + 1)   # the "ان میں سے کوئی نہیں" option


class FakeRetriever:
    def __init__(self, recipe: str, inline: bool = False):
        overview = "عضلاتی قبض اکثر شدید ہوتی ہے۔ قارورہ سرخ ہوتا ہے۔"
        secs = [("overview", overview + (f" • نسخہ: {recipe}" if inline else ""), [127])]
        if not inline:
            secs.append(("recipe", recipe, [127]))
        secs.append(("diet", "ٹھنڈی اشیاء سے پرہیز کریں۔", [127]))
        self.hit = TopicHit(1, "عضلاتی قبض", 2, [127], None, secs)
        self.calls = []

    def topics_for(self, complaint, system, limit=3):
        self.calls.append((complaint, system))
        return [self.hit]

    def passages(self, query, limit=3):
        return [Passage("ctx", "متن", 2, [1])]


def run(engine, answers):
    s = Session()
    r = engine.start(s)
    for a in answers:
        assert not r.done
        r = engine.reply(s, a)
    return s, r


# urine red, constipation, dry, gas, sour, heart yes, burning no, catarrh no, phlegm none
# appetite .. other_signs: normal / none
MUSCULAR = [NONE_FLAG, "قبض", "3", "2", "3", "1", "1", "1", "1", "1", "1", "2", "2", "4",
            "3", "2", "3", "4", "7", "3", "3", "9"]


def test_every_scored_option_cites_pages_and_valid_system():
    for q in DEFAULT_QUESTIONS:
        for o in q.options:
            assert set(o.weights) <= set(SYSTEMS)
            if o.weights:
                assert o.pages, f"{q.id}/{o.key} has weights but no source page"


def test_scoring_muscular_and_inconclusive():
    sc = score(DEFAULT_QUESTIONS, {"urine_color": "red", "bowel": "constipation", "body": "heat"})
    assert sc.primary == "عضلاتی" and sc.secondary == "غدی" and sc.tehreek == "عضلاتی غدی"
    tie = score(DEFAULT_QUESTIONS, {"urine_color": "red", "bowel": "incomplete"})
    assert not tie.conclusive and tie.primary is None
    assert not score(DEFAULT_QUESTIONS, {"heart": "yes"}).conclusive   # below minimum evidence


def test_full_consultation_shows_safe_recipe_with_citations():
    ret = FakeRetriever("سناکی، تیز پات۔ دونوں ہم وزن سفوف کر لیں۔")
    s, r = run(QuestionnaireEngine(ret), MUSCULAR)
    assert r.done and s.status == "completed"
    assert s.result["primary_system"] == "عضلاتی" and s.result["conclusive"]
    assert ret.calls[0] == ("قبض", "عضلاتی")
    assert "سناکی" in r.text and "صفحہ 127" in r.text and "مستند حکیم" in r.text
    roles = [m["role"] for m in s.transcript]
    assert roles[0] == "hakeem" and all(a != b for a, b in zip(roles, roles[1:]))


def test_hazardous_recipe_is_withheld():
    ret = FakeRetriever("کشتہ نیلا طوطیہ دو حصے، کشتہ سنکھیا ایک حصہ")
    s, r = run(QuestionnaireEngine(ret), MUSCULAR)
    assert "سنکھیا ایک حصہ" not in r.text and "نگرانی" in r.text
    assert set(s.result["recipe_hazards"]) == {"arsenic", "copper_sulphate", "kushta"}


def test_inline_recipe_also_goes_through_safety():
    ret = FakeRetriever("کشتہ شنگرف دو حصے", inline=True)
    _, r = run(QuestionnaireEngine(ret), MUSCULAR)
    assert "شنگرف دو حصے" not in r.text and "نگرانی" in r.text
    assert split_inline_recipe("بیان۔ • نسخہ: سونف") == ("بیان۔", "نسخہ: سونف")


def test_vulnerable_patients_get_no_recipe():
    pregnant = MUSCULAR.copy()
    pregnant[4] = "1"   # pregnancy: yes
    _, r = run(QuestionnaireEngine(FakeRetriever("سونف دو حصے")), pregnant)
    assert "سونف دو حصے" not in r.text and "حاملہ" in r.text
    child = [NONE_FLAG, "قبض", "1", "1"] + MUSCULAR[5:]   # age child -> pregnancy question skipped
    s, r = run(QuestionnaireEngine(FakeRetriever("سونف دو حصے")), child)
    assert "pregnancy" not in s.answers and s.result["vulnerable"] and "سونف دو حصے" not in r.text


def test_red_flag_stops_immediately():
    s, r = run(QuestionnaireEngine(FakeRetriever("x")), ["1"])
    assert r.done and s.status == "emergency" and "ہسپتال" in r.text
    s, r = run(QuestionnaireEngine(FakeRetriever("x")), [str(len(RED_FLAGS))])   # self_harm
    assert s.result["red_flags"] == ["self_harm"] and "اکیلے نہیں" in r.text


def test_invalid_answers_reask_and_accept_urdu_digits():
    e = QuestionnaireEngine(FakeRetriever("x"))
    s = Session()
    e.start(s)
    r = e.reply(s, "شاید")
    assert not r.done and "نمبر" in r.text and s.step == 0
    r = e.reply(s, "۱۰")            # Urdu digit for the "none" option
    assert s.answers["red_flags"] == ["none"] and r.data["question_id"] == "complaint"


def test_session_round_trips_for_stateless_web_apps():
    e = QuestionnaireEngine(FakeRetriever("x"))
    s = Session()
    e.start(s)
    e.reply(s, NONE_FLAG)
    restored = Session.from_dict(s.to_dict())
    r = e.reply(restored, "قبض")
    assert restored.answers["complaint"] == "قبض" and r.data["question_id"] == "duration"


def test_hazard_detection_whole_words_only():
    assert hazard_flags("پوست ہلیلہ زرد، گل بنفشہ") == []
    assert hazard_flags("کشتہ شنگرف دو حصے") == ["kushta", "mercury"]
    assert "opium" in hazard_flags("افیون ایک رتی")


def test_engine_config_and_provider_seam(monkeypatch):
    assert isinstance(build_engine(EngineConfig(), FakeRetriever("x")), QuestionnaireEngine)
    monkeypatch.setenv("NAZRIA_ENGINE", "llm")
    monkeypatch.setenv("NAZRIA_LLM_PROVIDER", "local")
    monkeypatch.setenv("NAZRIA_LLM_MODEL", "my-model")
    cfg = EngineConfig.from_env()
    with pytest.raises(ValueError):          # local needs an OpenAI-compatible base URL
        cfg.validate()
    cfg.base_url = "http://localhost:8000/v1"
    from nazria_kb.llm_engine import LLMEngine
    assert isinstance(build_engine(cfg, FakeRetriever("x")), LLMEngine)   # local needs no key
    eng = build_engine(EngineConfig(engine="llm", provider="unknown", model="m"), FakeRetriever("x"))
    assert isinstance(eng, QuestionnaireEngine) and "NAZRIA_LLM_PROVIDER" in eng.fallback_reason
    eng = build_engine(EngineConfig(engine="hybrid", provider="gemini"), FakeRetriever("x"))   # no model set
    assert isinstance(eng, QuestionnaireEngine) and "NAZRIA_LLM_MODEL" in eng.fallback_reason


def test_citation_corrections_match_defaults():
    from nazria_kb.db import CITATION_CORRECTIONS
    by = {(q.id, o.key): o.pages for q in DEFAULT_QUESTIONS for o in q.options}
    for qid, key, old, new in CITATION_CORRECTIONS:
        assert by[(qid, key)] == new and old != new


# --------------------------------------------------------------------------- the vol 1 signs
VOL1 = {"appetite", "thirst", "pain_timing", "joints", "skin", "hair", "feeling", "other_signs"}


def test_vol1_signs_cite_volume_1_pages_of_the_signs_treatise():
    qs = {q.id: q for q in DEFAULT_QUESTIONS}
    assert VOL1 <= set(qs)
    for qid in VOL1:
        q = qs[qid]
        assert q.stage == "signs" and q.options[-1].weights == {}          # last option: normal / none
        for o in q.options:
            if o.weights:
                assert o.volume == 1 and all(549 <= p <= 583 for p in o.pages), (qid, o.key)
                assert list(o.weights.values()) == [1]                     # one point: a supporting sign
    # the original nine sign questions keep citing vol 2
    assert all(o.volume == 2 for q in DEFAULT_QUESTIONS if q.id not in VOL1 for o in q.options if o.weights)


def test_vol1_signs_score_and_cite_their_volume():
    sc = score(DEFAULT_QUESTIONS, {"joints": "sharp_pain", "skin": ["cracks", "scaly_patches"], "pain_timing": "movement",
                                   "other_signs": ["sneezing"]})
    assert sc.totals == {"اعصابی": 1, "عضلاتی": 4, "غدی": 0} and sc.primary == "عضلاتی"
    assert sc.evidence_volumes == [1] * 5 and len(sc.evidence_keys) == 5
    from nazria_kb.engine import Assessment, render_assessment
    text = render_assessment(Assessment(sc, False, False))
    assert "جلد اول، صفحہ 559" in text and "(نقرس)" in text


def test_neutral_answers_add_nothing():
    neutral = {"appetite": "normal", "thirst": "normal", "pain_timing": "none", "joints": "none", "skin": ["none"],
               "hair": "normal", "feeling": "none", "other_signs": ["none"]}
    assert score(DEFAULT_QUESTIONS, neutral).totals == {s: 0 for s in SYSTEMS}
