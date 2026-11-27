"""URL routes: /api/v1/... for the Android app, /api/docs/ (OpenAPI), /admin/ (staff)."""
from django.conf import settings
from django.contrib import admin
from django.urls import include, path

urlpatterns = [path("api/v1/", include("consultations.urls"))]

if settings.NAZRIA_API_DOCS:
    from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView
    from rest_framework.permissions import AllowAny
    public = {"authentication_classes": [], "permission_classes": [AllowAny]}
    urlpatterns += [
        path("api/schema/", SpectacularAPIView.as_view(**public), name="schema"),
        path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema", **public), name="docs"),
    ]
if settings.NAZRIA_ADMIN:
    urlpatterns += [path("admin/", admin.site.urls)]
