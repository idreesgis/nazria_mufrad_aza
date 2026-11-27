"""On PostgreSQL the audit table refuses UPDATE, DELETE and TRUNCATE, whoever connects (not only through Django)."""
from django.db import migrations

SQL = """
CREATE OR REPLACE FUNCTION audit_auditevent_append_only() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'the audit log is append-only (% is not allowed)', TG_OP;
END $$;
DROP TRIGGER IF EXISTS audit_auditevent_no_change ON audit_auditevent;
CREATE TRIGGER audit_auditevent_no_change BEFORE UPDATE OR DELETE ON audit_auditevent
    FOR EACH ROW EXECUTE FUNCTION audit_auditevent_append_only();
DROP TRIGGER IF EXISTS audit_auditevent_no_truncate ON audit_auditevent;
CREATE TRIGGER audit_auditevent_no_truncate BEFORE TRUNCATE ON audit_auditevent
    FOR EACH STATEMENT EXECUTE FUNCTION audit_auditevent_append_only();
"""


def forwards(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(SQL, params=None)     # no parameter substitution: the SQL contains a literal %


class Migration(migrations.Migration):
    dependencies = [("audit", "0001_initial")]
    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
