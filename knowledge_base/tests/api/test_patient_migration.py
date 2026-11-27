"""patients.0002 moves existing history (consultations and pulse analyses owned by an account) to a "self" patient."""
import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone

BEFORE = [("accounts", "0003_social_login"), ("consultations", "0002_patient_owned_history"),
          ("pulse", "0001_initial")]


@pytest.mark.django_db(transaction=True)
def test_existing_history_is_moved_to_a_self_patient():
    ex = MigrationExecutor(connection)
    latest = ex.loader.graph.leaf_nodes()
    ex.migrate(BEFORE)
    old = MigrationExecutor(connection).loader.project_state(BEFORE).apps
    User = old.get_model("auth", "User")
    u = User.objects.create(username="+923001234567")
    empty = User.objects.create(username="+923000000000")              # no history: gets no patient
    old.get_model("accounts", "PatientProfile").objects.create(user=u, phone="+923001234567", full_name="Ali",
                                                               gender="male", birth_year=1980,
                                                               consent_at=timezone.now())
    C = old.get_model("consultations", "Consultation")
    c1 = C.objects.create(patient=u, status="completed", primary_system="عضلاتی")
    C.objects.create(patient=u, status="emergency")
    old.get_model("pulse", "PulseAnalysis").objects.create(patient=u, video="pulse/x.mp4", status="failed")

    ex = MigrationExecutor(connection)
    ex.loader.build_graph()
    ex.migrate(latest)

    from consultations.models import Consultation
    from patients.models import Patient
    from pulse.models import PulseAnalysis
    p = Patient.objects.get(account_id=u.pk)
    assert (p.relation, p.full_name, p.gender, p.birth_year) == ("self", "Ali", "male", 1980)
    assert not Patient.objects.filter(account_id=empty.pk).exists()
    assert set(Consultation.objects.values_list("patient_id", flat=True)) == {p.id}
    assert Consultation.objects.get(pk=c1.pk).account_id == u.pk
    assert Consultation.objects.get(pk=c1.pk).patient_snapshot["full_name"] == "Ali"
    assert PulseAnalysis.objects.get().patient_id == p.id and PulseAnalysis.objects.get().account_id == u.pk
    assert p.revisions.get().action == "migrated"
