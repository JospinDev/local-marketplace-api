"""Module 8 - Filtres des reservations (django-filter).

La recherche par localisation utilise `icontains` sur le champ texte libre du
produit : l'acheteur tape "taba" et retrouve ses reservations sur des
annonces situees a "Taba", "Taba centre", "Kamenge pres de Taba"...
"""
from django.utils import timezone
from django_filters import rest_framework as filters

from modules.products.models import EtatProduit
from modules.reservations.models import (
    Reservation,
    ReservationQuerySet,
    StatutReservation,
)


class ListeDeStatuts(filters.BaseInFilter, filters.CharFilter):
    """Permet `?statut_in=PENDING,CONFIRMED`."""


class ReservationFilter(filters.FilterSet):
    # --- statut ------------------------------------------------------------
    statut = filters.ChoiceFilter(choices=StatutReservation.choices)
    statut_in = ListeDeStatuts(
        field_name="statut", label="Plusieurs statuts separes par des virgules"
    )
    actives = filters.BooleanFilter(
        method="filtrer_actives",
        label="Uniquement les reservations en cours (PENDING ou CONFIRMED)",
    )
    expirees = filters.BooleanFilter(
        method="filtrer_expirees",
        label="Reservations actives dont le delai est depasse",
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

    # --- produit concerne --------------------------------------------------
    produit = filters.NumberFilter(field_name="produit_id")
    titre = filters.CharFilter(field_name="produit__titre", lookup_expr="icontains")
    categorie = filters.NumberFilter(field_name="produit__categorie_id")
    etat = filters.ChoiceFilter(field_name="produit__etat", choices=EtatProduit.choices)
    localisation = filters.CharFilter(
        field_name="produit__localisation",
        lookup_expr="icontains",
        label="Localisation contenant le mot saisi",
    )
    prix_min = filters.NumberFilter(field_name="produit__prix", lookup_expr="gte")
    prix_max = filters.NumberFilter(field_name="produit__prix", lookup_expr="lte")

    # --- dates -------------------------------------------------------------
    created_at_gte = filters.DateTimeFilter(field_name="created_at", lookup_expr="gte")
    created_at_lte = filters.DateTimeFilter(field_name="created_at", lookup_expr="lte")
    expire_le_gte = filters.DateTimeFilter(field_name="expire_le", lookup_expr="gte")
    expire_le_lte = filters.DateTimeFilter(field_name="expire_le", lookup_expr="lte")

    class Meta:
        model = Reservation
        fields = {
            "quantite_demandee": ["exact", "gte", "lte"],
            "quantite_confirmee": ["exact", "gte", "lte"],
            "quantite_livree": ["exact", "gte", "lte"],
            "confirmee_le": ["gte", "lte", "isnull"],
            "cloturee_le": ["gte", "lte", "isnull"],
        }

    def filtrer_actives(self, queryset, name, value):
        if value is None:
            return queryset
        return queryset.actives() if value else queryset.exclude(
            statut__in=ReservationQuerySet.STATUTS_ACTIFS
        )

    def filtrer_expirees(self, queryset, name, value):
        if value is None:
            return queryset
        maintenant = timezone.now()
        if value:
            return queryset.expirables(maintenant)
        return queryset.exclude(
            statut__in=ReservationQuerySet.STATUTS_ACTIFS, expire_le__lt=maintenant
        )
