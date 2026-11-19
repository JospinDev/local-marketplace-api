"""Routage du module 6 : /favorites/products/.

POST et DELETE partagent la meme URL de detail, comme prevu au cahier des
charges : les methodes du ViewSet sont mappees explicitement.
"""
from django.urls import path

from modules.favorites.viewsets import FavoriViewSet

favoris_liste = FavoriViewSet.as_view({"get": "list"})
favori_detail = FavoriViewSet.as_view({"post": "ajouter", "delete": "retirer"})

urlpatterns = [
    path("favorites/products/", favoris_liste, name="favorites-list"),
    path(
        "favorites/products/<int:produit_id>/",
        favori_detail,
        name="favorites-detail",
    ),
]
