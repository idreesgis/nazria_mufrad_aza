"""Django's own PostgreSQL backend, accepting PostgreSQL 12 and 13 as well (Django 5.2 itself requires 14+).

Used only when NAZRIA_ALLOW_POSTGRES_12=true, for a server whose shared PostgreSQL cannot be upgraded yet. Nothing
else changes: same SQL, same vendor ("postgresql"). The project's migrations and test suite are run against
PostgreSQL 12 (tests/api/test_pg12.py). PostgreSQL 12 and 13 get no security fixes any more (end of life
November 2024 and 2025): upgrade the database when you can, then remove the setting.
"""
from django.db.backends.postgresql import base, features


class DatabaseFeatures(features.DatabaseFeatures):
    minimum_database_version = (12,)


class DatabaseWrapper(base.DatabaseWrapper):
    features_class = DatabaseFeatures
