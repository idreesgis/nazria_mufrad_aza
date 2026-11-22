"""Evaluation harness with fake providers (no real API calls)."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nazria_kb.engine import Passage  # noqa: E402
from nazria_kb.evaluate import EVAL_SET, evaluate, overlap_groundedness, urdu_ratio  # noqa: E402
from nazria_kb.providers import FakeProvider, ProviderError  # noqa: E402


class R:
    def topics_for(self, *a, **k):
        return []

    def passages(self, query, limit=3):
        if "موبائل" in query:
            return []
        return [Passage("رسالہ › قبض", "عضلاتی قبض میں قارورہ سرخ ہوتا ہے اور قبض شدید ہوتی ہے۔", 2, [127], 1)]


def good(messages):
    return "عضلاتی قبض میں قارورہ سرخ ہوتا ہے اور قبض شدید ہوتی ہے (جلد دوم، صفحہ 127)۔"


def reckless(messages):
    return "نسخہ: کشتہ سنکھیا 1 رتی، سناء مکی 2 تولہ (جلد دوم، صفحہ 127)۔ مزید (جلد اول، صفحہ 3)"


def test_metrics_helpers():
    assert urdu_ratio("یہ اردو ہے") == 1.0 and urdu_ratio("") == 0.0
    assert overlap_groundedness("عضلاتی قبض شدید", "عضلاتی قبض بہت شدید ہوتی") == 1.0


def test_evaluate_compares_providers_and_writes_report(tmp_path, monkeypatch):
    monkeypatch.setenv("NAZRIA_PRICE_GOOD_IN_PER_MTOK", "1.0")
    monkeypatch.setenv("NAZRIA_PRICE_GOOD_OUT_PER_MTOK", "2.0")
    providers = [FakeProvider(good, name="good", model="g1"), FakeProvider(reckless, name="reckless", model="r1"),
                 FakeProvider([ProviderError("down", "connection", "x", True)], name="down", model="d1")]
    judge = FakeProvider([json.dumps({"groundedness": 4, "fluency": 5, "notes": "ok"})], name="judge", model="j")
    path, summary = evaluate(providers, R(), tmp_path / "EVAL.md", judge=judge)
    g, r, d = summary["good/g1"], summary["reckless/r1"], summary["down/d1"]
    n = len(EVAL_SET)
    assert g["safety_pass"] == n and g["citation_accuracy"] == 1.0 and g["cost"] is not None
    assert g["groundedness_judge"] == 4 and g["fluency_judge"] == 5
    assert r["safety_pass"] == n          # guards keep even a reckless model safe …
    assert r["citation_accuracy"] < 1.0   # … but its invalid citations are measured
    assert d["fallbacks"] > 0 and d["answered_by_llm"] == 0
    assert d["safety_pass"] == n          # a provider that is down gives no unsafe answer (o1 used to fail here)
    text = path.read_text()
    assert "`good/g1`" in text and "## Per question" in text and path.with_suffix(".json").exists()


def test_judge_failures_are_reported_not_silent(tmp_path, caplog):
    """A judge model that is not installed (Ollama 404) used to give groundedness_judge=null with no hint why."""
    good = FakeProvider(["عضلاتی قبض شدید ہوتی ہے (جلد دوم، صفحہ 127)۔"], name="good", model="g1")
    judge = FakeProvider([ProviderError("model 'qwen2.5:14b' not found", "not_found", "local", False)],
                         name="local", model="qwen2.5:14b")
    _, summary = evaluate([good], R(), tmp_path / "EVAL.md", judge=judge)
    s = summary["good/g1"]
    assert s["judge_errors"] == s["answered_by_llm"] > 0 and s["groundedness_judge"] is None
    assert "judge local/qwen2.5:14b failed" in caplog.text and "not found" in caplog.text


def test_evaluation_passes_the_configured_max_tokens_to_answers_and_judge(tmp_path, monkeypatch):
    """Thinking models spend output tokens on reasoning: a fixed 800/200 cut their answers off."""
    monkeypatch.setenv("NAZRIA_LLM_MAX_TOKENS", "4096")
    good = FakeProvider(["عضلاتی قبض شدید ہوتی ہے (جلد دوم، صفحہ 127)۔"], name="good", model="g1")
    judge = FakeProvider([json.dumps({"groundedness": 4, "fluency": 5})], name="judge", model="j")
    evaluate([good], R(), tmp_path / "EVAL.md", judge=judge)
    assert {c["max_tokens"] for c in good.calls} == {4096} and {c["max_tokens"] for c in judge.calls} == {4096}
