"""The people an account consults for. One account (the logged-in user) can manage many patients: themselves,
children, parents and so on. Every consultation and pulse analysis belongs to one patient.

Nothing is ever deleted: "delete" hides a patient (deleted_at), and every change to a patient's general info is kept
in ``PatientRevision`` (append-only), so each diagnosis can be read with the info that was true at the time
(``Consultation.patient_snapshot``)."""
from __future__ import annotations

import uuid
from datetime import date

from django.conf import settings
from django.db import models
from django.utils import timezone

RELATIONS = [("self", "self"), ("spouse", "spouse"), ("child", "child"), ("parent", "parent"),
             ("sibling", "sibling"), ("relative", "relative"), ("other", "other")]
GENDERS = [("male", "male"), ("female", "female"), ("other", "other")]
CONDITIONS = ["diabetes", "hypertension", "heart", "kidney", "liver", "asthma", "thyroid", "epilepsy", "other"]

CHILD_UNDER = 12        # the questionnaire's age groups: under 12 child, 12–60 adult, over 60 elderly
ELDERLY_OVER = 60


class Patient(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    account = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="patients")
    full_name = models.CharField(max_length=150)
    relation = models.CharField(max_length=10, choices=RELATIONS, default="other")
    gender = models.CharField(max_length=10, choices=GENDERS, blank=True)
    birth_year = models.PositiveSmallIntegerField(null=True, blank=True)
    weight_kg = models.DecimalField(max_digits=5, decimal_places=1, null=True, blank=True)
    height_cm = models.DecimalField(max_digits=5, decimal_places=1, null=True, blank=True)
    chronic_conditions = models.JSONField(default=list, blank=True, help_text=f"keys: {', '.join(CONDITIONS)}")
    conditions_other = models.CharField(max_length=300, blank=True)
    allergies = models.CharField(max_length=300, blank=True)
    medications = models.CharField(max_length=500, blank=True)
    notes = models.TextField(blank=True, max_length=2000)
    consent_at = models.DateTimeField(null=True, blank=True,
                                      help_text="the account holder confirmed they may record this patient's data")
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    updated_at = models.DateTimeField(default=timezone.now)
    deleted_at = models.DateTimeField(null=True, blank=True, help_text="hidden from the account; kept for history")

    class Meta:
        ordering = ["full_name", "created_at"]
        indexes = [models.Index(fields=["account", "deleted_at"], name="patient_account_idx")]

    def __str__(self) -> str:
        return f"{self.full_name} ({self.relation})"

    # ------------------------------------------------------------ derived
    @property
    def age(self) -> int | None:
        return date.today().year - self.birth_year if self.birth_year else None

    @property
    def age_group(self) -> str | None:
        """child | adult | elderly, as the questionnaire's age_group answer (None when the birth year is unknown)."""
        age = self.age
        if age is None:
            return None
        return "child" if age < CHILD_UNDER else "elderly" if age > ELDERLY_OVER else "adult"

    @property
    def bmi(self) -> float | None:
        if not (self.weight_kg and self.height_cm):
            return None
        m = float(self.height_cm) / 100
        return round(float(self.weight_kg) / (m * m), 1)

    def health(self) -> dict:
        """What the safety filters use: known conditions, and whether medicines/allergies call for caution."""
        return {"conditions": [c for c in self.chronic_conditions if c in CONDITIONS],
                "caution": bool(self.medications.strip() or self.allergies.strip())}

    def snapshot(self) -> dict:
        """The general info as it is now (stored with each consultation and each revision)."""
        return {"id": str(self.id), "full_name": self.full_name, "relation": self.relation, "gender": self.gender,
                "birth_year": self.birth_year, "age": self.age, "age_group": self.age_group,
                "weight_kg": float(self.weight_kg) if self.weight_kg is not None else None,
                "height_cm": float(self.height_cm) if self.height_cm is not None else None, "bmi": self.bmi,
                "chronic_conditions": list(self.chronic_conditions), "conditions_other": self.conditions_other,
                "allergies": self.allergies, "medications": self.medications}


class PatientRevision(models.Model):
    """One row per creation or change of a patient's general info (append-only, never edited)."""
    id = models.BigAutoField(primary_key=True)
    patient = models.ForeignKey(Patient, on_delete=models.PROTECT, related_name="revisions")
    changed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT, related_name="+")
    changed_at = models.DateTimeField(default=timezone.now, editable=False)
    action = models.CharField(max_length=20)                      # created | updated | deleted | migrated
    fields = models.JSONField(default=list)                       # names of the changed fields
    data = models.JSONField(default=dict)                         # the full snapshot after the change

    class Meta:
        ordering = ["-changed_at", "-id"]

    def save(self, *args, **kwargs):
        if self.pk is not None and PatientRevision.objects.filter(pk=self.pk).exists():
            raise PermissionError("patient revisions are append-only")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PermissionError("patient revisions are append-only")


def record_revision(patient: Patient, user, action: str, fields: list[str] | None = None) -> PatientRevision:
    return PatientRevision.objects.create(patient=patient, changed_by=user, action=action,
                                          fields=sorted(fields or []), data=patient.snapshot())
