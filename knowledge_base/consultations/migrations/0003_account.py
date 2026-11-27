"""Step 1/3 of "consultations belong to a patient of an account": add the account column (a copy of the former
"patient" column, which held the user). Split in three migrations so each runs in its own transaction."""
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("consultations", "0002_patient_owned_history"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="consultation",
            name="account",
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.PROTECT, related_name="+",
                                    to=settings.AUTH_USER_MODEL),
        ),
    ]
