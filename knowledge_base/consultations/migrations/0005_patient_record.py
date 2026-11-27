"""Step 3/3: "patient" now points to patients.Patient (filled by patients.0002 for existing history)."""
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("consultations", "0004_copy_account"),
        ("patients", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.RemoveIndex(model_name="consultation", name="consultatio_patient_ddabc3_idx"),
        migrations.RemoveField(model_name="consultation", name="patient"),
        migrations.AlterField(
            model_name="consultation",
            name="account",
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.PROTECT,
                                    related_name="consultations", to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name="consultation",
            name="patient",
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.PROTECT,
                                    related_name="consultations", to="patients.patient"),
        ),
        migrations.AddField(
            model_name="consultation",
            name="patient_snapshot",
            field=models.JSONField(blank=True, default=dict,
                                   help_text="the patient's general info when this diagnosis was made"),
        ),
        migrations.AddField(
            model_name="consultation",
            name="rediagnosis_of",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                                    related_name="rediagnoses", to="consultations.consultation"),
        ),
        migrations.AddIndex(model_name="consultation",
                            index=models.Index(fields=["account", "created_at"], name="consultatio_account_idx")),
        migrations.AddIndex(model_name="consultation",
                            index=models.Index(fields=["patient", "created_at"], name="consultation_patient_idx")),
    ]
