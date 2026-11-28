"""The API test suite on a real PostgreSQL instead of SQLite:

    NAZRIA_TEST_DATABASE_URL=postgresql://user:pass@127.0.0.1:5432/scratch \\
        python -m pytest tests/api --ds=nazria_api.settings_test_pg          (add NAZRIA_ALLOW_POSTGRES_12=true for 12/13)

Django creates (and afterwards drops) its own test database "test_<name>" there; the user needs CREATEDB. Never
uses NAZRIA_DATABASE_URL."""
import os

from .settings_test import *  # noqa: F401,F403
from .dburl import database_from_url
from nazria_kb.providers import env_flag

_url = os.environ.get("NAZRIA_TEST_DATABASE_URL")
if not _url:
    raise RuntimeError("set NAZRIA_TEST_DATABASE_URL to a disposable PostgreSQL database")
DATABASES = {"default": database_from_url(_url, "public", 0)}           # the fresh test database: schema public
if env_flag("NAZRIA_ALLOW_POSTGRES_12", False):
    DATABASES["default"]["ENGINE"] = "nazria_api.db_pg12"
