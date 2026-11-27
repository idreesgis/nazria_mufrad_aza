"""The API's PostgreSQL path (nazria schema) end to end. Runs only when NAZRIA_TEST_DATABASE_URL points at a
DISPOSABLE database: it drops and recreates schema "nazria" there. Never uses NAZRIA_DATABASE_URL."""
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

DSN = os.environ.get("NAZRIA_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DSN, reason="set NAZRIA_TEST_DATABASE_URL to a disposable database")

PAGES = [
    "# کلیات تحقیقات صابر ملتانی\n## تحقیقات و علاج قبض\n۱۰\n\n## عضلاتی قبض\n\n### علامات\n\n"
    "عضلاتی قبض اکثر شدید ہوتی ہے اور یہی قبض دائمی بھی ہوتی ہے۔ ایسے مریض کا قارورہ سرخ ہوتا ہے۔ ریاح زیادہ ہوتی ہے۔\n\n"
    "### نسخہ\n\nسناکی، تیز پات۔ دونوں ہم وزن سفوف کر لیں۔\n\n**مقدار خوراک:** دو ماشہ ہمراہ آب تازہ۔",
    "# کلیات تحقیقات صابر ملتانی\n## تحقیقات و علاج قبض\n۱۱\n\n### پرہیز\n\nٹھنڈی اشیاء سے پرہیز کریں۔ ثقیل غذا نہ کھائیں۔",
]


@pytest.fixture(scope="module")
def conn(tmp_path_factory):
    import psycopg
    from test_pipeline import _row
    from nazria_kb.db import apply_schema, load
    from nazria_kb.pipeline import build
    c = psycopg.connect(DSN, autocommit=True)
    c.execute("DROP SCHEMA IF EXISTS nazria CASCADE")
    csv = tmp_path_factory.mktemp("book") / "book.csv"
    csv.write_text("".join(_row(100 + i, v, 10 + i, t) for v in (1, 2) for i, t in enumerate(PAGES)), encoding="utf-8")
    c.autocommit = False
    apply_schema(c)
    load(c, build(csv))
    c.commit()
    c.autocommit = True
    # behave like Django's connection: jsonb comes back as text (Django decodes JSON itself)
    from psycopg.types.string import TextLoader
    c.adapters.register_loader("jsonb", TextLoader)
    yield c
    c.execute("DROP SCHEMA IF EXISTS nazria CASCADE")
    c.close()


def test_consultation_round_trip_in_postgres(conn, settings):
    from consultations import services
    from consultations.backends import PostgresKnowledgeBase
    kb = PostgresKnowledgeBase(connection_factory=lambda: conn, cache_seconds=0)
    kb.ping()
    questions = kb.questions()
    assert [q.id for q in questions][:2] == ["red_flags", "complaint"]      # seeded by load()
    from tests.api.conftest import REFERENCE
    answers = services.validate_answers(questions, {**REFERENCE, "complaint": "پرانی عضلاتی قبض"})
    out = services.run_consultation(kb, questions, answers)
    assert out.payload["assessment"]["primary_system"] == "عضلاتی"
    assert out.payload["book"]["topic"]["title"] == "عضلاتی قبض"
    kb.save_session(out.session)
    s = kb.load_session(out.session.session_uid)
    assert s.status == "completed" and s.answers == answers and s.result["api"]["text"] == out.payload["text"]
    assert len(s.transcript) == len(out.session.transcript)
    # an explanation turn is appended to the same session
    s.transcript.append({"role": "hakeem", "content": "وضاحت: …", "question_id": None, "latency_ms": 5,
                         "source_chunk_ids": [1]})
    s.result["explanation"] = {"status": "shown"}
    kb.save_session(s)
    again = kb.load_session(s.session_uid)
    assert again.transcript[-1]["source_chunk_ids"] == [1] and again.result["explanation"] == {"status": "shown"}
    assert kb.delete_session(s.session_uid) and kb.load_session(s.session_uid) is None
    assert not kb.delete_session(s.session_uid)
