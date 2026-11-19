"""Filtres du module 2 (django-filter).

Lookups exposes : `exact`, `icontains`, `gte`, `lte`, `in`, `isnull`.
"""
from django_filters import rest_framework as filters

from modules.categories.models import Categorie


class CategorieFilter(filters.FilterSet):
    # --- texte ------------------------------------------------------------
    nom = filters.CharFilter(field_name="nom", lookup_expr="icontains")
    nom_exact = filters.CharFilter(field_name="nom", lookup_expr="iexact")
    description = filters.CharFilter(field_name="description", lookup_expr="icontains")
    slug = filters.CharFilter(field_name="slug", lookup_expr="iexact")
    recherche = filters.CharFilter(
        method="filtrer_recherche",
        label="Recherche (nom ou description contient)",
    )

    # --- hierarchie -------------------------------------------------------
    parent = filters.ModelChoiceFilter(queryset=Categorie.objects.all())
    parent_slug = filters.CharFilter(field_name="parent__slug", lookup_expr="iexact")
    racines = filters.BooleanFilter(
        field_name="parent", lookup_expr="isnull",
        label="Uniquement les categories racines",
    )

    # --- etat et ordre ----------------------------------------------------
    is_active = filters.BooleanFilter()
    ordre_gte = filters.NumberFilter(field_name="ordre", lookup_expr="gte")
    ordre_lte = filters.NumberFilter(field_name="ordre", lookup_expr="lte")

    # --- dates ------------------------------------------------------------
    created_at_gte = filters.DateTimeFilter(field_name="created_at", lookup_expr="gte")
    created_at_lte = filters.DateTimeFilter(field_name="created_at", lookup_expr="lte")

    class Meta:
        model = Categorie
        fields = {
            "is_active": ["exact"],
            "ordre": ["exact", "gte", "lte"],
            "created_at": ["exact", "gte", "lte"],
            "updated_at": ["gte", "lte"],
        }

    def filtrer_recherche(self, queryset, name, value):
        from django.db.models import Q

        return queryset.filter(
            Q(nom__icontains=value) | Q(description__icontains=value)
        )
