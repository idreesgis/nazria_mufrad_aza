"""python manage.py create_api_schema – creates the PostgreSQL schema for Django's own tables (run before migrate).

Django's tables (API clients, admin users, migrations) are kept in their own schema (NAZRIA_API_DB_SCHEMA, default
"nazria_api") so nothing is created in "public" of a database that other applications share."""
import re

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection


class Command(BaseCommand):
    help = "Create the schema for Django's tables if it does not exist (nothing else is changed)."

    def handle(self, *args, **options):
        schema = settings.NAZRIA_API_DB_SCHEMA
        if not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", schema) or schema in ("public", "nazria"):
            raise CommandError(f"NAZRIA_API_DB_SCHEMA must be a lowercase name other than public/nazria, got {schema!r}")
        if connection.vendor != "postgresql":
            self.stdout.write("not PostgreSQL: nothing to do")
            return
        with connection.cursor() as cur:
            cur.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')
        self.stdout.write(f"schema {schema!r} is ready; now run: python manage.py migrate")
