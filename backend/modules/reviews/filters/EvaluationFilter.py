"""Module 11 - Filtres des evaluations (django-filter)."""
from django_filters import rest_framework as filters

from modules.reviews.models import Evaluation, StatutEvaluation


class ListeDeStatuts(filters.BaseInFilter, filters.CharFilter):
    """Permet `?statut_in=VISIBLE,MASQUEE`."""


class EvaluationFilter(filters.FilterSet):
    # --- statut et moderation ---------------------------------------------
    statut = filters.ChoiceFilter(choices=StatutEvaluation.choices)
    statut_in = ListeDeStatuts(
        field_name="statut", label="Plusieurs statuts separes par des virgules"
    )
    signalees = filters.BooleanFilter(
        method="filtrer_signalees",
        label="Avis ayant un signalement non traite",
    )

    # --- parties prenantes -------------------------------------------------
    auteur = filters.NumberFilter(field_name="auteur_id")
    vendeur = filters.NumberFilter(field_name="vendeur_id")
    auteur_username = filters.CharFilter(
        field_name="auteur__username", lookup_expr="icontains"
    )
    vendeur_username = filters.CharFilter(
        field_name="vendeur__username", lookup_expr="icontains"
    )

    # --- produit evalue ----------------------------------------------------
    produit = filters.NumberFilter(field_name="produit_id")
    produit_slug = filters.CharFilter(field_name="produit__slug", lookup_expr="exact")
    titre = filters.CharFilter(field_name="produit__titre", lookup_expr="icontains")
    categorie = filters.NumberFilter(field_name="produit__categorie_id")
    localisation = filters.CharFilter(
        field_name="produit__localisation",
        lookup_expr="icontains",
        label="Localisation contenant le mot saisi",
    )

    # --- contenu -----------------------------------------------------------
    commentaire = filters.CharFilter(
        field_name="commentaire", lookup_expr="icontains"
    )
    avec_commentaire = filters.BooleanFilter(
        method="filtrer_avec_commentaire",
        label="Uniquement les avis accompagnes d'un texte",
    )

    # --- dates -------------------------------------------------------------
    created_at_gte = filters.DateTimeFilter(field_name="created_at", lookup_expr="gte")
    created_at_lte = filters.DateTimeFilter(field_name="created_at", lookup_expr="lte")

    class Meta:
        model = Evaluation
        fields = {
            "note_produit": ["exact", "gte", "lte"],
            "note_vendeur": ["exact", "gte", "lte"],
            "vente": ["exact"],
            "modifiee_le": ["isnull", "gte", "lte"],
        }

    def filtrer_signalees(self, queryset, name, value):
        if value is None:
            return queryset
        expression = {"signalements__traite_le__isnull": True}
        if value:
            return queryset.filter(**expression).distinct()
        return queryset.exclude(**expression)

    def filtrer_avec_commentaire(self, queryset, name, value):
        if value is None:
            return queryset
        if value:
            return queryset.exclude(commentaire="")
        return queryset.filter(commentaire="")
