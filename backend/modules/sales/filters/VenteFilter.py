"""Module 9 - Filtres des ventes (django-filter)."""
from django_filters import rest_framework as filters

from modules.sales.models import (
    MoyenPaiement,
    StatutPaiement,
    StatutVente,
    Vente,
    VenteQuerySet,
)


class ListeDeStatuts(filters.BaseInFilter, filters.CharFilter):
    """Permet `?statut_in=PAID,COMPLETED`."""


class VenteFilter(filters.FilterSet):
    # --- statuts -----------------------------------------------------------
    statut = filters.ChoiceFilter(choices=StatutVente.choices)
    statut_in = ListeDeStatuts(
        field_name="statut", label="Plusieurs statuts separes par des virgules"
    )
    statut_paiement = filters.ChoiceFilter(choices=StatutPaiement.choices)
    moyen_paiement = filters.ChoiceFilter(choices=MoyenPaiement.choices)
    comptabilisables = filters.BooleanFilter(
        method="filtrer_comptabilisables",
        label="Uniquement les ventes qui entrent dans le chiffre d'affaires",
    )

    # --- parties prenantes -------------------------------------------------
    acheteur = filters.NumberFilter(field_name="acheteur_id")
    vendeur = filters.NumberFilter(field_name="vendeur_id")
    acheteur_username = filters.CharFilter(
        field_name="acheteur__username", lookup_expr="icontains"
    )
    vendeur_username = filters.CharFilter(
        field_name="vendeur__username", lookup_expr="icontains"
    )

    # --- produit vendu -----------------------------------------------------
    produit = filters.NumberFilter(field_name="lignes__produit_id", distinct=True)
    titre = filters.CharFilter(
        field_name="lignes__produit__titre", lookup_expr="icontains", distinct=True
    )
    categorie = filters.NumberFilter(
        field_name="lignes__produit__categorie_id", distinct=True
    )
    localisation = filters.CharFilter(
        field_name="lignes__produit__localisation",
        lookup_expr="icontains",
        distinct=True,
        label="Localisation contenant le mot saisi",
    )

    # --- montants et dates -------------------------------------------------
    montant_min = filters.NumberFilter(field_name="montant_total", lookup_expr="gte")
    montant_max = filters.NumberFilter(field_name="montant_total", lookup_expr="lte")
    created_at_gte = filters.DateTimeFilter(field_name="created_at", lookup_expr="gte")
    created_at_lte = filters.DateTimeFilter(field_name="created_at", lookup_expr="lte")
    confirmee_le_gte = filters.DateTimeFilter(
        field_name="confirmee_le", lookup_expr="gte"
    )
    confirmee_le_lte = filters.DateTimeFilter(
        field_name="confirmee_le", lookup_expr="lte"
    )

    class Meta:
        model = Vente
        fields = {
            "montant_total": ["exact", "gte", "lte"],
            "reservation": ["exact", "isnull"],
            "confirmee_le": ["isnull"],
            "confirmee_par_acheteur_le": ["isnull"],
            "annulee_le": ["isnull"],
        }

    def filtrer_comptabilisables(self, queryset, name, value):
        if value is None:
            return queryset
        if value:
            return queryset.comptabilisables()
        return queryset.exclude(statut__in=VenteQuerySet.STATUTS_COMPTABILISABLES)
