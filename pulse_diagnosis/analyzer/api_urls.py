"""
API URL patterns for analyzer app.
"""
from django.urls import path
from . import api_views

urlpatterns = [
    path('analyze/', api_views.AnalyzePulseAPI.as_view(), name='api_analyze'),
    path('analysis/<uuid:analysis_id>/', api_views.GetAnalysisAPI.as_view(), name='api_get_analysis'),
    path('analyses/', api_views.ListAnalysesAPI.as_view(), name='api_list_analyses'),
    path('symptoms/', api_views.SymptomSuggestionsAPI.as_view(), name='api_symptoms'),
]
