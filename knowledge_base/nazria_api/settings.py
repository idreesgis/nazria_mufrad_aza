"""Django settings for the Nazria REST API. Everything comes from environment variables (see .env.example);
secrets are never written to this file, git, the database or the logs.

Required in production: DJANGO_SECRET_KEY, DJANGO_ALLOWED_HOSTS, NAZRIA_DATABASE_URL.
"""
from __future__ import annotations

import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

from nazria_kb.providers import env_flag

from .dburl import database_from_url

BASE_DIR = Path(__file__).resolve().parent.parent
env = os.environ.get

DEBUG = env_flag("DJANGO_DEBUG", False)
SECRET_KEY = env("DJANGO_SECRET_KEY") or ""
if not SECRET_KEY:
    if not DEBUG:
        raise ImproperlyConfigured("set DJANGO_SECRET_KEY (or DJANGO_DEBUG=true for local development)")
    SECRET_KEY = "insecure-local-development-key-only"          # DEBUG only
ALLOWED_HOSTS = [h.strip() for h in (env("DJANGO_ALLOWED_HOSTS") or ("localhost,127.0.0.1,10.0.2.2" if DEBUG else "")).split(",")
                 if h.strip()]   # 10.0.2.2 = the host machine seen from the Android emulator

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "drf_spectacular",
    "consultations",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "nazria_api.urls"
WSGI_APPLICATION = "nazria_api.wsgi.application"
ASGI_APPLICATION = "nazria_api.asgi.application"

TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "DIRS": [],
    "APP_DIRS": True,
    "OPTIONS": {"context_processors": [
        "django.template.context_processors.request",
        "django.contrib.auth.context_processors.auth",
        "django.contrib.messages.context_processors.messages",
    ]},
}]

# ---------------------------------------------------------------- database
# One PostgreSQL database: the knowledge base lives in schema "nazria" (sql/schema.sql, loaded by
# `python -m nazria_kb load`); Django's own tables live in NAZRIA_API_DB_SCHEMA (default "nazria_api").
# Create that schema once with `python manage.py create_api_schema`, then `python manage.py migrate`.
NAZRIA_API_DB_SCHEMA = env("NAZRIA_API_DB_SCHEMA") or "nazria_api"
_db_url = env("NAZRIA_DATABASE_URL")
if not _db_url:
    raise ImproperlyConfigured("set NAZRIA_DATABASE_URL (its value is never printed)")
DATABASES = {"default": database_from_url(_db_url, NAZRIA_API_DB_SCHEMA, int(env("NAZRIA_DB_CONN_MAX_AGE") or 60))}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 12}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en"
TIME_ZONE = env("DJANGO_TIME_ZONE") or "Asia/Karachi"
USE_I18N = True
USE_TZ = True
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

# Rate-limit counters: "locmem" (per process, fine for one process) or "db" (shared by all gunicorn workers; run
# `python manage.py createcachetable` once – the table is created in the API schema)
CACHES = {"default": {"BACKEND": "django.core.cache.backends.db.DatabaseCache", "LOCATION": "api_cache"}
          if (env("NAZRIA_API_CACHE") or "locmem") == "db" else
          {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}

# ---------------------------------------------------------------- REST framework
API_RATE = env("NAZRIA_API_RATE") or "60/min"                    # per API client, all endpoints
EXPLAIN_RATE = env("NAZRIA_API_EXPLAIN_RATE") or "10/min"        # per API client, AI explanations (cost)
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": ["consultations.authentication.ApiKeyAuthentication"],
    "DEFAULT_PERMISSION_CLASSES": ["consultations.authentication.HasApiClient"],
    "DEFAULT_THROTTLE_CLASSES": ["consultations.authentication.ClientRateThrottle"],
    "DEFAULT_THROTTLE_RATES": {"client": API_RATE, "explanation": EXPLAIN_RATE},
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"]
    + (["rest_framework.renderers.BrowsableAPIRenderer"] if DEBUG else []),
    "DEFAULT_PARSER_CLASSES": ["rest_framework.parsers.JSONParser"],
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "EXCEPTION_HANDLER": "consultations.views.exception_handler",
    "UNAUTHENTICATED_USER": None,
}
SPECTACULAR_SETTINGS = {
    "TITLE": "Nazria Mufrad Aza API",
    "DESCRIPTION": "Symptom questionnaire, book-based assessment and optional AI explanation for the Android app. "
                   "Guidance only, not a diagnosis.",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "COMPONENT_SPLIT_REQUEST": True,
}
# OpenAPI schema + Swagger UI at /api/schema/ and /api/docs/ (on in DEBUG; NAZRIA_API_DOCS=true to force)
NAZRIA_API_DOCS = env_flag("NAZRIA_API_DOCS", DEBUG)
# Django admin at /admin/ for staff (API clients, consultations); NAZRIA_ADMIN=false to switch off
NAZRIA_ADMIN = env_flag("NAZRIA_ADMIN", True)

# ---------------------------------------------------------------- knowledge base
# "postgres" (the nazria schema in the same database) or a dotted path to a KnowledgeBase class (tests)
NAZRIA_KB_BACKEND = env("NAZRIA_KB_BACKEND") or "postgres"
NAZRIA_QUESTIONS_CACHE_S = int(env("NAZRIA_QUESTIONS_CACHE_S") or 60)   # Hakeem edits show up within this time

# ---------------------------------------------------------------- security (production)
if not DEBUG:
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_REFERRER_POLICY = "same-origin"
    X_FRAME_OPTIONS = "DENY"
    if env_flag("DJANGO_BEHIND_HTTPS_PROXY"):            # e.g. nginx terminating TLS
        SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
        SECURE_SSL_REDIRECT = True
        SECURE_HSTS_SECONDS = int(env("DJANGO_HSTS_SECONDS") or 0)
CSRF_TRUSTED_ORIGINS = [o.strip() for o in (env("DJANGO_CSRF_TRUSTED_ORIGINS") or "").split(",") if o.strip()]
DATA_UPLOAD_MAX_MEMORY_SIZE = 64 * 1024             # consultation payloads are small

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"plain": {"format": "%(asctime)s %(levelname)s %(name)s %(message)s"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "plain"}},
    "root": {"handlers": ["console"], "level": env("DJANGO_LOG_LEVEL") or "INFO"},
    "loggers": {
        "django.db.backends": {"level": "WARNING"},          # never log SQL parameters (patient text)
        "httpx": {"level": "WARNING"},
    },
}
