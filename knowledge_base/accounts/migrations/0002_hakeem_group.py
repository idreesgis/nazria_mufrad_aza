from django.db import migrations


def forwards(apps, schema_editor):
    apps.get_model("auth", "Group").objects.get_or_create(name="hakeem")


class Migration(migrations.Migration):
    dependencies = [("accounts", "0001_initial"), ("auth", "0012_alter_user_first_name_max_length")]
    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
