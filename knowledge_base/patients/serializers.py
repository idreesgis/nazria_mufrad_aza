from django.db.models import Count
from rest_framework import serializers

from .models import CONDITIONS, RELATIONS, Patient


class PatientIn(serializers.ModelSerializer):
    """General info of a patient (create: full_name, relation, gender, birth_year and consent are required)."""
    consent = serializers.BooleanField(write_only=True, required=False,
                                       help_text="Required (true) when the patient is created")
    chronic_conditions = serializers.ListField(child=serializers.ChoiceField(choices=CONDITIONS + ["none"]),
                                               required=False, max_length=len(CONDITIONS) + 1)
    weight_kg = serializers.DecimalField(max_digits=5, decimal_places=1, min_value=1, max_value=400, required=False,
                                         allow_null=True)
    height_cm = serializers.DecimalField(max_digits=5, decimal_places=1, min_value=30, max_value=250, required=False,
                                         allow_null=True)
    birth_year = serializers.IntegerField(min_value=1900, max_value=2100)

    class Meta:
        model = Patient
        fields = ["full_name", "relation", "gender", "birth_year", "weight_kg", "height_cm", "chronic_conditions",
                  "conditions_other", "allergies", "medications", "notes", "consent"]
        extra_kwargs = {"gender": {"allow_blank": False}, "notes": {"required": False}}

    def get_fields(self):
        fields = super().get_fields()
        creating = self.instance is None
        for name in ("full_name", "relation", "gender", "birth_year"):
            fields[name].required = creating
        return fields

    def validate_birth_year(self, v):
        from datetime import date
        if v > date.today().year:
            raise serializers.ValidationError("the birth year is in the future")
        return v

    def validate_chronic_conditions(self, v):
        v = list(dict.fromkeys(v))
        return [] if v == ["none"] else [c for c in v if c != "none"]

    def validate(self, data):
        if self.instance is None and data.get("consent") is not True:
            raise serializers.ValidationError({"consent": "confirm that you may record this patient's data"})
        return data


class PatientOut(serializers.Serializer):
    id = serializers.UUIDField()
    full_name = serializers.CharField()
    relation = serializers.ChoiceField(choices=[r for r, _ in RELATIONS])
    gender = serializers.CharField(allow_blank=True)
    birth_year = serializers.IntegerField(allow_null=True)
    age = serializers.IntegerField(allow_null=True)
    age_group = serializers.CharField(allow_null=True, help_text="child | adult | elderly (from birth_year)")
    weight_kg = serializers.FloatField(allow_null=True)
    height_cm = serializers.FloatField(allow_null=True)
    bmi = serializers.FloatField(allow_null=True)
    chronic_conditions = serializers.ListField(child=serializers.CharField())
    conditions_other = serializers.CharField(allow_blank=True)
    allergies = serializers.CharField(allow_blank=True)
    medications = serializers.CharField(allow_blank=True)
    notes = serializers.CharField(allow_blank=True)
    prefilled_questions = serializers.ListField(
        child=serializers.CharField(), help_text="Questionnaire questions the server answers from this info: skip them")
    consultations = serializers.IntegerField(help_text="Number of diagnoses")
    pulse_analyses = serializers.IntegerField()
    last_consultation_at = serializers.DateTimeField(allow_null=True)
    created_at = serializers.DateTimeField()
    updated_at = serializers.DateTimeField()
    deleted = serializers.BooleanField()


class PatientSnapshotOut(serializers.Serializer):
    """The patient's general info at the time of a consultation."""
    id = serializers.UUIDField()
    full_name = serializers.CharField()
    relation = serializers.CharField()
    gender = serializers.CharField(allow_blank=True)
    birth_year = serializers.IntegerField(allow_null=True)
    age = serializers.IntegerField(allow_null=True)
    age_group = serializers.CharField(allow_null=True)
    weight_kg = serializers.FloatField(allow_null=True)
    height_cm = serializers.FloatField(allow_null=True)
    bmi = serializers.FloatField(allow_null=True)
    chronic_conditions = serializers.ListField(child=serializers.CharField())
    conditions_other = serializers.CharField(allow_blank=True)
    allergies = serializers.CharField(allow_blank=True)
    medications = serializers.CharField(allow_blank=True)


class RevisionOut(serializers.Serializer):
    id = serializers.IntegerField()
    changed_at = serializers.DateTimeField()
    changed_by = serializers.IntegerField(source="changed_by_id", allow_null=True)
    action = serializers.CharField()
    fields = serializers.ListField(child=serializers.CharField())
    data = PatientSnapshotOut()


class IntakeFieldOut(serializers.Serializer):
    id = serializers.CharField()
    kind = serializers.ChoiceField(choices=["text", "single", "multi", "integer", "number", "boolean"])
    required = serializers.BooleanField()
    label = serializers.CharField()
    options = serializers.ListField(child=serializers.DictField(child=serializers.CharField()), required=False)
    min = serializers.FloatField(required=False)
    max = serializers.FloatField(required=False)
    max_length = serializers.IntegerField(required=False)
    help = serializers.CharField(required=False)


class IntakeFormOut(serializers.Serializer):
    version = serializers.CharField()
    language = serializers.ChoiceField(choices=["ur", "en", "ar"])
    direction = serializers.ChoiceField(choices=["rtl", "ltr"])
    fields = IntakeFieldOut(many=True)
    prefills = serializers.DictField(child=serializers.CharField())


def with_counts(qs):
    from django.db.models import Max
    return qs.annotate(n_consultations=Count("consultations", distinct=True),
                       n_pulse=Count("pulse_analyses", distinct=True),
                       last_at=Max("consultations__created_at"))


def patient_out(p: Patient) -> dict:
    from .intake import prefilled_question_ids
    snap = p.snapshot()
    n_c = getattr(p, "n_consultations", None)
    n_p = getattr(p, "n_pulse", None)
    last = getattr(p, "last_at", None)
    if n_c is None:
        n_c = p.consultations.count()
        n_p = p.pulse_analyses.count()
        last = p.consultations.order_by("-created_at").values_list("created_at", flat=True).first()
    return {**snap, "notes": p.notes, "prefilled_questions": prefilled_question_ids(p), "consultations": n_c,
            "pulse_analyses": n_p, "last_consultation_at": last, "created_at": p.created_at,
            "updated_at": p.updated_at, "deleted": p.deleted_at is not None}
