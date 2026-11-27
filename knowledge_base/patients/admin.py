from django.contrib import admin

from .models import Patient, PatientRevision


class RevisionInline(admin.TabularInline):
    model = PatientRevision
    extra = 0
    fields = ("changed_at", "changed_by", "action", "fields")
    readonly_fields = fields
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Patient)
class PatientAdmin(admin.ModelAdmin):
    list_display = ("full_name", "relation", "gender", "birth_year", "account", "created_at", "deleted_at")
    list_filter = ("relation", "gender")
    search_fields = ("full_name", "account__username", "account__email")
    readonly_fields = ("id", "account", "consent_at", "created_at", "updated_at", "deleted_at")
    inlines = [RevisionInline]

    def has_add_permission(self, request):
        return False                     # added from the app (with the account holder's consent)

    def has_delete_permission(self, request, obj=None):
        return False                     # complete history is kept

    def save_model(self, request, obj, form, change):
        from django.utils import timezone

        from .models import record_revision
        obj.updated_at = timezone.now()
        super().save_model(request, obj, form, change)
        record_revision(obj, request.user, "updated", list(form.changed_data))
