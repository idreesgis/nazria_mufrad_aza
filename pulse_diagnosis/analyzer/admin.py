from django.contrib import admin
from .models import PulseAnalysis, SymptomCategory, Symptom


@admin.register(PulseAnalysis)
class PulseAnalysisAdmin(admin.ModelAdmin):
    list_display = ['id', 'patient_name', 'status', 'primary_mizaj', 'created_at']
    list_filter = ['status', 'primary_mizaj', 'created_at']
    search_fields = ['patient_name', 'id']
    readonly_fields = ['id', 'created_at', 'processed_at']


@admin.register(SymptomCategory)
class SymptomCategoryAdmin(admin.ModelAdmin):
    list_display = ['name', 'name_urdu']


@admin.register(Symptom)
class SymptomAdmin(admin.ModelAdmin):
    list_display = ['name', 'category', 'mizaj_association']
    list_filter = ['category', 'mizaj_association']
    search_fields = ['name', 'name_urdu']
