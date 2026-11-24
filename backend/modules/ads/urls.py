"""Routage des publicites : /public/ads/ et /admin/ads/."""
from django.urls import include, path
from rest_framework.routers import SimpleRouter

from modules.ads.viewsets import PubliciteAdminViewSet, PublicitePubliqueViewSet

router_public = SimpleRouter()
router_public.register("ads", PublicitePubliqueViewSet, basename="public-ads")

router_admin = SimpleRouter()
router_admin.register("ads", PubliciteAdminViewSet, basename="admin-ads")

urlpatterns = [
    path("public/", include(router_public.urls)),
    path("admin/", include(router_admin.urls)),
]
