"""Filtres d'administration des publicites.

Les bornes sont explicites (`lte`, `gte`, `exact`) comme partout ailleurs
dans le projet : un filtre dont on ne voit pas la comparaison dans son nom
se prete aux malentendus.
"""
from django_filters import rest_framework as filters

from modules.ads.models import Publicite, TypeCiblePublicite


class PubliciteFilter(filters.FilterSet):
    actif = filters.BooleanFilter()
    type_cible = filters.ChoiceFilter(choices=TypeCiblePublicite.choices)

    ordre = filters.NumberFilter()
    ordre_lte = filters.NumberFilter(field_name="ordre", lookup_expr="lte")
    ordre_gte = filters.NumberFilter(field_name="ordre", lookup_expr="gte")

    titre = filters.CharFilter(lookup_expr="icontains")

    debut_le_lte = filters.IsoDateTimeFilter(field_name="debut_le", lookup_expr="lte")
    debut_le_gte = filters.IsoDateTimeFilter(field_name="debut_le", lookup_expr="gte")
    fin_le_lte = filters.IsoDateTimeFilter(field_name="fin_le", lookup_expr="lte")
    fin_le_gte = filters.IsoDateTimeFilter(field_name="fin_le", lookup_expr="gte")

    class Meta:
        model = Publicite
        fields = ("actif", "type_cible", "ordre", "titre")
