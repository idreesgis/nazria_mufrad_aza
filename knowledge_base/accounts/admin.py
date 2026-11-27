from django.contrib import admin

from .models import PatientProfile


@admin.register(PatientProfile)
class PatientProfileAdmin(admin.ModelAdmin):
    list_display = ("phone", "full_name", "gender", "birth_year", "consent_at", "created_at")
    search_fields = ("phone", "full_name")
    readonly_fields = ("user", "phone", "consent_at", "consent_version", "created_at")

    def has_delete_permission(self, request, obj=None):
        return False                     # complete history is kept; deactivate the user instead
