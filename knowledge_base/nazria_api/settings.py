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
if os.environ.get("NAZRIA_ENV_FILE"):                 # e.g. /etc/nazria/nazria.env on the server (manage.py commands)
    from .envfile import load_env_file
    load_env_file(os.environ["NAZRIA_ENV_FILE"])
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
    "rest_framework_simplejwt.token_blacklist",
    "drf_spectacular",
    "allauth",                                         # social sign-in: providers, token checks, account links
    "allauth.account",
    "allauth.socialaccount",
    "allauth.socialaccount.providers.google",
    "allauth.socialaccount.providers.facebook",
    "allauth.socialaccount.providers.apple",
    "allauth.socialaccount.providers.microsoft",      # with accounts.social_providers.MicrosoftTokenProvider
    "accounts",
    "audit",
    "patients",
    "consultations",
    "pulse",
]

MIDDLEWARE = [
    "nazria_api.drain.DrainUnreadBodyMiddleware",                     # an unread upload never turns into a 502
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "allauth.account.middleware.AccountMiddleware",
    "audit.middleware.AuditMiddleware",                               # one audit row per API / admin request
    "nazria_api.language.ContentLanguageMiddleware",                  # Content-Language: ur | en | ar
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
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 8}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en"
TIME_ZONE = env("DJANGO_TIME_ZONE") or "Asia/Karachi"
USE_I18N = True
USE_TZ = True
STATIC_URL = "static/"
STATIC_ROOT = Path(env("NAZRIA_STATIC_ROOT") or BASE_DIR / "staticfiles")

# Rate-limit counters: "locmem" (per process, fine for one process) or "db" (shared by all gunicorn workers; run
# `python manage.py createcachetable` once – the table is created in the API schema)
CACHES = {"default": {"BACKEND": "django.core.cache.backends.db.DatabaseCache", "LOCATION": "api_cache"}
          if (env("NAZRIA_API_CACHE") or "locmem") == "db" else
          {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}

# ---------------------------------------------------------------- REST framework
# Every request needs the app key (X-Api-Key, NAZRIA_REQUIRE_APP_KEY); patient and staff endpoints also need a
# login token (Authorization: Bearer <access token> from /api/v1/auth/login/).
NAZRIA_REQUIRE_APP_KEY = env_flag("NAZRIA_REQUIRE_APP_KEY", True)
API_RATE = env("NAZRIA_API_RATE") or "60/min"                    # per logged-in user (per IP otherwise)
EXPLAIN_RATE = env("NAZRIA_API_EXPLAIN_RATE") or "10/min"        # AI explanations (provider cost)
AUTH_RATE = env("NAZRIA_API_AUTH_RATE") or "10/min"              # register / login / refresh, per IP
PULSE_RATE = env("NAZRIA_API_PULSE_RATE") or "10/min"            # video uploads
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": ["rest_framework_simplejwt.authentication.JWTAuthentication"],
    "DEFAULT_PERMISSION_CLASSES": ["accounts.permissions.HasAppKey", "rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_THROTTLE_CLASSES": ["accounts.throttles.UserRateThrottle"],
    "DEFAULT_THROTTLE_RATES": {"user": API_RATE, "explanation": EXPLAIN_RATE, "auth": AUTH_RATE, "pulse": PULSE_RATE},
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"]
    + (["rest_framework.renderers.BrowsableAPIRenderer"] if DEBUG else []),
    "DEFAULT_PARSER_CLASSES": ["rest_framework.parsers.JSONParser"],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 20,
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "EXCEPTION_HANDLER": "consultations.views.exception_handler",
}
from datetime import timedelta  # noqa: E402

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=int(env("NAZRIA_JWT_ACCESS_MINUTES") or 30)),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=int(env("NAZRIA_JWT_REFRESH_DAYS") or 30)),
    "ROTATE_REFRESH_TOKENS": True,            # each refresh returns a new refresh token …
    "BLACKLIST_AFTER_ROTATION": True,         # … and the old one stops working
    "UPDATE_LAST_LOGIN": True,
    "AUTH_HEADER_TYPES": ("Bearer",),
    "SIGNING_KEY": SECRET_KEY,
}
SPECTACULAR_SETTINGS = {
    "TITLE": "Nazria Mufrad Aza API",
    "DESCRIPTION": "Patient accounts, symptom questionnaire, book-based assessment, pulse-video analysis and optional "
                   "AI explanation for the Android app, with a complete audit log. Guidance only, not a diagnosis.",
    "VERSION": "2.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "COMPONENT_SPLIT_REQUEST": True,
    "ENUM_NAME_OVERRIDES": {
        "ConsultationStatusEnum": ["completed", "emergency"],
        "PulseStatusEnum": ["processing", "completed", "failed"],
        "ExplanationStatusEnum": ["shown", "not_covered", "rejected", "unavailable", "disabled"],
        "RecipeStatusEnum": ["shown", "withheld_vulnerable", "withheld_condition", "withheld_hazard"],
        "RoleEnum": ["patient", "hakeem", "admin"],
        "LanguageEnum": ["ur", "en", "ar"],
        "DirectionEnum": ["rtl", "ltr"],
        "SystemCodeEnum": ["nervous", "muscular", "glandular"],
        "SocialProviderEnum": ["google", "facebook", "apple", "microsoft"],
    },
    "POSTPROCESSING_HOOKS": ["drf_spectacular.hooks.postprocess_schema_enums",
                             "consultations.schema.add_app_key_header"],
}
# OpenAPI schema + Swagger UI at /api/schema/ and /api/docs/ (on in DEBUG; NAZRIA_API_DOCS=true to force)
NAZRIA_API_DOCS = env_flag("NAZRIA_API_DOCS", DEBUG)
# Django admin at /admin/ for staff (API clients, consultations); NAZRIA_ADMIN=false to switch off
NAZRIA_ADMIN = env_flag("NAZRIA_ADMIN", True)

# ---------------------------------------------------------------- patients and pulse videos
# Social sign-in (django-allauth). Every provider is off until its IDs are set; GET /health/ lists the ones that are on.
# Client / app IDs are public; NAZRIA_FACEBOOK_APP_SECRET is a secret: only in the server's env file, never in git.
def _ids(name: str) -> list[str]:
    return [c.strip() for c in (env(name) or "").split(",") if c.strip()]


# Google: the "Web application" OAuth client ID(s) the Android app passes as serverClientId (comma-separated)
NAZRIA_GOOGLE_CLIENT_IDS = _ids("NAZRIA_GOOGLE_CLIENT_IDS")
# The server's public https:// address (Sign in with Apple sends the patient back to it; Apple needs HTTPS)
NAZRIA_PUBLIC_URL = (env("NAZRIA_PUBLIC_URL") or "").rstrip("/")
SOCIALACCOUNT_PROVIDERS = {
    "google": {"APPS": [{"client_id": c, "secret": "", "key": ""} for c in NAZRIA_GOOGLE_CLIENT_IDS],
               "VERIFIED_EMAIL": False},                         # trust Google's own email_verified claim
    "facebook": {"APPS": [{"client_id": c, "secret": env("NAZRIA_FACEBOOK_APP_SECRET") or "", "key": ""}
                          for c in _ids("NAZRIA_FACEBOOK_APP_ID")[:1]],
                 "FIELDS": ["id", "email", "name", "first_name", "last_name"], "SCOPE": ["email", "public_profile"],
                 "VERIFIED_EMAIL": False, "EXCHANGE_TOKEN": False},
    # Apple: the Services ID first (web sign-in from Android), then iOS bundle IDs if any; no private key needed:
    # the server only checks the ID token
    "apple": {"APPS": [{"client_id": ",".join(_ids("NAZRIA_APPLE_CLIENT_IDS")), "secret": "", "key": "",
                        "settings": {"certificate_key": ""}}] if _ids("NAZRIA_APPLE_CLIENT_IDS") else []},
    # Microsoft: the Application (client) ID of the "Mobile and desktop" app registration; tenant common |
    # consumers | organizations | <tenant id>
    "microsoft": {"APPS": [{"client_id": c, "secret": "", "key": ""} for c in _ids("NAZRIA_MICROSOFT_CLIENT_ID")[:1]],
                  "TENANT": env("NAZRIA_MICROSOFT_TENANT") or "common",
                  "provider_class": "accounts.social_providers.MicrosoftTokenProvider"},
}
SOCIALACCOUNT_ADAPTER = "accounts.social.NazriaSocialAccountAdapter"
SOCIALACCOUNT_STORE_TOKENS = False                 # provider tokens are never stored
SOCIALACCOUNT_EMAIL_AUTHENTICATION = False         # never join accounts by e-mail address
SOCIALACCOUNT_EMAIL_AUTHENTICATION_AUTO_CONNECT = False
SOCIALACCOUNT_REQUESTS_TIMEOUT = 10
ACCOUNT_LOGIN_METHODS = {"username"}               # allauth's web pages are not used; patients log in with the API
ACCOUNT_SIGNUP_FIELDS = ["username*", "password1*"]
ACCOUNT_EMAIL_VERIFICATION = "none"
NAZRIA_DEFAULT_COUNTRY_CODE = env("NAZRIA_DEFAULT_COUNTRY_CODE") or "92"     # 03001234567 -> +923001234567
MEDIA_ROOT = Path(env("NAZRIA_MEDIA_ROOT") or BASE_DIR / "media")          # pulse videos (never served publicly)
NAZRIA_PULSE_MAX_MB = int(env("NAZRIA_PULSE_MAX_MB") or 100)
FILE_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024                              # larger uploads go to a temp file
# behind nginx on the same machine: take the client IP from X-Forwarded-For (for the audit log)
NAZRIA_TRUST_PROXY = env_flag("NAZRIA_TRUST_PROXY", False)

# ---------------------------------------------------------------- knowledge base
# "postgres" (the nazria schema in the same database) or a dotted path to a KnowledgeBase class (tests)
NAZRIA_KB_BACKEND = env("NAZRIA_KB_BACKEND") or "postgres"
NAZRIA_QUESTIONS_CACHE_S = int(env("NAZRIA_QUESTIONS_CACHE_S") or 60)   # Hakeem edits show up within this time

# ---------------------------------------------------------------- security (production)
# NAZRIA_HTTPS=false while the server is reached over plain HTTP (cookies must then be allowed without HTTPS).
# Plain HTTP sends passwords and health data unencrypted: switch to HTTPS as soon as possible (see deploy/).
NAZRIA_HTTPS = env_flag("NAZRIA_HTTPS", True)
if not DEBUG:
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SESSION_COOKIE_SECURE = NAZRIA_HTTPS
    CSRF_COOKIE_SECURE = NAZRIA_HTTPS
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
