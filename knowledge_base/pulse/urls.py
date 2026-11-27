from django.urls import path

from . import views

urlpatterns = [
    path("pulse/analyses/", views.PulseListCreateView.as_view(), name="pulse-list"),
    path("pulse/analyses/<uuid:pk>/", views.PulseDetailView.as_view(), name="pulse-detail"),
    path("pulse/symptom-suggestions/", views.SymptomSuggestionsView.as_view(), name="pulse-symptoms"),
]
