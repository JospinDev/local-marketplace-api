"""Routage du module 14 : tout sous /api/v1/admin/.

Les autres portes d'administration vivent avec leur module : /admin/users/
(module 1), /admin/categories/ (module 2), /admin/products/ (module 3) et
/admin/reviews/ (module 11). Ce fichier n'ajoute que ce qui n'appartenait a
aucun module metier.
"""
from django.urls import include, path
from rest_framework.routers import SimpleRouter

from modules.moderation.viewsets import (
    JournalAuditViewSet,
    MouvementStockAdminViewSet,
    ParametrePlateformeViewSet,
    ReservationAdminViewSet,
    SignalementViewSet,
    StatistiquesViewSet,
    VenteAdminViewSet,
)

router = SimpleRouter()
router.register("audit-logs", JournalAuditViewSet, basename="admin-audit-logs")
router.register("settings", ParametrePlateformeViewSet, basename="admin-settings")
router.register("statistics", StatistiquesViewSet, basename="admin-statistics")
router.register("reports", SignalementViewSet, basename="admin-reports")
router.register(
    "stock-movements", MouvementStockAdminViewSet, basename="admin-stock-movements"
)
router.register("sales", VenteAdminViewSet, basename="admin-sales")
router.register(
    "reservations", ReservationAdminViewSet, basename="admin-reservations"
)

urlpatterns = [
    path("admin/", include(router.urls)),
]
