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
