"""Module 4 - Filtres de recherche publique.

Reprend `ProduitFilter` (module 3) et ajoute la recherche par proximite
geographique. Le filtre de statut est retire : le catalogue public n'expose
que les annonces visibles, ce qui est impose par le ViewSet et ne doit pas
etre contournable par un parametre d'URL.
"""
from decimal import Decimal

from django_filters import rest_framework as filters

from modules.products.filters import ProduitFilter
from modules.products.models import Produit


class ProduitRechercheFilter(ProduitFilter):
    """Filtres exposes aux visiteurs et aux acheteurs."""

    # Recherche a proximite : rayon en kilometres autour d'un point.
    # Les bornes sont validees ici : une coordonnee invalide donne une erreur
    # 400 explicite plutot qu'un filtre silencieusement ignore.
    latitude = filters.NumberFilter(
        method="ignorer",
        label="Latitude du point de reference",
        min_value=-90,
        max_value=90,
    )
    longitude = filters.NumberFilter(
        method="ignorer",
        label="Longitude du point de reference",
        min_value=-180,
        max_value=180,
    )
    rayon_km = filters.NumberFilter(
        method="filtrer_rayon",
        label="Rayon maximal en km (necessite latitude et longitude)",
        min_value=0,
    )

    class Meta(ProduitFilter.Meta):
        model = Produit
        fields = {
            "prix": ["exact", "gte", "lte"],
            "devise": ["exact"],
            "etat": ["exact"],
            "nombre_vues": ["gte", "lte"],
            "created_at": ["exact", "gte", "lte"],
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Le visiteur ne choisit pas le statut des annonces qu'il consulte.
        for champ in ("status", "status_in", "status__exact"):
            self.filters.pop(champ, None)

    def ignorer(self, queryset, name, value):
        """Latitude et longitude sont lues par le ViewSet, pas filtrantes."""
        return queryset

    def filtrer_rayon(self, queryset, name, value):
        """Filtre sur la distance annotee par le ViewSet.

        Le rayon n'a de sens qu'avec un point de reference : sans `latitude`
        ET `longitude`, le parametre est ignore plutot que de vider la liste
        (la distance annotee vaut alors NULL).
        """
        donnees = self.data or {}
        if not (donnees.get("latitude") and donnees.get("longitude")):
            return queryset
        if "distance_km" not in queryset.query.annotations:
            return queryset
        try:
            rayon = Decimal(str(value))
        except (TypeError, ValueError, ArithmeticError):
            return queryset
        return queryset.filter(distance_km__lte=rayon)
