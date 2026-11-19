"""Routage du module 10 : /seller-dashboard/."""
from django.urls import include, path
from rest_framework.routers import SimpleRouter

from modules.analytics.viewsets import TableauDeBordViewSet

router = SimpleRouter()
router.register(
    "seller-dashboard", TableauDeBordViewSet, basename="seller-dashboard"
)

urlpatterns = [
    path("", include(router.urls)),
]
