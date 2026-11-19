"""Filtres utilisateurs : django-filter avec lookups explicites.

Localisation : un seul champ texte, recherche par `icontains`. Le client
tape un mot et on retourne tous les comptes dont la localisation contient
ce mot. Aucun identifiant de localisation.
Dates et booleens : lookups `exact`, `gte`, `lte`.
"""
from django.contrib.auth import get_user_model
from django_filters import rest_framework as filters

from modules.accounts.models import StatutCompte

User = get_user_model()


class UserFilter(filters.FilterSet):
    # --- identite -----------------------------------------------------
    username = filters.CharFilter(field_name="username", lookup_expr="icontains")
    username_exact = filters.CharFilter(field_name="username", lookup_expr="iexact")
    nom_complet = filters.CharFilter(field_name="nom_complet", lookup_expr="icontains")
    nom_commercial = filters.CharFilter(
        field_name="nom_commercial", lookup_expr="icontains"
    )
    email = filters.CharFilter(field_name="email", lookup_expr="icontains")
    telephone = filters.CharFilter(field_name="telephone", lookup_expr="icontains")

    # --- localisation : un seul champ, en icontains -----------------------
    localisation = filters.CharFilter(
        field_name="localisation",
        lookup_expr="icontains",
        label="Localisation contenant le mot saisi (ex. taba)",
    )

    # --- etat du compte ---------------------------------------------------
    statut_compte = filters.ChoiceFilter(choices=StatutCompte.choices)
    email_verifie = filters.BooleanFilter()
    is_active = filters.BooleanFilter()
    groupe = filters.CharFilter(field_name="groups__name", lookup_expr="iexact")

    # --- dates : gte / lte ------------------------------------------------
    date_joined_gte = filters.DateTimeFilter(field_name="date_joined", lookup_expr="gte")
    date_joined_lte = filters.DateTimeFilter(field_name="date_joined", lookup_expr="lte")

    class Meta:
        model = User
        fields = {
            "statut_compte": ["exact"],
            "email_verifie": ["exact"],
            "is_active": ["exact"],
            "is_staff": ["exact"],
            "date_joined": ["exact", "gte", "lte"],
        }
