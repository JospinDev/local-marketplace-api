"""Routage REST du module 8 : /reservations/."""
from django.urls import include, path
from rest_framework.routers import SimpleRouter

from modules.reservations.viewsets import ReservationViewSet

router = SimpleRouter()
router.register("reservations", ReservationViewSet, basename="reservations")

urlpatterns = [
    path("", include(router.urls)),
]
