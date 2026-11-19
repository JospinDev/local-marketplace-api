"""Routage du module 3 : /products/ (vendeur) et /admin/products/ (moderation)."""
from django.urls import include, path
from rest_framework.routers import SimpleRouter

from modules.products.viewsets import ProduitAdminViewSet, ProduitViewSet

router_prive = SimpleRouter()
router_prive.register("products", ProduitViewSet, basename="products")

router_admin = SimpleRouter()
router_admin.register("products", ProduitAdminViewSet, basename="admin-products")

urlpatterns = [
    path("", include(router_prive.urls)),
    path("admin/", include(router_admin.urls)),
]
