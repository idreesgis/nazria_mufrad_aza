"""Test settings: Django's own tables in SQLite, the knowledge base in memory (no PostgreSQL needed).
The PostgreSQL path is covered by tests/api/test_postgres_backend.py when NAZRIA_TEST_DATABASE_URL is set."""
import os

os.environ.setdefault("DJANGO_SECRET_KEY", "test-only-secret-key-not-for-production")
os.environ.setdefault("NAZRIA_DATABASE_URL", "postgresql://unused@localhost/unused")

from .settings import *  # noqa: E402,F401,F403

DEBUG = False
DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}
NAZRIA_KB_BACKEND = "consultations.backends.MemoryKnowledgeBase"
NAZRIA_API_DOCS = True
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]      # fast tests only
REST_FRAMEWORK = {**REST_FRAMEWORK, "DEFAULT_THROTTLE_RATES": {  # noqa: F405
    "user": "1000/min", "explanation": "1000/min", "auth": "1000/min", "pulse": "1000/min"}}
import tempfile  # noqa: E402

MEDIA_ROOT = tempfile.mkdtemp(prefix="nazria-test-media-")
