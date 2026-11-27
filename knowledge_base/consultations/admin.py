"""Staff admin: API clients (create keys, revoke) and the consultation access log (no patient text)."""
from django.contrib import admin, messages

from .models import ApiClient, Consultation


@admin.register(ApiClient)
class ApiClientAdmin(admin.ModelAdmin):
    list_display = ("name", "key_prefix", "is_active", "created_at", "last_used_at")
    list_filter = ("is_active",)
    readonly_fields = ("key_prefix", "created_at", "last_used_at")
    fields = ("name", "is_active", "notes", "key_prefix", "created_at", "last_used_at")

    def save_model(self, request, obj, form, change):
        if change:
            return super().save_model(request, obj, form, change)
        client, key = ApiClient.create(obj.name, obj.notes)
        obj.pk, obj.key_prefix = client.pk, client.key_prefix
        self.message_user(request, f"API key for {client.name} (shown only once, copy it now): {key}",
                          level=messages.WARNING)


@admin.register(Consultation)
class ConsultationAdmin(admin.ModelAdmin):
    list_display = ("session_uid", "account", "patient", "status", "primary_system", "explanation_status", "created_at",
                    "deleted_at")
    list_filter = ("status", "explanation_status", "client")
    search_fields = ("session_uid", "account__username", "patient__full_name")
    readonly_fields = [f.name for f in Consultation._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False                     # complete history is kept
