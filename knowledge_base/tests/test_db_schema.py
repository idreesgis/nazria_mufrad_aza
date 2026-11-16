"""Schema v3 migration against a real PostgreSQL. Runs only when NAZRIA_TEST_DATABASE_URL points at a
DISPOSABLE database (it drops and recreates schema "nazria" there). Never uses NAZRIA_DATABASE_URL."""
import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

DSN = os.environ.get("NAZRIA_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DSN, reason="set NAZRIA_TEST_DATABASE_URL to a disposable database")
ROOT = Path(__file__).resolve().parent.parent
SCHEMA = (ROOT / "sql" / "schema.sql").read_text(encoding="utf-8")


def _v2_schema() -> str | None:
    try:   # the schema as it was before v3 (main branch), to test the upgrade path
        return subprocess.run(["git", "show", "origin/main:knowledge_base/sql/schema.sql"], cwd=ROOT,
                              capture_output=True, text=True, check=True).stdout
    except Exception:
        return None


@pytest.fixture()
def conn():
    import psycopg
    with psycopg.connect(DSN, autocommit=True) as c:
        c.execute("DROP SCHEMA IF EXISTS nazria CASCADE")
        yield c
        c.execute("DROP SCHEMA IF EXISTS nazria CASCADE")


def _seed_conversation(c, uid, hazard=False):
    c.execute("INSERT INTO nazria.books VALUES (2,2,'t','v','a',NULL,1) ON CONFLICT DO NOTHING")
    c.execute("INSERT INTO nazria.treatises (book_id, ordinal, title, start_page, end_page, page_count) "
              "VALUES (2,1,'t',1,1,1) ON CONFLICT DO NOTHING")
    tr = c.execute("SELECT treatise_id FROM nazria.treatises LIMIT 1").fetchone()[0]
    c.execute("INSERT INTO nazria.topics (book_id, treatise_id, ordinal, title, title_key, topic_type, pages, "
              "start_page, end_page, full_text, char_count) VALUES (2,%s,1,'قبض','قبض','disease','{127}',127,127,'x',1) "
              "ON CONFLICT DO NOTHING", (tr,))
    tid = c.execute("SELECT topic_id FROM nazria.topics LIMIT 1").fetchone()[0]
    cid = c.execute("INSERT INTO nazria.conversations (conversation_uid, conv_type, title, topic_id, book_id, template_id, "
                    "generator, seed, system_prompt, turn_count, pages, quality_score, hazard_flags) "
                    "VALUES (%s,'qa','t',%s,2,'qa1','g',1,'sys',2,'{127}',0.9,%s) RETURNING conversation_id",
                    (uid, tid, ["arsenic"] if hazard else [])).fetchone()[0]
    c.execute("INSERT INTO nazria.conversation_turns (conversation_id, turn_index, role, content) VALUES "
              "(%s,0,'patient','سوال'),(%s,1,'hakeem','جواب')", (cid, cid))


def test_upgrade_from_v2_keeps_reviews_and_is_idempotent(conn):
    v2 = _v2_schema()
    if v2 is None:
        pytest.skip("origin/main not available")
    conn.execute(v2)
    uid = str(uuid.uuid4())
    conn.execute("INSERT INTO nazria.conversation_reviews (conversation_uid, review_status, reviewer, notes) "
                 "VALUES (%s,'approved','Hakeem A','ok')", (uid,))
    conn.execute(SCHEMA)
    conn.execute(SCHEMA)          # re-runnable
    row = conn.execute("SELECT review_status, reviewer, reviewer_type FROM nazria.conversation_reviews").fetchone()
    assert row == ("approved", "Hakeem A", "human")
    assert [v for (v,) in conn.execute("SELECT version FROM nazria.schema_version ORDER BY 1")] == [1, 2, 3]


def test_ai_never_overwrites_human_and_human_overrides_ai(conn):
    conn.execute(SCHEMA)
    from nazria_kb.reviewer import save_ai_review
    a, b = str(uuid.uuid4()), str(uuid.uuid4())
    conn.execute("INSERT INTO nazria.conversation_reviews (conversation_uid, review_status, reviewer) "
                 "VALUES (%s,'rejected','Hakeem A')", (a,))
    assert not save_ai_review(conn, a, "approved", "ai:fake/m", "looks fine", {"status": "approved"})
    assert conn.execute("SELECT review_status, reviewer FROM nazria.conversation_reviews WHERE conversation_uid=%s",
                        (a,)).fetchone() == ("rejected", "Hakeem A")
    # even a direct UPDATE by an AI process is neutralised by the trigger
    conn.execute("UPDATE nazria.conversation_reviews SET review_status='approved', reviewer='ai:x/y' "
                 "WHERE conversation_uid=%s", (a,))
    assert conn.execute("SELECT review_status, reviewer_type FROM nazria.conversation_reviews "
                        "WHERE conversation_uid=%s", (a,)).fetchone() == ("rejected", "human")
    # AI review on a fresh row, then a human override (reviewer_type is derived from the reviewer name)
    assert save_ai_review(conn, b, "approved", "ai:fake/m", "ok", {"status": "approved"})
    conn.execute("UPDATE nazria.conversation_reviews SET review_status='needs_edit', reviewer='Hakeem B' "
                 "WHERE conversation_uid=%s", (b,))
    row = conn.execute("SELECT review_status, reviewer_type, ai_details->>'status' FROM nazria.conversation_reviews "
                       "WHERE conversation_uid=%s", (b,)).fetchone()
    assert row == ("needs_edit", "human", "approved")
    assert not save_ai_review(conn, b, "approved", "ai:fake/m", "again", {"status": "approved"})


def test_training_export_modes_edits_and_hazard_filter(conn):
    conn.execute(SCHEMA)
    from nazria_kb.reviewer import save_ai_review
    h, ai, haz, pend = (str(uuid.uuid4()) for _ in range(4))
    for u in (h, ai, pend):
        _seed_conversation(conn, u)
    _seed_conversation(conn, haz, hazard=True)
    conn.execute("INSERT INTO nazria.conversation_reviews (conversation_uid, review_status, reviewer, edited_turns) "
                 "VALUES (%s,'approved','Hakeem A','[{\"turn_index\":1,\"content\":\"اصلاح شدہ جواب\"}]')", (h,))
    save_ai_review(conn, ai, "approved", "ai:fake/m", "ok", {})
    conn.execute("INSERT INTO nazria.conversation_reviews (conversation_uid, review_status, reviewer) "
                 "VALUES (%s,'approved','Hakeem A')", (haz,))
    q = "SELECT conversation_uid::text FROM nazria.training_messages(%s, %s)"
    assert {r[0] for r in conn.execute(q, ("human_only", False))} == {h}
    assert {r[0] for r in conn.execute(q, ("human_or_ai", False))} == {h, ai}
    assert {r[0] for r in conn.execute(q, ("human_only", True))} == {h, haz}
    rec = conn.execute("SELECT record FROM nazria.training_messages('human_only') ").fetchone()[0]
    assert rec["messages"][-1] == {"role": "assistant", "content": "اصلاح شدہ جواب"}
    import psycopg
    with pytest.raises(psycopg.errors.RaiseException):
        conn.execute("SELECT * FROM nazria.training_messages('everything')")


def test_save_session_logs_llm_telemetry(conn):
    conn.execute(SCHEMA)
    from nazria_kb.db import save_session
    from nazria_kb.engine import Session
    s = Session(engine="hybrid", provider="openai", model="m", status="completed", external_provider=True,
                transcript=[{"role": "patient", "content": "قبض", "question_id": None},
                            {"role": "hakeem", "content": "جواب", "question_id": None, "provider": "openai",
                             "model": "m", "prompt_tokens": 10, "completion_tokens": 5, "latency_ms": 80,
                             "source_chunk_ids": [3, 4]}])
    save_session(conn, s)
    assert conn.execute("SELECT provider, external_provider FROM nazria.consultation_sessions").fetchone() == ("openai", True)
    assert conn.execute("SELECT prompt_tokens, completion_tokens, latency_ms, source_chunk_ids FROM "
                        "nazria.consultation_messages WHERE message_index=1").fetchone() == (10, 5, 80, [3, 4])


def test_full_load_twice_keeps_reviews_and_question_bank(conn, tmp_path):
    """End-to-end load of a small synthetic book, twice: TRUNCATE (without CASCADE) must succeed, and
    reviews / questionnaire edits must survive the reload."""
    from test_pipeline import _row
    from nazria_kb.db import load, verify
    from nazria_kb.pipeline import build
    pages = [
        "# کلیات تحقیقات صابر ملتانی\n## تحقیقات و علاج نزلہ و زکام\n۱۰\n\n## کھانسی\n\n### علامات\n\n"
        "گلے میں خراش ہوتی ہے۔ رات کو کھانسی بڑھ جاتی ہے۔ بلغم خارج ہوتا ہے۔ سینے میں بوجھ محسوس ہوتا ہے۔\n\n"
        "### اسباب\n\nسردی لگنا اور ٹھنڈی اشیاء کا استعمال، جو عضلاتی اعصابی تحریک پیدا کرتے ہیں۔",
        "# کلیات تحقیقات صابر ملتانی\n## تحقیقات و علاج نزلہ و زکام\n۱۱\n\n### نسخہ\n\nگل بنفشہ پانچ حصے، بادیان تین حصے، "
        "ملٹھی دو حصے، سب کو باریک پیس لیں۔\n\n**مقدار خوراک:** ایک ماشہ دن میں تین بار۔\n\n### پرہیز\n\nٹھنڈی اشیاء سے پرہیز کریں۔",
    ]
    csv = tmp_path / "book.csv"
    csv.write_text("".join(_row(100 + i, v, 10 + i, t) for v in (1, 2) for i, t in enumerate(pages)), encoding="utf-8")
    ds = build(csv)
    conn.autocommit = False
    load(conn, ds)
    conn.commit()
    uid = conn.execute("SELECT conversation_uid FROM nazria.conversations LIMIT 1").fetchone()[0]
    conn.execute("INSERT INTO nazria.conversation_reviews (conversation_uid, review_status, reviewer) "
                 "VALUES (%s,'approved','Hakeem A')", (uid,))
    conn.execute("UPDATE nazria.questionnaire_options SET weights='{\"عضلاتی\": 3}' "
                 "WHERE question_id='urine_color' AND option_key='red'")
    conn.commit()
    load(conn, ds)                                   # reload
    conn.commit()
    assert conn.execute("SELECT review_status FROM nazria.v_conversations WHERE conversation_uid=%s",
                        (uid,)).fetchone()[0] == "approved"
    assert conn.execute("SELECT weights FROM nazria.questionnaire_options WHERE question_id='urine_color' "
                        "AND option_key='red'").fetchone()[0] == {"عضلاتی": 3}
    checks = {name: ok for name, ok, _ in verify(conn)}
    assert len(checks) == 12 and checks["last ingest run succeeded"] and checks["questionnaire bank seeded"]
    conn.rollback()
    conn.autocommit = True


def test_citation_corrections_respect_hakeem_edits(conn):
    conn.execute(SCHEMA)
    from nazria_kb.db import seed_questionnaire
    conn.execute("INSERT INTO nazria.questionnaire_questions VALUES ('taste',1,'single','signs','x',true),"
                 "('catarrh',2,'single','signs','y',true)")
    from psycopg.types.json import Jsonb
    conn.execute("INSERT INTO nazria.questionnaire_options VALUES ('taste','sweet',1,'میٹھا',%s,2,'{125,126}'),"
                 "('catarrh','yes',0,'ہاں',%s,2,'{200}')", (Jsonb({"غدی": 1}), Jsonb({"اعصابی": 1})))  # catarrh: Hakeem edit
    seed_questionnaire(conn.cursor())
    rows = dict(conn.execute("SELECT question_id, source_pages FROM nazria.questionnaire_options "
                             "WHERE option_key IN ('sweet','yes') AND question_id IN ('taste','catarrh')").fetchall())
    assert rows == {"taste": [125], "catarrh": [200]}
