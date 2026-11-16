"""AI reviewer with a fake provider and an in-memory store (no DB, no real API)."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nazria_kb.providers import FakeProvider, ProviderError  # noqa: E402
from nazria_kb.questionnaire import DEFAULT_QUESTIONS  # noqa: E402
from nazria_kb.reviewer import (Chunk, ConvItem, decide, deterministic_checks, judge_messages,  # noqa: E402
                                normalise_judgement, parse_json_object, review_conversations, review_weights)

SAFE_CLOSE = "یہ معلومات کتاب (جلد دوم، صفحات 127) سے ماخوذ ہیں۔ کسی مستند حکیم سے معائنہ ضرور کروائیں۔"


def item(uid="u1", hazard=False, close=SAFE_CLOSE, cited="127"):
    recipe = "نسخہ: کشتہ سنکھیا 1 رتی" if hazard else "نسخہ: سناء مکی 2 تولہ"
    return ConvItem(uid, 1, "consultation", "قبض", 2, [127], ["arsenic", "kushta"] if hazard else [], [
        (0, "patient", "مجھے قبض ہے", []),
        (1, "hakeem", "عضلاتی قبض میں قارورہ سرخ ہوتا ہے۔", [5]),
        (2, "patient", "علاج؟", []),
        (3, "hakeem", recipe, [5]),
        (4, "patient", "شکریہ", []),
        (5, "hakeem", close.replace("127", cited), []),
    ], {5: Chunk(5, "رسالہ › قبض", "عضلاتی قبض میں قارورہ سرخ ہوتا ہے۔ نسخہ: سناء مکی 2 تولہ", 2, [127])})


class MemStore:
    def __init__(self, items, human=()):
        self.items, self.human, self.saved = items, set(human), {}

    def pending(self, limit):
        return [i for i in self.items if i.uid not in self.saved and i.uid not in self.human][:limit]

    def save(self, uid, status, reviewer, notes, details):
        if uid in self.human:
            return False
        self.saved[uid] = (status, reviewer, notes, details)
        return True


def verdict(status="approved", **kw):
    return json.dumps({"status": status, "groundedness": 5, "citations_correct": True, "safety": "ok",
                       "urdu_quality": 4, "notes": "grounded", **kw})


def test_json_parsing_tolerates_fences_and_prose():
    assert parse_json_object('Sure:\n```json\n{"status": "approved", "notes": "a {b}"}\n```')["notes"] == "a {b}"
    assert parse_json_object("no json here") is None
    assert normalise_judgement({"status": "maybe"}) is None
    assert normalise_judgement({"status": "approved", "groundedness": 9})["groundedness"] == 5


def test_deterministic_checks_and_decision_only_get_stricter():
    det = deterministic_checks(item(hazard=True, close="شکریہ، اللہ شفا دے۔", cited="999"))
    assert det["hazards"] == ["arsenic", "kushta"] and not det["referral_present"]
    status, reasons = decide(normalise_judgement(json.loads(verdict())), det)
    assert status == "needs_edit" and any("hazardous" in r for r in reasons) and any("referral" in r for r in reasons)
    status, _ = decide(normalise_judgement(json.loads(verdict("rejected"))), det)
    assert status == "rejected"                                    # never loosened
    det = deterministic_checks(item(cited="999"))
    assert det["uncited_pages"] == [999]
    assert decide(normalise_judgement(json.loads(verdict())), deterministic_checks(item()))[0] == "approved"


def test_review_run_hazard_first_resumable_limit_and_temperature_zero():
    items = [item("safe1"), item("haz1", hazard=True), item("safe2")]
    items.sort(key=lambda i: not i.hazard_flags)       # the store returns hazard-flagged first
    store = MemStore(items, human={"safe2"})
    fp = FakeProvider([verdict()], name="local", model="judge-m")
    stats = review_conversations(store, fp, limit=2)
    assert stats["reviewed"] == 2 and list(store.saved) == ["haz1", "safe1"]
    assert store.saved["haz1"][0] == "needs_edit" and store.saved["safe1"][0] == "approved"
    assert store.saved["safe1"][1] == "ai:local/judge-m" and all(c["temperature"] == 0.0 for c in fp.calls)
    assert store.saved["haz1"][3]["deterministic"]["hazards"] == ["arsenic", "kushta"]
    again = review_conversations(store, fp, limit=10)            # resumable: nothing left (safe2 is human)
    assert again["reviewed"] == 0 and len(fp.calls) == 2


def test_review_repairs_bad_json_and_counts_errors():
    store = MemStore([item("a"), item("b")])
    fp = FakeProvider(["not json", verdict(), ProviderError("local", "timeout", "slow", True)])
    stats = review_conversations(store, fp, limit=5)
    assert stats["reviewed"] == 1 and stats["errors"] == 1 and "a" in store.saved


def test_judge_prompt_contains_sources_and_conversation():
    msgs = judge_messages(item())
    assert "[chunk 5]" in msgs[1]["content"] and "HAKEEM [3]" in msgs[1]["content"] and "JSON" in msgs[0]["content"]


def test_weights_report_never_changes_weights(tmp_path):
    before = [(o.key, dict(o.weights)) for q in DEFAULT_QUESTIONS for o in q.options]
    fp = FakeProvider([json.dumps({"supported": "partly", "system_in_text": "غدی", "quote": "…", "notes": "check"})])
    out = review_weights(DEFAULT_QUESTIONS, lambda book, pages: {p: (f"scan page {p}", "متن") for p in pages},
                         fp, tmp_path / "W.md")
    text = out.read_text()
    assert "Nothing was changed" in text and "`taste`" in text and "need a Hakeem's attention" in text
    assert [(o.key, dict(o.weights)) for q in DEFAULT_QUESTIONS for o in q.options] == before
    n_links = sum(len(o.weights) for q in DEFAULT_QUESTIONS if q.stage == "signs" for o in q.options)
    assert len(fp.calls) == n_links
