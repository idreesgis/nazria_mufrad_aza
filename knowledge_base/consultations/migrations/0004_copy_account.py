from django.db import migrations
from django.db.models import F


def forwards(apps, schema_editor):
    apps.get_model("consultations", "Consultation").objects.update(account=F("patient"))


def backwards(apps, schema_editor):
    apps.get_model("consultations", "Consultation").objects.update(patient=F("account"))


class Migration(migrations.Migration):

    dependencies = [("consultations", "0003_account")]

    operations = [migrations.RunPython(forwards, backwards)]
