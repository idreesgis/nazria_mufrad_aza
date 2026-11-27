"""python manage.py seed_questionnaire – add new questions and options of the built-in question bank to
nazria.questionnaire_questions / questionnaire_options.

Insert-only: rows that already exist (and any Hakeem edit to them, or a question a Hakeem switched off) are never
changed. Run after an update that adds questions; deploy/update.sh runs it."""
from django.core.management.base import BaseCommand
from django.db import connection


class Command(BaseCommand):
    help = "Insert missing questionnaire questions/options into the nazria schema (never overwrites edits)."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="only list what would be added")

    def handle(self, *args, dry_run=False, **options):
        from nazria_kb.db import seed_questionnaire
        from nazria_kb.questionnaire import DEFAULT_QUESTIONS
        if connection.vendor != "postgresql":
            self.stdout.write("not PostgreSQL: the built-in questions are used as they are")
            return
        connection.ensure_connection()
        raw = connection.connection
        have_q = {r[0] for r in raw.execute("SELECT question_id FROM nazria.questionnaire_questions")}
        have_o = {(a, b) for a, b in raw.execute("SELECT question_id, option_key FROM nazria.questionnaire_options")}
        new_q = [q.id for q in DEFAULT_QUESTIONS if q.id not in have_q]
        new_o = [(q.id, o.key) for q in DEFAULT_QUESTIONS for o in q.options if (q.id, o.key) not in have_o]
        if dry_run:
            self.stdout.write(f"would add {len(new_q)} questions {new_q} and {len(new_o)} options")
            return
        with raw.transaction(), raw.cursor() as cur:
            seed_questionnaire(cur)
        self.stdout.write(f"added {len(new_q)} questions {new_q} and {len(new_o)} options "
                          "(existing rows unchanged)")
