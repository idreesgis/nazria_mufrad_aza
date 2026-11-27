"""Every account that already has consultations or pulse analyses gets one patient, "self", made from its profile,
and that history is assigned to it. Nothing is deleted."""
from django.db import migrations
from django.utils import timezone


def forwards(apps, schema_editor):
    Patient = apps.get_model("patients", "Patient")
    PatientRevision = apps.get_model("patients", "PatientRevision")
    Consultation = apps.get_model("consultations", "Consultation")
    PulseAnalysis = apps.get_model("pulse", "PulseAnalysis")
    PatientProfile = apps.get_model("accounts", "PatientProfile")
    account_ids = set(Consultation.objects.filter(patient__isnull=True, account__isnull=False)
                      .values_list("account_id", flat=True))
    account_ids |= set(PulseAnalysis.objects.filter(patient__isnull=True).values_list("account_id", flat=True))
    for uid in sorted(account_ids):
        prof = PatientProfile.objects.filter(user_id=uid).first()
        now = timezone.now()
        p = Patient.objects.create(account_id=uid, relation="self",
                                   full_name=(prof.full_name if prof and prof.full_name else "میں خود"),
                                   gender=prof.gender if prof else "", birth_year=prof.birth_year if prof else None,
                                   consent_at=prof.consent_at if prof else None, created_at=now, updated_at=now)
        snap = {"id": str(p.id), "full_name": p.full_name, "relation": "self", "gender": p.gender,
                "birth_year": p.birth_year}
        PatientRevision.objects.create(patient=p, changed_by=None, changed_at=now, action="migrated",
                                       fields=[], data=snap)
        Consultation.objects.filter(account_id=uid, patient__isnull=True).update(patient=p, patient_snapshot=snap)
        PulseAnalysis.objects.filter(account_id=uid, patient__isnull=True).update(patient=p)


class Migration(migrations.Migration):

    dependencies = [
        ("patients", "0001_initial"),
        ("accounts", "0003_social_login"),
        ("consultations", "0005_patient_record"),
        ("pulse", "0004_patient_record"),
    ]

    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
