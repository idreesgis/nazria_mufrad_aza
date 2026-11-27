from django.urls import path

from . import views

urlpatterns = [
    path("health/", views.HealthView.as_view(), name="health"),
    path("questionnaire/", views.QuestionnaireView.as_view(), name="questionnaire"),
    path("triage/", views.TriageView.as_view(), name="triage"),
    path("consultations/", views.ConsultationCreateView.as_view(), name="consultation-create"),
    path("consultations/<uuid:pk>/", views.ConsultationDetailView.as_view(), name="consultation-detail"),
    path("consultations/<uuid:pk>/explanation/", views.ExplanationView.as_view(), name="consultation-explanation"),
]
