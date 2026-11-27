from django.urls import path

from . import views

urlpatterns = [
    path("patients/intake-form/", views.IntakeFormView.as_view(), name="patient-intake-form"),
    path("patients/", views.PatientListCreateView.as_view(), name="patients"),
    path("patients/<uuid:pk>/", views.PatientDetailView.as_view(), name="patient-detail"),
    path("patients/<uuid:pk>/history/", views.PatientHistoryView.as_view(), name="patient-history"),
]
