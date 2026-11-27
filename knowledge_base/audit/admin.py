from django.contrib import admin

from .models import AuditEvent


@admin.register(AuditEvent)
class AuditEventAdmin(admin.ModelAdmin):
    list_display = ("at", "action", "actor", "actor_type", "object_type", "object_id", "status_code", "ip")
    list_filter = ("action", "actor_type", "status_code")
    search_fields = ("object_id", "actor__username", "ip", "request_id")
    date_hierarchy = "at"
    readonly_fields = [f.name for f in AuditEvent._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
