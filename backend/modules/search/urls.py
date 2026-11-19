"""Routage du module 4 : /public/products/."""
from django.urls import include, path
from rest_framework.routers import SimpleRouter

from modules.search.viewsets import ProduitPublicViewSet

router_public = SimpleRouter()
router_public.register("products", ProduitPublicViewSet, basename="public-products")

urlpatterns = [
    path("public/", include(router_public.urls)),
]
