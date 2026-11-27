import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("pulse", "0003_copy_account"),
        ("patients", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.RemoveField(model_name="pulseanalysis", name="patient"),
        migrations.AlterField(
            model_name="pulseanalysis",
            name="account",
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="pulse_analyses",
                                    to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name="pulseanalysis",
            name="patient",
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.PROTECT,
                                    related_name="pulse_analyses", to="patients.patient"),
        ),
    ]
