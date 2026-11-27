from django.db import migrations
from django.db.models import F


def forwards(apps, schema_editor):
    apps.get_model("pulse", "PulseAnalysis").objects.update(account=F("patient"))


def backwards(apps, schema_editor):
    apps.get_model("pulse", "PulseAnalysis").objects.update(patient=F("account"))


class Migration(migrations.Migration):

    dependencies = [("pulse", "0002_account")]

    operations = [migrations.RunPython(forwards, backwards)]
