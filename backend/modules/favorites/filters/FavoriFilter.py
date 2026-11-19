"""Module 6 - Filtres des favoris (django-filter)."""
from django.db.models import F, Q
from django_filters import rest_framework as filters

from modules.favorites.models import Favori
from modules.products.models import EtatProduit, StatutProduit


class FavoriFilter(filters.FilterSet):
    # --- sur le produit mis en favori -------------------------------------
    titre = filters.CharFilter(field_name="produit__titre", lookup_expr="icontains")
    categorie = filters.NumberFilter(field_name="produit__categorie_id")
    etat = filters.ChoiceFilter(
        field_name="produit__etat", choices=EtatProduit.choices
    )
    localisation = filters.CharFilter(
        field_name="produit__localisation",
        lookup_expr="icontains",
        label="Localisation contenant le mot saisi",
    )
    prix_min = filters.NumberFilter(field_name="produit__prix", lookup_expr="gte")
    prix_max = filters.NumberFilter(field_name="produit__prix", lookup_expr="lte")

    # --- alertes ----------------------------------------------------------
    disponible = filters.BooleanFilter(
        method="filtrer_disponible",
        label="Uniquement les favoris encore disponibles",
    )
    retire = filters.BooleanFilter(
        method="filtrer_retire",
        label="Uniquement les favoris dont l'annonce a ete retiree",
    )
    prix_a_change = filters.BooleanFilter(
        method="filtrer_prix_a_change",
        label="Uniquement les favoris dont le prix a change",
    )

    # --- dates ------------------------------------------------------------
    created_at_gte = filters.DateTimeFilter(field_name="created_at", lookup_expr="gte")
    created_at_lte = filters.DateTimeFilter(field_name="created_at", lookup_expr="lte")

    class Meta:
        model = Favori
        fields = {
            "prix_a_l_ajout": ["exact", "gte", "lte"],
            "created_at": ["exact", "gte", "lte"],
        }

    def filtrer_disponible(self, queryset, name, value):
        expression = (
            Q(produit__status=StatutProduit.ACTIVE)
            & Q(produit__owner__is_active=True)
            & Q(
                produit__inventaire__quantite_totale__gt=F(
                    "produit__inventaire__quantite_reservee"
                )
                + F("produit__inventaire__quantite_vendue")
            )
        )
        return queryset.filter(expression) if value else queryset.exclude(expression)

    def filtrer_retire(self, queryset, name, value):
        expression = Q(
            produit__status__in=[StatutProduit.ARCHIVED, StatutProduit.REMOVED]
        ) | Q(produit__owner__is_active=False)
        return queryset.filter(expression) if value else queryset.exclude(expression)

    def filtrer_prix_a_change(self, queryset, name, value):
        expression = Q(produit__prix=F("prix_a_l_ajout"))
        return queryset.exclude(expression) if value else queryset.filter(expression)
