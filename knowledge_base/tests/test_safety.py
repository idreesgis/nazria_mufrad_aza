"""Safety-layer fixes: free-text red flags, extended hazard list, output guard, unsafe excerpts, DSN redaction."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nazria_kb.db import normalize_dsn, redact  # noqa: E402
from nazria_kb.engine import Passage, QuestionnaireEngine, Session, TopicHit  # noqa: E402
from nazria_kb.safety import (PRACTITIONER_ONLY, RED_FLAGS, VULNERABLE_NO_RECIPE, detect_red_flags,  # noqa: E402
                              guard_answer, hazard_flags, looks_like_recipe)

NONE_FLAG = str(len(RED_FLAGS) + 1)
ADULT_SIGNS = ["3", "2", "3", "1", "1", "1", "1", "1", "1", "2", "2", "4",
               "3", "2", "3", "4", "7", "3", "3", "9"]   # appetite .. other_signs: normal / none


@pytest.mark.parametrize("text,code", [
    ("سینے میں شدید درد ہے", "chest_pain"),
    ("خون کی قے آئی ہے", "bleeding"),
    ("اچانک بازو کمزور ہو گیا", "stroke"),
    ("میں خودکشی کا سوچتا ہوں", "self_harm"),
    ("غلطی سے زہر کھا لیا", "poisoning"),
    ("پیٹ میں شدید درد ہے", "severe_abdominal_pain"),
    ("سانس لینے میں شدید دشواری", "breathing"),
])
def test_free_text_red_flags(text, code):
    assert code in detect_red_flags(text)


@pytest.mark.parametrize("text", ["مجھے پرانی قبض کی شکایت ہے", "میرے سینے میں جلن ہوتی ہے",
                                  "مجھے فالج کا پرانا مرض ہے", "نزلہ زکام اور کھانسی", ""])
def test_free_text_no_false_alarm(text):
    assert detect_red_flags(text) == []


@pytest.mark.parametrize("text,flag", [
    ("سیماب مصفی ایک ماشہ", "mercury"), ("کشتۂ فولاد", "kushta"), ("کشتے استعمال کریں", "kushta"),
    ("مینسل سرخ", "arsenic"), ("کچلا مدبر", "strychnine"), ("پتے کنیر", "oleander"),
])
def test_extended_hazards(text, flag):
    assert flag in hazard_flags(text)


def test_guard_answer_replaces_hazard_and_vulnerable_recipes():
    ans = "قبض عضلاتی تحریک سے ہوتی ہے (جلد دوم، صفحہ 127)۔\nنسخہ: شنگرف 1 ماشہ، سناء مکی 2 تولہ"
    out, info = guard_answer(ans, vulnerable=False)
    assert "شنگرف 1 ماشہ" not in out and info["hazards"] == ["mercury"]
    assert PRACTITIONER_ONLY.split("(")[0] in out
    out, info = guard_answer("نسخہ: سناء مکی 2 تولہ، ہلیلہ 1 تولہ", vulnerable=True)
    assert "سناء" not in out and VULNERABLE_NO_RECIPE in out and info["vulnerable_recipe_removed"]
    assert looks_like_recipe("سناء مکی ۲ تولہ") and not looks_like_recipe("پانی زیادہ پئیں")


class PassageOnlyRetriever:
    def topics_for(self, complaint, system, limit=3):
        return []

    def passages(self, query, limit=3):
        return [Passage("خطرناک", "کشتہ سنکھیا بنانے کا طریقہ", 2, [5], 1),
                Passage("نسخہ", "نسخہ: سناء مکی 2 تولہ، ہلیلہ 1 تولہ", 2, [6], 2),
                Passage("محفوظ", "قبض میں پانی زیادہ پئیں اور سادہ غذا کھائیں۔", 2, [7], 3)]


def _run(engine, answers):
    s = Session()
    r = engine.start(s)
    for a in answers:
        r = engine.reply(s, a)
        if r.done:
            break
    return s, r


def test_fallback_passages_are_hazard_and_vulnerability_checked():
    s, r = _run(QuestionnaireEngine(PassageOnlyRetriever()), [NONE_FLAG, "قبض"] + ADULT_SIGNS)
    assert r.done and "سنکھیا" not in r.text and "صفحہ 6" in r.text and "صفحہ 7" in r.text
    elderly = ADULT_SIGNS.copy()
    elderly[1] = "3"
    s, r = _run(QuestionnaireEngine(PassageOnlyRetriever()), [NONE_FLAG, "قبض"] + elderly)
    assert r.done and "سناء" not in r.text and "سنکھیا" not in r.text and "صفحہ 7" in r.text


def test_complaint_text_triggers_emergency():
    s, r = _run(QuestionnaireEngine(PassageOnlyRetriever()), [NONE_FLAG, "کل سے سینے میں شدید درد ہے"])
    assert r.done and s.status == "emergency" and s.result["red_flags"] == ["chest_pain"]


def test_hazardous_description_excerpt_is_not_shown():
    class R(PassageOnlyRetriever):
        def topics_for(self, complaint, system, limit=3):
            return [TopicHit(1, "قبض", 2, [127], None, [("overview", "اس میں کشتہ پارہ مفید ہے۔", [127])])]
    s, r = _run(QuestionnaireEngine(R()), [NONE_FLAG, "قبض"] + ADULT_SIGNS)
    assert r.done and "کشتہ پارہ" not in r.text


def test_dsn_normalisation_and_redaction():
    raw = "postgis://user:pa%6ss@db.example:5432/x?sslmode=require"
    assert normalize_dsn(raw) == "postgresql://user:pa%256ss@db.example:5432/x?sslmode=require"
    msg = f'invalid connection option "{raw}" and {normalize_dsn(raw)} password=hunter2'
    out = redact(msg, raw)
    assert "pa%6ss" not in out and "pa%256ss" not in out and "hunter2" not in out
