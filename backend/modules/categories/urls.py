"""Routage du module 2 : /public/categories/ et /admin/categories/."""
from django.urls import include, path
from rest_framework.routers import SimpleRouter

from modules.categories.viewsets import CategoriePublicViewSet, CategorieViewSet

router_public = SimpleRouter()
router_public.register("categories", CategoriePublicViewSet, basename="public-categories")

router_admin = SimpleRouter()
router_admin.register("categories", CategorieViewSet, basename="admin-categories")

urlpatterns = [
    path("public/", include(router_public.urls)),
    path("admin/", include(router_admin.urls)),
]
