"""URL routes: /api/v1/... for the Android app, /api/docs/ (OpenAPI), /admin/ (staff)."""
from django.conf import settings
from django.contrib import admin
from django.urls import include, path

from accounts.staff_views import AccountHistoryView, AccountListView, StaffPatientHistoryView, StaffPatientListView
from audit.views import MyActivityView, StaffAuditView

api_v1 = [
    path("", include("consultations.urls")),
    path("", include("accounts.urls")),
    path("", include("pulse.urls")),
    path("", include("patients.urls")),
    path("me/activity/", MyActivityView.as_view(), name="me-activity"),
    path("staff/accounts/", AccountListView.as_view(), name="staff-accounts"),
    path("staff/accounts/<int:pk>/", AccountHistoryView.as_view(), name="staff-account"),
    path("staff/patients/", StaffPatientListView.as_view(), name="staff-patients"),
    path("staff/patients/<uuid:pk>/", StaffPatientHistoryView.as_view(), name="staff-patient"),
    path("staff/audit/", StaffAuditView.as_view(), name="staff-audit"),
]
urlpatterns = [path("api/v1/", include(api_v1))]

if settings.NAZRIA_API_DOCS:
    from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView
    from rest_framework.permissions import AllowAny
    public = {"authentication_classes": [], "permission_classes": [AllowAny]}
    urlpatterns += [
        path("api/schema/", SpectacularAPIView.as_view(**public), name="schema"),
        path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema", **public), name="docs"),
    ]
if settings.NAZRIA_ADMIN:
    admin.site.site_header = "Nazria Mufrad Aza – administration"
    urlpatterns += [path("admin/", admin.site.urls)]
