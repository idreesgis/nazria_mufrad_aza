"""NAZRIA_DATABASE_URL -> Django DATABASES entry (no third-party parser; the URL is never logged)."""
from __future__ import annotations

from urllib.parse import parse_qsl, unquote, urlsplit

from nazria_kb.db import normalize_dsn

_KNOWN_OPTIONS = {"sslmode", "sslrootcert", "sslcert", "sslkey", "connect_timeout", "application_name",
                  "target_session_attrs"}


def database_from_url(url: str, schema: str, conn_max_age: int = 60) -> dict:
    """``postgresql://user:pass@host:5432/db?sslmode=require`` (``postgis://`` accepted) for Django.

    ``schema`` becomes the only entry of the search_path, so Django's own tables (API clients, admin users,
    migrations) are created there and never in ``public`` of a shared database. The knowledge-base queries are
    schema-qualified (``nazria.*``) and unaffected.
    """
    parts = urlsplit(normalize_dsn(url))
    if parts.scheme not in ("postgresql", "postgres"):
        raise ValueError("NAZRIA_DATABASE_URL must be a postgresql:// URL")
    query = dict(parse_qsl(parts.query))
    host = query.pop("host", None) or parts.hostname or ""          # ?host=/var/run/postgresql (Unix socket)
    port = query.pop("port", None) or (str(parts.port) if parts.port else "")
    unknown = sorted(set(query) - _KNOWN_OPTIONS)
    if unknown:
        raise ValueError(f"unsupported NAZRIA_DATABASE_URL options: {', '.join(unknown)}")
    options = {k: v for k, v in query.items()}
    options["options"] = f"-c search_path={schema}"
    return {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": unquote(parts.path.lstrip("/")),
        "USER": unquote(parts.username or ""),
        "PASSWORD": unquote(parts.password or ""),
        "HOST": host,
        "PORT": port,
        "CONN_MAX_AGE": conn_max_age,
        "CONN_HEALTH_CHECKS": True,
        "OPTIONS": options,
    }
