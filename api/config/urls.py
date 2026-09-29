from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from config.views import health
from integration.api import integration_urls, reference_urls

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/health/", health, name="health"),
    path("api/schema/", SpectacularAPIView.as_view(permission_classes=[]), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema", permission_classes=[]), name="docs"),
    path("api/v1/auth/", include("iam.urls")),
    path("api/v1/notifications/", include("notifications.api")),
    path("api/v1/", include("programmes.api")),
    path("api/v1/", include("students.api")),
    path("api/v1/academics/", include("academics.api")),
    path("api/v1/reports/", include("reports.api")),
    path("api/v1/reference/", include((reference_urls, "reference"))),
    # Service-to-service API for the GSA ecosystem (LMS). Api-Key authentication, scoped.
    path("api/v1/integration/", include((integration_urls, "integration"))),
]

# Student documents are never served from MEDIA_URL; downloads go through authenticated endpoints.
