from django.contrib import admin

from .models import PulseAnalysis


@admin.register(PulseAnalysis)
class PulseAnalysisAdmin(admin.ModelAdmin):
    list_display = ("id", "account", "patient", "method", "status", "created_at", "deleted_at")
    list_filter = ("status", "method")
    search_fields = ("account__username", "patient__full_name", "id")
    readonly_fields = [f.name for f in PulseAnalysis._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
