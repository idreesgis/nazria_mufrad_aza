"""Request validation and the response shapes (also the OpenAPI contract the Android app is generated from)."""
from rest_framework import serializers


# ---------------------------------------------------------------- requests
class TriageRequest(serializers.Serializer):
    red_flags = serializers.ListField(child=serializers.CharField(max_length=40), allow_empty=False, max_length=20,
                                      help_text='Option keys of the "red_flags" question, e.g. ["none"]')
    complaint = serializers.CharField(required=False, allow_blank=True, max_length=1000,
                                      help_text="Free-text complaint, if already entered (also screened)")


class ConsultationRequest(serializers.Serializer):
    answers = serializers.DictField(
        help_text='{question_id: answer}. Single choice: option key; multiple choice: list of keys; text: string. '
                  'Example: {"red_flags": ["none"], "complaint": "پرانی قبض", "duration": "chronic", ...}. '
                  'The questions in the patient\'s prefilled_questions may be left out: the server fills them.')
    patient_id = serializers.UUIDField(required=False, allow_null=True,
                                       help_text="An existing patient of this account (re-diagnosis)")
    new_patient = serializers.DictField(required=False, allow_null=True,
                                        help_text="A new patient's general info (GET /patients/intake-form/), "
                                                  "created together with this diagnosis")

    def validate(self, data):
        if data.get("patient_id") and data.get("new_patient"):
            raise serializers.ValidationError({"patient_id": "send patient_id or new_patient, not both"})
        return data


class RediagnoseRequest(serializers.Serializer):
    answers = serializers.DictField(required=False, default=dict,
                                    help_text="Only the answers that changed since the earlier diagnosis "
                                              "(e.g. {\"urine_color\": \"yellow\"}); all others are reused")
    patient_id = serializers.UUIDField(required=False, allow_null=True,
                                       help_text="Needed only when the earlier diagnosis has no patient")


# ---------------------------------------------------------------- responses
class OptionOut(serializers.Serializer):
    key = serializers.CharField()
    label = serializers.CharField()


class SkipIfOut(serializers.Serializer):
    question_id = serializers.CharField()
    equals = serializers.CharField()


class QuestionOut(serializers.Serializer):
    id = serializers.CharField()
    kind = serializers.ChoiceField(choices=["single", "multi", "text"])
    stage = serializers.ChoiceField(choices=["triage", "profile", "signs"])
    text = serializers.CharField()
    options = OptionOut(many=True)
    skip_if = SkipIfOut(allow_null=True, help_text="Do not ask this question when the given answer was chosen")
    emergency_unless = serializers.ListField(child=serializers.CharField(), allow_null=True,
                                             help_text="Any other selected option is an emergency: call /triage/")
    min_length = serializers.IntegerField(allow_null=True)
    max_length = serializers.IntegerField(allow_null=True)


class QuestionnaireOut(serializers.Serializer):
    version = serializers.CharField(help_text="Changes whenever a Hakeem edits the questions; cache by it")
    disclaimer = serializers.CharField()
    questions = QuestionOut(many=True)


class TriageOut(serializers.Serializer):
    emergency = serializers.BooleanField()
    flags = serializers.ListField(child=serializers.CharField())
    flag_labels = serializers.ListField(child=serializers.CharField())
    message = serializers.CharField(allow_null=True, help_text="Show this and stop when emergency is true")


class CitationOut(serializers.Serializer):
    volume = serializers.IntegerField()
    volume_name = serializers.CharField()
    pages = serializers.ListField(child=serializers.IntegerField())
    text = serializers.CharField(help_text='Ready-made Urdu reference, e.g. "جلد دوم، صفحہ 127"')


class EmergencyOut(serializers.Serializer):
    flags = serializers.ListField(child=serializers.CharField())
    flag_labels = serializers.ListField(child=serializers.CharField())
    message = serializers.CharField()


class EvidenceOut(serializers.Serializer):
    question_id = serializers.CharField()
    option_key = serializers.CharField()
    question = serializers.CharField()
    answer = serializers.CharField()
    system = serializers.CharField()
    citation = CitationOut()


class AssessmentOut(serializers.Serializer):
    conclusive = serializers.BooleanField(help_text="False: no clear tehreek, the patient needs a pulse examination")
    primary_system = serializers.CharField(allow_null=True, help_text="اعصابی | عضلاتی | غدی")
    primary_organs = serializers.CharField(allow_null=True)
    secondary_system = serializers.CharField(allow_null=True)
    tehreek = serializers.CharField(allow_null=True)
    mizaj = serializers.CharField(allow_null=True)
    confidence = serializers.FloatField()
    totals = serializers.DictField(child=serializers.IntegerField())
    evidence = EvidenceOut(many=True)
    vulnerable = serializers.BooleanField(help_text="Child, elderly or pregnant: no recipe is ever returned")


class HazardOut(serializers.Serializer):
    code = serializers.CharField()
    name = serializers.CharField()


class RecipeOut(serializers.Serializer):
    status = serializers.ChoiceField(choices=["shown", "withheld_vulnerable", "withheld_condition", "withheld_hazard"])
    text = serializers.CharField(allow_null=True)
    dosage = serializers.CharField(allow_null=True)
    hazards = HazardOut(many=True)
    message = serializers.CharField(allow_null=True, help_text="Why the recipe is not shown")


class TopicOut(serializers.Serializer):
    id = serializers.IntegerField()
    title = serializers.CharField()
    citation = CitationOut()


class PassageOut(serializers.Serializer):
    context = serializers.CharField()
    excerpt = serializers.CharField()
    citation = CitationOut()


class BookOut(serializers.Serializer):
    topic = TopicOut(allow_null=True)
    description = serializers.CharField(allow_null=True)
    recipe = RecipeOut(allow_null=True)
    diet = serializers.CharField(allow_null=True)
    passages = PassageOut(many=True, help_text="Only when no chapter matched the complaint")


class SourceOut(serializers.Serializer):
    context = serializers.CharField()
    citation = CitationOut()


class ExplanationOut(serializers.Serializer):
    status = serializers.ChoiceField(choices=["shown", "not_covered", "rejected", "unavailable", "disabled"])
    text = serializers.CharField(required=False, help_text="Only when status is shown")
    sources = SourceOut(many=True, required=False)
    reason = serializers.CharField(required=False)
    retryable = serializers.BooleanField(required=False)
    provider = serializers.CharField(required=False)
    model = serializers.CharField(required=False)
    external_provider = serializers.BooleanField(required=False)
    notice = serializers.CharField(required=False, allow_null=True,
                                   help_text="Show to the patient when an external AI service was used")


class PulseSummaryOut(serializers.Serializer):
    id = serializers.UUIDField()
    status = serializers.CharField()
    method = serializers.CharField()
    created_at = serializers.DateTimeField()
    average_heart_rate_bpm = serializers.FloatField(allow_null=True)


class PatientRefOut(serializers.Serializer):
    id = serializers.UUIDField()
    full_name = serializers.CharField()
    relation = serializers.CharField()


class ConsultationSummaryOut(serializers.Serializer):
    id = serializers.UUIDField()
    status = serializers.ChoiceField(choices=["completed", "emergency"])
    created_at = serializers.DateTimeField()
    patient = PatientRefOut(allow_null=True)
    rediagnosis_of = serializers.UUIDField(allow_null=True)
    primary_system = serializers.CharField(allow_null=True)
    explanation_status = serializers.CharField(allow_null=True)
    complaint = serializers.CharField()
    deleted = serializers.BooleanField(help_text="Hidden by the patient (only staff see these)")


class ConsultationOut(serializers.Serializer):
    id = serializers.UUIDField()
    account = serializers.IntegerField(help_text="User id of the account the patient belongs to")
    patient = serializers.DictField(allow_null=True, help_text="The patient's general info AT THE TIME of this "
                                    "diagnosis (see PatientSnapshotOut); null only for an emergency without patient")
    rediagnosis_of = serializers.UUIDField(allow_null=True, help_text="The earlier diagnosis this one re-ran")
    prefilled_answers = serializers.DictField(child=serializers.CharField(),
                                              help_text="Answers the server took from the patient's info")
    status = serializers.ChoiceField(choices=["completed", "emergency"])
    created_at = serializers.DateTimeField()
    emergency = EmergencyOut(allow_null=True)
    assessment = AssessmentOut(allow_null=True)
    book = BookOut(allow_null=True)
    advice = serializers.ListField(child=serializers.CharField())
    disclaimer = serializers.CharField()
    text = serializers.CharField(help_text="The whole result as Urdu text (same as the CLI), for simple display")
    explanation = ExplanationOut(allow_null=True)
    explanation_available = serializers.BooleanField(help_text="True when the server can explain this result with AI")
    pulse_analyses = PulseSummaryOut(many=True)
    deleted = serializers.BooleanField()


class HealthOut(serializers.Serializer):
    status = serializers.CharField()
    database = serializers.CharField()
    explanation_enabled = serializers.BooleanField()
    google_login_enabled = serializers.BooleanField(help_text="Show the \"Sign in with Google\" button")
    api_version = serializers.IntegerField()


class ErrorOut(serializers.Serializer):
    error = serializers.CharField()
    detail = serializers.CharField()
    fields = serializers.DictField(child=serializers.CharField(), required=False)
