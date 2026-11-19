"""Routage global : /api/v1/ avec separation public / prive / admin."""
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularRedocView,
    SpectacularSwaggerView,
)

API_V1 = "api/v1/"

urlpatterns = [
    path("django-admin/", admin.site.urls),
    # Documentation OpenAPI
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
    path("api/redoc/", SpectacularRedocView.as_view(url_name="schema"), name="redoc"),
    # Modules metier
    path(API_V1, include("modules.accounts.urls")),
    path(API_V1, include("modules.categories.urls")),
    path(API_V1, include("modules.products.urls")),
    path(API_V1, include("modules.search.urls")),
    path(API_V1, include("modules.sellers.urls")),
    path(API_V1, include("modules.favorites.urls")),
    path(API_V1, include("modules.messaging.urls")),
    path(API_V1, include("modules.reservations.urls")),
    path(API_V1, include("modules.sales.urls")),
    path(API_V1, include("modules.analytics.urls")),
    path(API_V1, include("modules.reviews.urls")),
    path(API_V1, include("modules.notifications.urls")),
    path(API_V1, include("modules.moderation.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
