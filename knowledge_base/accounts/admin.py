from django.contrib import admin

from .models import PatientProfile, SocialAccount


@admin.register(PatientProfile)
class PatientProfileAdmin(admin.ModelAdmin):
    list_display = ("phone", "full_name", "gender", "birth_year", "consent_at", "created_at")
    search_fields = ("phone", "full_name")
    readonly_fields = ("user", "phone", "consent_at", "consent_version", "created_at")

    def has_delete_permission(self, request, obj=None):
        return False                     # complete history is kept; deactivate the user instead


@admin.register(SocialAccount)
class LegacyGoogleLinkAdmin(admin.ModelAdmin):
    """The Google links from before django-allauth (copied to "Social accounts"); kept as a record, read-only."""
    list_display = ("provider", "email", "user", "created_at", "last_login_at")
    list_filter = ("provider",)
    search_fields = ("email", "user__username")
    readonly_fields = ("user", "provider", "uid", "email", "email_verified", "name", "created_at", "last_login_at")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
