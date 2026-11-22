"""CLI argument parsing."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nazria_kb.__main__ import parse_answers  # noqa: E402

EXPECTED = ["10", "مجھے پرانی قبض کی شکایت ہے", "3", "2"]


@pytest.mark.parametrize("text", [
    '["10","مجھے پرانی قبض کی شکایت ہے","3","2"]',      # JSON
    "[10,مجھے پرانی قبض کی شکایت ہے,3,2]",              # quotes stripped by the IDE (Windows)
    "10,مجھے پرانی قبض کی شکایت ہے,3,2",                # plain
    "10 | مجھے پرانی قبض کی شکایت ہے | 3 | 2",          # pipe
])
def test_answers_formats(text):
    assert parse_answers(text) == EXPECTED


def test_pipe_keeps_commas_inside_an_answer():
    assert parse_answers("10|قبض، گیس اور بھوک کم|3") == ["10", "قبض، گیس اور بھوک کم", "3"]


def test_empty_answers_rejected():
    with pytest.raises(ValueError):
        parse_answers("[]  ")


def test_unquoted_answers_with_spaces_are_joined_back(monkeypatch):
    import nazria_kb.__main__ as cli
    seen = {}
    monkeypatch.setattr(cli, "_consult", lambda args: seen.setdefault("a", parse_answers(" ".join(args.answers))) and 0)
    argv = ["consult", "--answers", "10,مجھے", "پرانی", "قبض", "کی", "شکایت", "ہے,3,2,ختم"]
    cli._main(argv)
    assert seen["a"] == ["10", "مجھے پرانی قبض کی شکایت ہے", "3", "2", "ختم"]


def test_evaluate_defaults_to_gemini_4_hydrogen_for_answers_and_judge(monkeypatch, tmp_path):
    import nazria_kb.engine as engine_mod
    import nazria_kb.evaluate as evaluate_mod
    import nazria_kb.pipeline as pipeline_mod
    from nazria_kb.__main__ import main
    for k in ("NAZRIA_LLM_PROVIDER", "NAZRIA_LLM_MODEL", "NAZRIA_LLM_BASE_URL", "NAZRIA_LLM_API_KEY_ENV"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("NAZRIA_ALLOW_EXTERNAL_PROVIDERS", "true")
    monkeypatch.setenv("GEMINI_API_KEY", "g-test")
    seen = {}

    def fake_evaluate(providers, retriever, out, judge=None):
        seen["providers"] = [(p.name, p.model) for p in providers]
        seen["judge"] = (judge.name, judge.model) if judge else None
        return tmp_path / "EVAL.md", {}
    monkeypatch.setattr(evaluate_mod, "evaluate", fake_evaluate)
    monkeypatch.setattr(pipeline_mod, "build", lambda csv: None)
    monkeypatch.setattr(engine_mod, "DatasetRetriever", lambda ds: None)
    assert main(["evaluate", "--csv", "x.csv"]) == 0
    assert seen == {"providers": [("gemini", "gemini-4-hydrogen")], "judge": ("gemini", "gemini-4-hydrogen")}
    assert main(["evaluate", "--csv", "x.csv", "--judge-provider", "none"]) == 0 and seen["judge"] is None
