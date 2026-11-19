"""Routage REST du module 9 : /sales/."""
from django.urls import include, path
from rest_framework.routers import SimpleRouter

from modules.sales.viewsets import VenteViewSet

router = SimpleRouter()
router.register("sales", VenteViewSet, basename="sales")

urlpatterns = [
    path("", include(router.urls)),
]
