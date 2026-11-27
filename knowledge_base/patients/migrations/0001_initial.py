import uuid

import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="Patient",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("full_name", models.CharField(max_length=150)),
                ("relation", models.CharField(choices=[("self", "self"), ("spouse", "spouse"), ("child", "child"),
                                                       ("parent", "parent"), ("sibling", "sibling"),
                                                       ("relative", "relative"), ("other", "other")],
                                              default="other", max_length=10)),
                ("gender", models.CharField(blank=True, choices=[("male", "male"), ("female", "female"),
                                                                 ("other", "other")], max_length=10)),
                ("birth_year", models.PositiveSmallIntegerField(blank=True, null=True)),
                ("weight_kg", models.DecimalField(blank=True, decimal_places=1, max_digits=5, null=True)),
                ("height_cm", models.DecimalField(blank=True, decimal_places=1, max_digits=5, null=True)),
                ("chronic_conditions", models.JSONField(blank=True, default=list, help_text="keys: diabetes, hypertension, heart, kidney, liver, asthma, thyroid, epilepsy, other")),
                ("conditions_other", models.CharField(blank=True, max_length=300)),
                ("allergies", models.CharField(blank=True, max_length=300)),
                ("medications", models.CharField(blank=True, max_length=500)),
                ("notes", models.TextField(blank=True, max_length=2000)),
                ("consent_at", models.DateTimeField(blank=True, null=True, help_text="the account holder confirmed they may record this patient's data")),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now, editable=False)),
                ("updated_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("deleted_at", models.DateTimeField(blank=True, null=True, help_text="hidden from the account; kept for history")),
                ("account", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="patients",
                                              to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "ordering": ["full_name", "created_at"],
                "indexes": [models.Index(fields=["account", "deleted_at"], name="patient_account_idx")],
            },
        ),
        migrations.CreateModel(
            name="PatientRevision",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False)),
                ("changed_at", models.DateTimeField(default=django.utils.timezone.now, editable=False)),
                ("action", models.CharField(max_length=20)),
                ("fields", models.JSONField(default=list)),
                ("data", models.JSONField(default=dict)),
                ("changed_by", models.ForeignKey(null=True, on_delete=django.db.models.deletion.PROTECT,
                                                 related_name="+", to=settings.AUTH_USER_MODEL)),
                ("patient", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="revisions",
                                              to="patients.patient")),
            ],
            options={"ordering": ["-changed_at", "-id"]},
        ),
    ]
