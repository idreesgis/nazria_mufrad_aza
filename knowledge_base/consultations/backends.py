"""Where the API reads the book and stores consultations.

* ``PostgresKnowledgeBase`` (production): the ``nazria`` schema in the same PostgreSQL database as Django, through
  Django's own connection (psycopg 3), using the existing ``nazria_kb`` functions unchanged.
* ``MemoryKnowledgeBase`` (tests, offline demo): a small built-in book excerpt and an in-memory session store.
"""
from __future__ import annotations

import threading
import time
from typing import Protocol

from django.conf import settings
from django.utils.module_loading import import_string

from nazria_kb.engine import Passage, PostgresRetriever, Retriever, Session, TopicHit
from nazria_kb.questionnaire import DEFAULT_QUESTIONS, Question


class KnowledgeBase(Protocol):
    def questions(self) -> list[Question]: ...
    def retriever(self) -> Retriever: ...
    def save_session(self, session: Session) -> None: ...
    def load_session(self, session_uid: str) -> Session | None: ...
    def delete_session(self, session_uid: str) -> bool: ...
    def session_summaries(self, session_uids: list[str]) -> dict[str, dict]: ...
    def ping(self) -> None: ...


class PostgresKnowledgeBase:
    def __init__(self, connection_factory=None, cache_seconds: int | None = None):
        self._factory = connection_factory or self._django_connection
        self._cache_s = settings.NAZRIA_QUESTIONS_CACHE_S if cache_seconds is None else cache_seconds
        self._questions: tuple[float, list[Question]] | None = None
        self._lock = threading.Lock()

    @staticmethod
    def _django_connection():
        """The raw psycopg connection behind Django's (per thread, autocommit, search_path = API schema).
        All knowledge-base SQL is schema-qualified (nazria.*)."""
        from django.db import connection
        connection.ensure_connection()
        return connection.connection

    def questions(self) -> list[Question]:
        from nazria_kb.db import load_questions
        now = time.monotonic()
        with self._lock:
            if self._questions and now - self._questions[0] < self._cache_s:
                return self._questions[1]
        qs = load_questions(self._factory())
        with self._lock:
            self._questions = (now, qs)
        return qs

    def retriever(self) -> Retriever:
        return PostgresRetriever(self._factory())

    def save_session(self, session: Session) -> None:
        from nazria_kb.db import save_session
        save_session(self._factory(), session)

    def load_session(self, session_uid: str) -> Session | None:
        from nazria_kb.db import load_session
        return load_session(self._factory(), session_uid)

    def delete_session(self, session_uid: str) -> bool:
        from nazria_kb.db import delete_session
        return delete_session(self._factory(), session_uid)

    def session_summaries(self, session_uids: list[str]) -> dict[str, dict]:
        """{uid: {"complaint", "status", "primary_system"}} for history lists (one query)."""
        if not session_uids:
            return {}
        rows = self._factory().execute(
            "SELECT session_uid::text, answers->>'complaint', status, result->>'primary_system' "
            "FROM nazria.consultation_sessions WHERE session_uid = ANY(%s::uuid[])", (list(session_uids),)).fetchall()
        return {uid: {"complaint": c or "", "status": st, "primary_system": ps} for uid, c, st, ps in rows}

    def ping(self) -> None:
        self._factory().execute("SELECT 1 FROM nazria.schema_version LIMIT 1").fetchone()


# --------------------------------------------------------------------------- in memory
DEMO_TOPICS = [
    TopicHit(1603, "عضلاتی قبض", 2, [127], None, [
        ("definition", "عضلاتی قبض اکثر شدید ہوتی ہے اور یہی قبض دائمی بھی ہوتی ہے۔ اس قسم کی قبض میں ریاح اور نفخ شکم "
                       "کی زیادتی ہوتی ہے اور ایسے مریض کا قارورہ سرخ یا زردی مائل سرخ ہوتا ہے۔ • نسخہ: سناکی، تیز پات۔ "
                       "دونوں ہم وزن سفوف کر لیں۔", [127]),
        ("dosage", "2 رتی سے 2 ماشہ تک ہمراہ آب تازہ", [127]),
        ("diet", "ٹھنڈی اشیاء سے پرہیز کریں۔", [127])]),
    TopicHit(77, "دمہ", 2, [133], "عضلاتی غدی", [
        ("symptoms", "سانس پھولتا ہے اور سینے میں گھٹن رہتی ہے۔", [133]),
        ("recipe", "کشتہ سنکھیا ایک رتی، شنگرف دو رتی", [133])]),
]
DEMO_PASSAGES = [
    Passage("تحقیقات المجربات › عضلاتی قبض", "عضلاتی قبض اکثر شدید ہوتی ہے اور یہی قبض دائمی بھی ہوتی ہے۔ "
            "ایسے مریض کا قارورہ سرخ ہوتا ہے۔", 2, [127], 3412),
    Passage("تحقیقات المجربات › نزلہ", "نزلہ میں سر بھاری رہتا ہے اور ناک سے رطوبت بہتی ہے۔", 2, [128], 3500),
]


class MemoryRetriever:
    def __init__(self, topics: list[TopicHit] | None = None, passages: list[Passage] | None = None):
        self.topics = DEMO_TOPICS if topics is None else topics
        self.passage_list = DEMO_PASSAGES if passages is None else passages

    def topics_for(self, complaint: str, system: str | None, limit: int = 3) -> list[TopicHit]:
        from nazria_kb.engine import complaint_tokens
        toks = complaint_tokens(complaint)
        hits = [t for t in self.topics if any(tok in t.title for tok in toks)]
        hits.sort(key=lambda t: bool(system and system in t.title), reverse=True)
        return hits[:limit]

    def passages(self, query: str, limit: int = 3) -> list[Passage]:
        from nazria_kb.engine import complaint_tokens
        toks = complaint_tokens(query)
        scored = sorted(((sum(p.content.count(t) for t in toks), i, p) for i, p in enumerate(self.passage_list)),
                        key=lambda x: (-x[0], x[1]))
        return [p for n, _, p in scored[:limit] if n]


class MemoryKnowledgeBase:
    def __init__(self, retriever: Retriever | None = None, questions: list[Question] | None = None):
        self._retriever = retriever or MemoryRetriever()
        self._questions = questions or DEFAULT_QUESTIONS
        self.sessions: dict[str, Session] = {}

    def questions(self) -> list[Question]:
        return self._questions

    def retriever(self) -> Retriever:
        return self._retriever

    def save_session(self, session: Session) -> None:
        stored = Session.from_dict(session.to_dict())
        stored.meta = {}                      # meta (engine scratch state) is not stored, as in PostgreSQL
        self.sessions[session.session_uid] = stored

    def load_session(self, session_uid: str) -> Session | None:
        s = self.sessions.get(str(session_uid))
        return Session.from_dict(s.to_dict()) if s else None

    def delete_session(self, session_uid: str) -> bool:
        return self.sessions.pop(str(session_uid), None) is not None

    def session_summaries(self, session_uids: list[str]) -> dict[str, dict]:
        return {u: {"complaint": s.answers.get("complaint", ""), "status": s.status,
                    "primary_system": s.result.get("primary_system")}
                for u in session_uids if (s := self.sessions.get(str(u)))}

    def ping(self) -> None:
        return None


_instance: KnowledgeBase | None = None
_instance_lock = threading.Lock()


def knowledge_base() -> KnowledgeBase:
    """The configured backend (settings.NAZRIA_KB_BACKEND), one per process."""
    global _instance
    with _instance_lock:
        if _instance is None:
            name = settings.NAZRIA_KB_BACKEND
            _instance = PostgresKnowledgeBase() if name == "postgres" else import_string(name)()
        return _instance


def set_knowledge_base(kb: KnowledgeBase | None) -> None:
    """Replace the backend (tests)."""
    global _instance
    with _instance_lock:
        _instance = kb
