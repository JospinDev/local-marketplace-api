"""Tri avec alias : le nom expose a l'API peut differer du champ trie.

DRF ne propose pas ce mecanisme : dans `ordering_fields`, un tuple
`("champ", "libelle")` ne cree pas d'alias, le second element sert seulement
de libelle dans l'interface navigable.

Utilite : exposer `ordering=distance_km` tout en triant sur `distance_tri`,
un champ annexe qui place les annonces sans coordonnees en dernier quel que
soit le traitement des NULL par le moteur SQL.

Declaration dans un ViewSet :

    ordering_fields = ("prix", "distance_km")
    ordering_aliases = {"distance_km": "distance_tri"}
"""
from rest_framework.filters import OrderingFilter


class AliasOrderingFilter(OrderingFilter):
    """`OrderingFilter` traduisant les noms publics en champs reels."""

    def get_ordering(self, request, queryset, view):
        ordering = super().get_ordering(request, queryset, view)
        aliases = getattr(view, "ordering_aliases", None) or {}
        if not ordering or not aliases:
            return ordering

        traduits = []
        for terme in ordering:
            decroissant = terme.startswith("-")
            nom = terme[1:] if decroissant else terme
            reel = aliases.get(nom, nom)
            traduits.append(f"-{reel}" if decroissant else reel)
        return traduits
