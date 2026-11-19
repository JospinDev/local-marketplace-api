"""Module 14 - Filtres de l'administration (django-filter)."""
from django_filters import rest_framework as filters

from modules.moderation.models import ActionAudit, JournalAudit
from modules.products.models import MouvementStock, TypeMouvementStock


class ListeDeValeurs(filters.BaseInFilter, filters.CharFilter):
    """Permet `?action_in=SUSPENSION_COMPTE,MODERATION_ANNONCE`."""


class JournalAuditFilter(filters.FilterSet):
    action = filters.ChoiceFilter(choices=ActionAudit.choices)
    action_in = ListeDeValeurs(
        field_name="action", label="Plusieurs actions separees par des virgules"
    )
    acteur = filters.NumberFilter(field_name="acteur_id")
    acteur_username = filters.CharFilter(
        field_name="acteur_username", lookup_expr="icontains"
    )
    cible_libelle = filters.CharFilter(
        field_name="cible_libelle", lookup_expr="icontains"
    )
    motif = filters.CharFilter(field_name="motif", lookup_expr="icontains")

    created_at_gte = filters.DateTimeFilter(field_name="created_at", lookup_expr="gte")
    created_at_lte = filters.DateTimeFilter(field_name="created_at", lookup_expr="lte")

    class Meta:
        model = JournalAudit
        fields = {
            "cible_type": ["exact"],
            "cible_id": ["exact"],
            "adresse_ip": ["exact"],
            "created_at": ["exact", "gte", "lte"],
        }


class MouvementStockFilter(filters.FilterSet):
    """Filtres de l'historique du stock, cote administration."""

    type_mouvement = filters.ChoiceFilter(choices=TypeMouvementStock.choices)
    type_in = ListeDeValeurs(
        field_name="type_mouvement",
        label="Plusieurs types separes par des virgules",
    )

    produit = filters.NumberFilter(field_name="produit_id")
    titre = filters.CharFilter(field_name="produit__titre", lookup_expr="icontains")
    owner = filters.NumberFilter(field_name="produit__owner_id")
    owner_username = filters.CharFilter(
        field_name="produit__owner__username", lookup_expr="icontains"
    )
    localisation = filters.CharFilter(
        field_name="produit__localisation",
        lookup_expr="icontains",
        label="Localisation contenant le mot saisi",
    )
    effectue_par = filters.NumberFilter(field_name="effectue_par_id")
    commentaire = filters.CharFilter(
        field_name="commentaire", lookup_expr="icontains"
    )

    created_at_gte = filters.DateTimeFilter(field_name="created_at", lookup_expr="gte")
    created_at_lte = filters.DateTimeFilter(field_name="created_at", lookup_expr="lte")

    class Meta:
        model = MouvementStock
        fields = {
            "quantite": ["exact", "gte", "lte"],
            "reference_type": ["exact"],
            "reference_id": ["exact"],
            "created_at": ["exact", "gte", "lte"],
        }
