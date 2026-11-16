"""PostgreSQL loader.

* Applies ``sql/schema.sql`` (idempotent).
* Full refresh inside ONE transaction: data tables are truncated and reloaded
  with COPY; on any error everything rolls back and the previous data stays.
* ``conversation_reviews`` (expert review state) and ``ingest_runs`` are never
  truncated – reviews re-attach through the deterministic ``conversation_uid``.
"""
from __future__ import annotations

import logging
from pathlib import Path

import psycopg
from psycopg.types.json import Jsonb

from . import PIPELINE_VERSION
from .normalize import search_key
from .pipeline import AUTHOR, BOOKS, PUBLISHER, Dataset
from .questionnaire import DEFAULT_QUESTIONS, SOURCE_BOOK, Option, Question
from .safety import hazard_flags

log = logging.getLogger("nazria_kb")
SCHEMA_SQL = Path(__file__).resolve().parent.parent / "sql" / "schema.sql"

DATA_TABLES = ["conversation_turns", "conversations", "diet_guidelines", "remedy_ingredients", "remedies",
               "diseases", "knowledge_chunks", "topic_sections", "topics", "source_pages", "treatises", "books"]


def connect(dsn: str) -> psycopg.Connection:
    return psycopg.connect(dsn, application_name="nazria_kb_loader", connect_timeout=20)


def apply_schema(conn: psycopg.Connection) -> None:
    conn.execute(SCHEMA_SQL.read_text(encoding="utf-8"))


def _copy(cur: psycopg.Cursor, table: str, cols: list[str], rows) -> int:
    n = 0
    with cur.copy(f"COPY nazria.{table} ({', '.join(cols)}) FROM STDIN") as cp:
        for r in rows:
            cp.write_row(r)
            n += 1
    return n


def load(conn: psycopg.Connection, ds: Dataset) -> dict:
    stats = ds.stats()
    with conn.transaction():
        apply_schema(conn)
        cur = conn.cursor()
        run_id = cur.execute(
            "INSERT INTO nazria.ingest_runs (pipeline_version, source_file, source_sha256) VALUES (%s,%s,%s) RETURNING run_id",
            (PIPELINE_VERSION, Path(ds.source_path).name, ds.source_sha256)).fetchone()[0]
        cur.execute("TRUNCATE " + ", ".join(f"nazria.{t}" for t in DATA_TABLES) + " RESTART IDENTITY CASCADE")

        # books
        page_counts = {v: sum(1 for p in ds.pages if p.volume_no == v) for v in BOOKS}
        _copy(cur, "books", ["book_id", "volume_no", "title", "volume_name", "author", "publisher", "page_count"],
              [(v, v, b["title"], b["volume_name"], AUTHOR, PUBLISHER, page_counts[v]) for v, b in BOOKS.items()])

        # treatises
        _copy(cur, "treatises", ["book_id", "ordinal", "title", "title_variants", "start_page", "end_page", "page_count"],
              [(t.volume_no, t.ordinal, t.title, t.variants[1:], t.pages[0], t.pages[-1], len(t.pages)) for t in ds.treatises])
        tr_id = dict(cur.execute("SELECT ordinal, treatise_id FROM nazria.treatises").fetchall())

        # source pages
        raw_by_key = {(r.volume_no, r.page_no): r for r in ds.raw_pages}
        def page_rows():
            for p in ds.pages:
                r = raw_by_key[(p.volume_no, p.page_no)]
                yield (p.volume_no, p.page_no, p.printed_page_no, tr_id[ds.page_treatise[(p.volume_no, p.page_no)]],
                       r.legacy_id, r.page_key, r.image_file, r.source_section_id, r.ocr_text, r.html_text or None,
                       r.corrected_text or None, p.text, r.ocr_status, r.review_status, r.is_corrected,
                       r.ocr_completed_at, r.reviewed_at, p.quality_score, p.flags, p.unclear_count, p.raw_chars,
                       len(p.text), r.audio_status, r.audio_file, r.audio_duration_s)
        _copy(cur, "source_pages",
              ["book_id", "page_no", "printed_page_no", "treatise_id", "legacy_id", "page_key", "image_file",
               "source_section_id", "raw_ocr_text", "raw_html", "corrected_text", "clean_text", "ocr_status",
               "review_status", "is_corrected", "ocr_completed_at", "reviewed_at", "quality_score", "quality_flags",
               "unclear_count", "raw_char_count", "clean_char_count", "audio_status", "audio_file", "audio_duration_s"],
              page_rows())

        # topics + sections
        _copy(cur, "topics", ["book_id", "treatise_id", "ordinal", "title", "title_key", "topic_type", "tehreek_code",
                              "tehreek_counts", "roles", "pages", "start_page", "end_page", "full_text", "char_count"],
              [(t.volume_no, tr_id[t.treatise_ordinal], i, t.title, search_key(t.title), t.topic_type, t.tehreek,
                Jsonb(t.tehreek_counts), t.roles, t.pages, t.pages[0], t.pages[-1], t.text, len(t.text))
               for i, t in enumerate(ds.topics)])
        topic_id = dict(cur.execute("SELECT ordinal, topic_id FROM nazria.topics").fetchall())
        _copy(cur, "topic_sections", ["topic_id", "ordinal", "role", "heading", "content", "pages"],
              [(topic_id[i], si, s.role, s.heading or None, s.text, s.pages)
               for i, t in enumerate(ds.topics) for si, s in enumerate(t.sections)])
        topic_ord = {v: k for k, v in topic_id.items()}
        section_id = {(topic_ord[tid], o): sid for sid, tid, o in
                      cur.execute("SELECT section_id, topic_id, ordinal FROM nazria.topic_sections").fetchall()}

        # chunks
        page_q = {(p.volume_no, p.page_no): p.quality_score for p in ds.pages}
        def chunk_rows():
            for c in ds.chunks:
                t = ds.topics[c.topic_index]
                q = sum(page_q.get((c.volume_no, p), 0.8) for p in c.pages) / max(1, len(c.pages))
                yield (c.volume_no, tr_id[c.treatise_ordinal], topic_id[c.topic_index],
                       section_id[(c.topic_index, c.section_index)], c.ordinal, c.role, c.context, c.text,
                       search_key(c.text), len(c.text), len(c.text.split()), c.pages, c.pages[0], c.pages[-1],
                       t.tehreek, round(q, 2))
        _copy(cur, "knowledge_chunks",
              ["book_id", "treatise_id", "topic_id", "section_id", "ordinal", "role", "context_path", "content",
               "search_text", "char_count", "word_count", "pages", "start_page", "end_page", "tehreek_code",
               "quality_score"], chunk_rows())
        chunk_ids: dict[int, list[int]] = {}
        for cid, sid in cur.execute("SELECT chunk_id, section_id FROM nazria.knowledge_chunks ORDER BY section_id, ordinal"):
            chunk_ids.setdefault(sid, []).append(cid)

        # diseases / remedies / ingredients / diet
        _copy(cur, "diseases", ["topic_id", "name", "name_key", "tehreek_code", "definition", "causes", "symptoms",
                                "diagnosis", "treatment", "pages"],
              [(topic_id[d.topic_index], d.name, search_key(d.name), d.tehreek, d.definition, d.causes, d.symptoms,
                d.diagnosis, d.treatment, d.pages) for d in ds.diseases])
        disease_by_topic = {k: v for v, k in cur.execute("SELECT disease_id, topic_id FROM nazria.diseases")}
        rem_rows = []
        for r in ds.remedies:
            tid = topic_id[r.topic_index]
            rem_rows.append((tid, disease_by_topic.get(tid) if r.indication else None, r.name, search_key(r.name),
                             r.dosage_form, r.composition_text, r.preparation_text, r.dosage_text, r.actions_text,
                             r.caution_text, r.indication, r.tehreek, r.pages or ds.topics[r.topic_index].pages,
                             hazard_flags(" ".join(x for x in (r.composition_text, r.preparation_text) if x))))
        ids = []
        for row in rem_rows:  # small table: row inserts keep a reliable position -> id mapping
            ids.append(cur.execute(
                "INSERT INTO nazria.remedies (topic_id, disease_id, name, name_key, dosage_form, composition_text, "
                "preparation_text, dosage_text, actions_text, caution_text, indication, tehreek_code, pages, hazard_flags) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING remedy_id", row).fetchone()[0])
        _copy(cur, "remedy_ingredients", ["remedy_id", "ordinal", "ingredient_name", "quantity_text", "quantity_value", "unit"],
              [(rid, i.ordinal, i.name, i.quantity_text, i.quantity_value, i.unit)
               for rid, r in zip(ids, ds.remedies) for i in r.ingredients])
        _copy(cur, "diet_guidelines", ["topic_id", "disease_id", "kind", "content", "items", "pages"],
              [(topic_id[d.topic_index], disease_by_topic.get(topic_id[d.topic_index]), d.kind, d.text, d.items,
                d.pages) for d in ds.diets])

        # conversations + turns
        _copy(cur, "conversations", ["conversation_uid", "conv_type", "title", "topic_id", "book_id", "template_id",
                                     "generator", "seed", "system_prompt", "turn_count", "pages", "quality_score",
                                     "hazard_flags"],
              [(uid, c.conv_type, c.title, topic_id[c.topic_index], c.volume_no, c.template_id, c.generator, c.seed,
                c.system_prompt, len(c.turns), c.pages, c.quality_score,
                hazard_flags(" ".join(t.content for t in c.turns if t.role == "hakeem")))
               for uid, c in zip(ds.conversation_uids, ds.conversations)])
        conv_id = {str(u): i for i, u in cur.execute("SELECT conversation_id, conversation_uid FROM nazria.conversations")}

        def turn_rows():
            for uid, c in zip(ds.conversation_uids, ds.conversations):
                for k, tn in enumerate(c.turns):
                    sids = [section_id[r] for r in tn.refs if r in section_id]
                    cids = [x for s in sids for x in chunk_ids.get(s, [])]
                    yield (conv_id[uid], k, tn.role, tn.content, sids, cids)
        _copy(cur, "conversation_turns", ["conversation_id", "turn_index", "role", "content", "source_section_ids",
                                          "source_chunk_ids"], turn_rows())

        seed_questionnaire(cur)
        counts = dict(cur.execute("SELECT item, n FROM nazria.v_dataset_summary").fetchall())
        stats["db_counts"] = counts
        cur.execute("UPDATE nazria.ingest_runs SET status='succeeded', finished_at=now(), stats=%s WHERE run_id=%s",
                    (Jsonb(stats), run_id))
    log.info("load committed: %s", counts)
    return stats


def verify(conn: psycopg.Connection) -> list[tuple[str, bool, str]]:
    """Post-load integrity checks. Returns (check, passed, detail)."""
    q = lambda sql: conn.execute(sql).fetchone()[0]  # noqa: E731
    checks = [
        ("pages loaded (expected 1879)", q("SELECT count(*) FROM nazria.source_pages") == 1879,
         str(q("SELECT count(*) FROM nazria.source_pages"))),
        ("both volumes present", q("SELECT count(DISTINCT book_id) FROM nazria.source_pages") == 2, ""),
        ("every page has a treatise", q("SELECT count(*) FROM nazria.source_pages WHERE treatise_id IS NULL") == 0, ""),
        ("no empty chunks", q("SELECT count(*) FROM nazria.knowledge_chunks WHERE length(content) = 0") == 0, ""),
        ("every hakeem turn is grounded (except greetings/closings)",
         q("""SELECT count(*) FROM nazria.conversation_turns t JOIN nazria.conversations c USING (conversation_id)
              WHERE t.role='hakeem' AND c.conv_type='qa' AND cardinality(t.source_chunk_ids)=0""") == 0, ""),
        ("every conversation has >= 2 turns",
         q("SELECT count(*) FROM nazria.conversations WHERE turn_count < 2") == 0, ""),
        ("turns alternate starting with patient",
         q("""SELECT count(*) FROM nazria.conversation_turns
              WHERE (turn_index % 2 = 0 AND role <> 'patient') OR (turn_index % 2 = 1 AND role <> 'hakeem')""") == 0, ""),
        ("full-text search works (query: علاج)",
         q("SELECT count(*) FROM nazria.knowledge_chunks WHERE tsv @@ to_tsquery('simple','علاج')") > 0,
         str(q("SELECT count(*) FROM nazria.knowledge_chunks WHERE tsv @@ to_tsquery('simple','علاج')"))),
        ("questionnaire bank seeded",
         q("SELECT count(*) FROM nazria.questionnaire_questions WHERE active") >= 10,
         str(q("SELECT count(*) FROM nazria.questionnaire_questions WHERE active"))),
        ("every scored option cites a source page",
         q("""SELECT count(*) FROM nazria.questionnaire_options
              WHERE weights <> '{}'::jsonb AND cardinality(source_pages) = 0""") == 0, ""),
        ("hazardous remedies flagged",
         q("SELECT count(*) FROM nazria.remedies WHERE cardinality(hazard_flags) > 0") > 0,
         str(q("SELECT count(*) FROM nazria.remedies WHERE cardinality(hazard_flags) > 0"))),
        ("last ingest run succeeded",
         q("SELECT status FROM nazria.ingest_runs ORDER BY run_id DESC LIMIT 1") == "succeeded", ""),
    ]
    return checks


# --------------------------------------------------------------------------- questionnaire
def seed_questionnaire(cur, questions: list[Question] = DEFAULT_QUESTIONS) -> None:
    """Insert missing questions/options. Never overwrites rows a Hakeem has edited."""
    for qi, q in enumerate(questions):
        cur.execute("INSERT INTO nazria.questionnaire_questions (question_id, ordinal, kind, stage, text_ur) "
                    "VALUES (%s,%s,%s,%s,%s) ON CONFLICT (question_id) DO NOTHING", (q.id, qi, q.kind, q.stage, q.text))
        for oi, o in enumerate(q.options):
            cur.execute("INSERT INTO nazria.questionnaire_options (question_id, option_key, ordinal, label_ur, weights, "
                        "source_book_id, source_pages) VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                        (q.id, o.key, oi, o.label, Jsonb(o.weights), SOURCE_BOOK if o.pages else None, o.pages))


def load_questions(conn: psycopg.Connection) -> list[Question]:
    """Active question bank from the DB (with any Hakeem edits); built-in defaults if not seeded."""
    try:
        qrows = conn.execute("SELECT question_id, kind, stage, text_ur FROM nazria.questionnaire_questions "
                             "WHERE active ORDER BY ordinal").fetchall()
    except psycopg.errors.UndefinedTable:
        conn.rollback()
        return DEFAULT_QUESTIONS
    if not qrows:
        return DEFAULT_QUESTIONS
    opts: dict[str, list[Option]] = {}
    for qid, key, label, weights, pages in conn.execute(
            "SELECT question_id, option_key, label_ur, weights, source_pages FROM nazria.questionnaire_options "
            "ORDER BY question_id, ordinal"):
        opts.setdefault(qid, []).append(Option(key, label, dict(weights), list(pages)))
    return [Question(qid, kind, text, stage, opts.get(qid, [])) for qid, kind, stage, text in qrows]


def save_session(conn: psycopg.Connection, session) -> None:
    """Upsert a consultation session and its transcript (idempotent per message index)."""
    with conn.transaction():
        conn.execute(
            """INSERT INTO nazria.consultation_sessions (session_uid, engine, provider, model, status, answers, result)
               VALUES (%s,%s,%s,%s,%s,%s,%s)
               ON CONFLICT (session_uid) DO UPDATE SET status = EXCLUDED.status, answers = EXCLUDED.answers,
                   result = EXCLUDED.result, updated_at = now()""",
            (session.session_uid, session.engine, session.provider, session.model, session.status,
             Jsonb(session.answers), Jsonb(session.result)))
        for i, m in enumerate(session.transcript):
            conn.execute(
                """INSERT INTO nazria.consultation_messages (session_uid, message_index, role, content, question_id)
                   VALUES (%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING""",
                (session.session_uid, i, m["role"], m["content"], m.get("question_id")))
