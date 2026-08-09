"""
URL patterns for analyzer app (frontend views).
"""
from django.urls import path
from . import views

urlpatterns = [
    path('', views.HomeView.as_view(), name='home'),
    path('upload/', views.UploadView.as_view(), name='upload'),
    path('results/<uuid:analysis_id>/', views.ResultsView.as_view(), name='results'),
    path('history/', views.HistoryView.as_view(), name='history'),
    path('health/', views.health_check, name='health_check'),
]
