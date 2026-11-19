"""Routage du module 5 : /public/sellers/ et /following/.

Les routes `/following/sellers/{id}/` acceptent POST (suivre) et DELETE
(ne plus suivre) sur la meme URL, comme prevu au cahier des charges : les
methodes du ViewSet sont donc mappees explicitement.
"""
from django.urls import include, path
from rest_framework.routers import SimpleRouter

from modules.sellers.viewsets import (
    AbonnementViewSet,
    ProduitsSuivisViewSet,
    VendeurPublicViewSet,
)

router_public = SimpleRouter()
router_public.register("sellers", VendeurPublicViewSet, basename="public-sellers")

abonnements_liste = AbonnementViewSet.as_view({"get": "list"})
abonnement_detail = AbonnementViewSet.as_view(
    {"post": "suivre", "delete": "ne_plus_suivre"}
)
produits_suivis = ProduitsSuivisViewSet.as_view({"get": "list"})

urlpatterns = [
    path("public/", include(router_public.urls)),
    path("following/sellers/", abonnements_liste, name="following-sellers"),
    path(
        "following/sellers/<int:vendeur_id>/",
        abonnement_detail,
        name="following-seller-detail",
    ),
    path("following/products/", produits_suivis, name="following-products"),
]
