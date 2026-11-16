"""LLM and hybrid engines with a FAKE provider (and one run through the mock OpenAI-compatible server)."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from mock_openai import MockOpenAIServer  # noqa: E402
from nazria_kb.engine import EngineConfig, Passage, QuestionnaireEngine, Session, TopicHit, build_engine  # noqa: E402
from nazria_kb.llm_engine import (NOT_COVERED_MESSAGE, VULNERABLE_RULE, HybridEngine, LLMEngine,  # noqa: E402
                                  check_citations, parse_citations)
from nazria_kb.providers import FakeProvider, ProviderError  # noqa: E402
from nazria_kb.safety import BOOK_DISCLAIMER_LLM, DISCLAIMER, RED_FLAGS, VULNERABLE_NO_RECIPE  # noqa: E402

NONE_FLAG = str(len(RED_FLAGS) + 1)
GOOD = "عضلاتی قبض میں قارورہ سرخ ہوتا ہے اور قبض شدید ہوتی ہے (جلد دوم، صفحہ 127)۔"
SIGNS = ["3", "2", "3", "1", "1", "1", "1", "1", "1", "2", "2", "4"]   # duration .. phlegm (adult)


class R:
    def __init__(self, passages=True):
        self.has = passages

    def topics_for(self, complaint, system, limit=3):
        return [TopicHit(1, "عضلاتی قبض", 2, [127], None, [("overview", "عضلاتی قبض شدید ہوتی ہے۔", [127]),
                                                           ("recipe", "سناء مکی 2 تولہ، ہلیلہ 1 تولہ", [127])])]

    def passages(self, query, limit=3):
        if not self.has:
            return []
        return [Passage("رسالہ › عضلاتی قبض", "عضلاتی قبض میں قارورہ سرخ ہوتا ہے۔ نسخہ: سناء مکی 2 تولہ", 2, [127], 11),
                Passage("رسالہ › غدی قبض", "غدی قبض میں پاخانہ تسلی سے نہیں ہوتا۔", 2, [128], 12)][:limit]


def llm_session(provider, retriever=None, intake=(NONE_FLAG, "2", "2")):
    e = LLMEngine(provider, retriever or R())
    s = Session()
    r = e.start(s)
    for a in intake:
        r = e.reply(s, a)
    return e, s, r


# --------------------------------------------------------------------------- citations
def test_citation_parsing_and_validation():
    cits = parse_citations("(جلد دوم، صفحہ ۱۲۷) اور جلد اول صفحات 5–7")
    assert [(v, a, b) for v, a, b, _ in cits] == [(2, 127, 127), (1, 5, 7)]
    ps = R().passages("x")
    text, cited, invalid, valid = check_citations("الف (جلد دوم، صفحہ 127)۔ ب (جلد اول، صفحہ 999)۔", ps)
    assert "999" not in text and (invalid, valid) == (1, 1) and [p.chunk_id for p in cited] == [11]


# --------------------------------------------------------------------------- llm engine
def test_llm_engine_grounded_answer_with_citation_disclaimer_and_telemetry():
    fp = FakeProvider([GOOD])
    e, s, r = llm_session(fp)
    assert s.phase == "chat" and not r.done
    r = e.reply(s, "مجھے پرانی قبض ہے، اس کی وجہ کیا ہے؟")
    assert "صفحہ 127" in r.text and "ماخذ:" in r.text and BOOK_DISCLAIMER_LLM in r.text and not r.done
    last = s.transcript[-1]
    assert last["provider"] == "fake" and last["model"] == "fake-model" and last["source_chunk_ids"] == [11, 12]
    assert last["prompt_tokens"] > 0 and last["latency_ms"] >= 0
    system = fp.calls[0]["messages"][0]["content"]
    assert "[NOT_COVERED]" in system and "(جلد دوم، صفحہ 127)" in system and VULNERABLE_RULE not in system
    r = e.reply(s, "ختم")
    assert r.done and s.status == "completed" and BOOK_DISCLAIMER_LLM in r.text


def test_red_flag_in_chat_stops_without_calling_the_model():
    fp = FakeProvider([GOOD])
    e, s, r = llm_session(fp)
    r = e.reply(s, "اچانک سینے میں شدید درد ہو رہا ہے")
    assert r.done and s.status == "emergency" and "ہسپتال" in r.text and fp.calls == []


def test_intake_red_flag_and_reask():
    e = LLMEngine(FakeProvider([GOOD]), R())
    s = Session()
    e.start(s)
    assert "نمبر" in e.reply(s, "پتا نہیں").text
    r = e.reply(s, "2")
    assert r.done and s.status == "emergency"


def test_not_covered_and_no_passages_refer_to_hakeem():
    e, s, r = llm_session(FakeProvider(["[NOT_COVERED]"]))
    r = e.reply(s, "شوگر کا علاج؟")
    assert NOT_COVERED_MESSAGE in r.text and BOOK_DISCLAIMER_LLM in r.text
    fp = FakeProvider([GOOD])
    e, s, r = llm_session(fp, R(passages=False))
    r = e.reply(s, "شوگر کا علاج؟")
    assert NOT_COVERED_MESSAGE in r.text and fp.calls == []


def test_hazardous_model_answer_is_replaced():
    bad = GOOD + "\nنسخہ: کشتہ سنکھیا 1 رتی، شنگرف 1 ماشہ (جلد دوم، صفحہ 127)"
    e, s, r = llm_session(FakeProvider([bad]))
    r = e.reply(s, "قبض کا نسخہ بتائیں")
    assert "1 رتی" not in r.text and "مستند حکیم کی نگرانی" in r.text and "صفحہ 127" in r.text
    assert s.result["answers"][-1]["hazards"] == ["arsenic", "kushta", "mercury"]


def test_vulnerable_patients_get_no_recipe_from_the_model():
    fp = FakeProvider([GOOD + "\nنسخہ: سناء مکی 2 تولہ، ہلیلہ 1 تولہ (جلد دوم، صفحہ 127)"])
    e, s, r = llm_session(fp, intake=(NONE_FLAG, "3", "3"))          # elderly
    r = e.reply(s, "قبض کا علاج؟")
    assert "سناء مکی 2" not in r.text and VULNERABLE_NO_RECIPE in r.text
    assert VULNERABLE_RULE in fp.calls[0]["messages"][0]["content"]
    # pregnancy mentioned in free text also makes the patient vulnerable
    e, s, r = llm_session(FakeProvider([GOOD + "\nنسخہ: سناء مکی 2 تولہ (جلد دوم، صفحہ 127)"]))
    r = e.reply(s, "میں حاملہ ہوں اور قبض ہے")
    assert "سناء مکی 2" not in r.text


def test_uncited_answer_falls_back_to_book_excerpts():
    e, s, r = llm_session(FakeProvider(["قبض کے لیے پانی زیادہ پئیں۔"]))
    r = e.reply(s, "قبض؟")
    assert "کتاب کے متعلقہ اقتباسات" in r.text and "صفحہ 127" in r.text and "پانی زیادہ پئیں" not in r.text
    assert s.result["answers"][-1].get("citation_missing")


def test_provider_failure_falls_back_to_questionnaire_and_finishes():
    e, s, r = llm_session(FakeProvider([ProviderError("local", "connection", "down", True)]))
    r = e.reply(s, "مجھے پرانی قبض کی شکایت ہے")
    assert not r.done and "AI سروس دستیاب نہیں" in r.text and r.data["question_id"] == "duration"
    assert s.result["ai_fallback"] == "connection" and s.phase == "questionnaire"
    for a in SIGNS:
        r = e.reply(s, a)
    assert r.done and s.status == "completed" and s.result["primary_system"] == "عضلاتی" and DISCLAIMER in r.text


def test_unexpected_error_never_crashes():
    fp = FakeProvider([RuntimeError("boom")])
    e, s, r = llm_session(fp)
    r = e.reply(s, "قبض")
    assert not r.done and r.text and s.phase == "questionnaire"


def test_external_provider_redacts_pii_and_notifies_once():
    fp = FakeProvider([GOOD], name="openai", external=True)
    e = LLMEngine(fp, R())
    s = Session()
    r = e.start(s)
    assert "بیرونی AI سروس (openai)" in r.text and s.external_provider
    for a in (NONE_FLAG, "2", "2"):
        r = e.reply(s, a)
    assert "بیرونی" not in r.text
    e.reply(s, "میرا نام احمد علی ہے، فون 0300-1234567، شناختی کارڈ 35202-1234567-1، قبض ہے")
    e.reply(s, "احمد علی کو بھوک بھی کم لگتی ہے")
    sent = " ".join(m["content"] for c in fp.calls for m in c["messages"] if m["role"] == "user")
    assert "احمد" not in sent and "0300" not in sent and "35202" not in sent and "[نام]" in sent
    assert s.transcript[-1]["provider"] == "openai"


def test_session_round_trip_mid_chat():
    fp = FakeProvider([GOOD])
    e, s, r = llm_session(fp)
    s2 = Session.from_dict(s.to_dict())
    r = e.reply(s2, "قبض")
    assert "صفحہ 127" in r.text and s2.engine == "llm"


# --------------------------------------------------------------------------- hybrid engine
def run_hybrid(provider, retriever=None, answers=None):
    e = HybridEngine(provider, retriever or R())
    s = Session()
    r = e.start(s)
    for a in answers or [NONE_FLAG, "مجھے پرانی قبض کی شکایت ہے"] + SIGNS:
        r = e.reply(s, a)
    return e, s, r


def test_hybrid_questionnaire_then_llm_explanation_and_followups():
    fp = FakeProvider([GOOD, "غدی قبض میں پاخانہ تسلی سے نہیں ہوتا (جلد دوم، صفحہ 128)۔"])
    e, s, r = run_hybrid(fp)
    assert not r.done and s.phase == "followup" and s.engine == "hybrid"
    assert "عضلاتی" in r.text and "سناء مکی 2 تولہ" in r.text and "وضاحت:" in r.text and DISCLAIMER in r.text
    assert "غالب نظام: عضلاتی" in fp.calls[0]["messages"][0]["content"]
    r = e.reply(s, "غدی قبض کیسی ہوتی ہے؟")
    assert "صفحہ 128" in r.text and BOOK_DISCLAIMER_LLM in r.text
    r = e.reply(s, "ختم")
    assert r.done and s.status == "completed"


def test_hybrid_provider_failure_keeps_questionnaire_result():
    e, s, r = run_hybrid(FakeProvider([ProviderError("local", "timeout", "slow", True)]))
    assert not r.done and "عضلاتی" in r.text and "وضاحت" not in r.text and s.result["ai_fallback"] == "timeout"
    r = e.reply(s, "غدی قبض؟")
    assert "AI سروس دستیاب نہیں" in r.text and "صفحہ" in r.text


def test_hybrid_emergency_and_vulnerable():
    fp = FakeProvider([GOOD])
    e, s, r = run_hybrid(fp, answers=["1"])
    assert r.done and s.status == "emergency" and fp.calls == []
    fp = FakeProvider([GOOD + "\nنسخہ: سناء مکی 2 تولہ (جلد دوم، صفحہ 127)"])
    child = [NONE_FLAG, "قبض", "1", "1"] + SIGNS[3:]          # child: pregnancy question skipped
    e, s, r = run_hybrid(fp, answers=child)
    assert "سناء مکی 2 تولہ" not in r.text and VULNERABLE_NO_RECIPE in r.text


def test_build_engine_policy_fallback_and_default(monkeypatch):
    monkeypatch.delenv("NAZRIA_ENGINE", raising=False)
    assert EngineConfig.from_env().engine == "questionnaire"
    cfg = EngineConfig(engine="hybrid", provider="openai", model="m")   # external, not allowed
    eng = build_engine(cfg, R())
    assert isinstance(eng, QuestionnaireEngine) and "NAZRIA_ALLOW_EXTERNAL_PROVIDERS" in eng.fallback_reason
    with pytest.raises(ValueError):
        EngineConfig(engine="magic").validate()


def test_hybrid_end_to_end_through_mock_local_server():
    with MockOpenAIServer([("ok", GOOD)]) as srv:
        cfg = EngineConfig(engine="hybrid", provider="local", model="qwen-local", local_stack="ollama",
                           base_url=srv.url, max_retries=0)
        e = build_engine(cfg, R())
        s = Session()
        r = e.start(s)
        for a in [NONE_FLAG, "قبض"] + SIGNS:
            r = e.reply(s, a)
    assert isinstance(e, HybridEngine) and "وضاحت:" in r.text and srv.requests[0]["body"]["model"] == "qwen-local"
    summary = [m for m in s.transcript if m.get("provider")][0]
    assert summary["model"] == "mock-model" and summary["prompt_tokens"] == 42


def test_hybrid_explanation_retrieves_by_complaint_not_by_instruction():
    class Recording(R):
        queries = []

        def passages(self, query, limit=3):
            self.queries.append(query)
            return super().passages(query, limit)
    ret = Recording()
    run_hybrid(FakeProvider([GOOD]), ret)
    assert ret.queries[-1].startswith("مجھے پرانی قبض کی شکایت ہے")


def test_small_model_citation_styles_are_accepted_only_when_unambiguous():
    ps = R().passages("x")                       # vol 2 p127 (chunk 11), vol 2 p128 (chunk 12)
    text, cited, invalid, valid = check_citations("الف [1]۔ ب صفحہ 128 پر۔ ج [7]۔ د صفحہ 999۔", ps)
    assert (valid, invalid) == (2, 0) and [p.chunk_id for p in cited] == [11, 12]
    assert "جلد دوم، صفحہ 127" in text and "جلد دوم، صفحہ 128" in text and "[7]" in text


def test_passage_number_citation_reaches_the_patient():
    e, s, r = llm_session(FakeProvider(["عضلاتی قبض میں قارورہ سرخ ہوتا ہے [1]۔"]))
    r = e.reply(s, "قبض؟")
    assert "(جلد دوم، صفحہ 127)" in r.text and "ماخذ:" in r.text and "کتاب کے متعلقہ اقتباسات" not in r.text


def test_debug_logs_raw_model_answer(caplog):
    import logging
    caplog.set_level(logging.DEBUG, logger="nazria_kb")
    e, s, r = llm_session(FakeProvider(["بغیر حوالہ جواب"]))
    e.reply(s, "قبض؟")
    assert "بغیر حوالہ جواب" in caplog.text and "no valid citation" in caplog.text


def test_degenerate_answers_are_never_shown_even_with_a_citation():
    from nazria_kb.llm_engine import degenerate_reason
    loop = "عضلاتی قبض (جلد دوم، صفحہ 127) میں ریاح اور نفخ شکم (پھ" + "叔" * 400
    assert "repetition" in degenerate_reason(loop)
    assert "non-Urdu" in degenerate_reason("یہ جواب ہے 这是中文回答这是中文回答 (جلد دوم، صفحہ 127)")
    assert degenerate_reason(GOOD) is None and degenerate_reason("ہا ہا ہا") is None
    e, s, r = llm_session(FakeProvider([loop]))
    r = e.reply(s, "قبض؟")
    assert "叔" not in r.text and "کتاب کے متعلقہ اقتباسات" in r.text
    assert s.result["answers"][-1]["kind"] == "excerpt_fallback"
