"""Module 5 - Filtres des profils vendeurs (django-filter)."""
from django.contrib.auth import get_user_model
from django_filters import rest_framework as filters

User = get_user_model()


class VendeurFilter(filters.FilterSet):
    # --- texte ------------------------------------------------------------
    username = filters.CharFilter(field_name="username", lookup_expr="icontains")
    nom_commercial = filters.CharFilter(
        field_name="nom_commercial", lookup_expr="icontains"
    )
    nom_complet = filters.CharFilter(field_name="nom_complet", lookup_expr="icontains")
    q = filters.CharFilter(
        method="filtrer_mots_cles",
        label="Recherche (nom commercial, nom, username, localisation)",
    )

    # --- localisation : un seul champ texte, en icontains -----------------
    localisation = filters.CharFilter(
        field_name="localisation",
        lookup_expr="icontains",
        label="Localisation contenant le mot saisi (ex. taba)",
    )

    # --- statistiques : gte / lte ----------------------------------------
    produits_min = filters.NumberFilter(
        field_name="nombre_produits_actifs", lookup_expr="gte"
    )
    produits_max = filters.NumberFilter(
        field_name="nombre_produits_actifs", lookup_expr="lte"
    )
    abonnes_min = filters.NumberFilter(field_name="nombre_abonnes", lookup_expr="gte")

    # --- dates ------------------------------------------------------------
    date_joined_gte = filters.DateTimeFilter(field_name="date_joined", lookup_expr="gte")
    date_joined_lte = filters.DateTimeFilter(field_name="date_joined", lookup_expr="lte")

    class Meta:
        model = User
        fields = []

    def filtrer_mots_cles(self, queryset, name, value):
        from django.db.models import Q

        return queryset.filter(
            Q(nom_commercial__icontains=value)
            | Q(nom_complet__icontains=value)
            | Q(username__icontains=value)
            | Q(localisation__icontains=value)
        )
