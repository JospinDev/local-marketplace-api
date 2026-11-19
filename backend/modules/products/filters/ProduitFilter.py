"""Filtres des annonces (module 3) - django-filter avec lookups explicites.

Prix, quantites et dates : `exact`, `gte`, `lte`.
Textes et localisation : `icontains`.
"""
from django.db.models import F, Q
from django_filters import rest_framework as filters

from modules.products.models import EtatProduit, Produit, StatutProduit


class ProduitFilter(filters.FilterSet):
    # --- texte ------------------------------------------------------------
    titre = filters.CharFilter(field_name="titre", lookup_expr="icontains")
    description = filters.CharFilter(field_name="description", lookup_expr="icontains")
    q = filters.CharFilter(
        method="filtrer_mots_cles",
        label="Recherche par mots-cles (titre, description, categorie, localisation)",
    )

    # --- categorie --------------------------------------------------------
    categorie = filters.NumberFilter(field_name="categorie_id")
    categorie_slug = filters.CharFilter(
        field_name="categorie__slug", lookup_expr="iexact"
    )
    categorie_arbre = filters.NumberFilter(
        method="filtrer_categorie_arbre",
        label="Categorie incluant ses sous-categories",
    )

    # --- prix : gte / lte -------------------------------------------------
    prix_min = filters.NumberFilter(field_name="prix", lookup_expr="gte")
    prix_max = filters.NumberFilter(field_name="prix", lookup_expr="lte")

    # --- localisation : un seul champ texte, en icontains -----------------
    # L'acheteur tape "taba" et obtient toutes les annonces dont la
    # localisation contient "taba", quelle que soit la casse.
    localisation = filters.CharFilter(
        field_name="localisation",
        lookup_expr="icontains",
        label="Localisation contenant le mot saisi (ex. taba)",
    )

    # --- etat, statut, vendeur -------------------------------------------
    etat = filters.ChoiceFilter(choices=EtatProduit.choices)
    status = filters.ChoiceFilter(choices=StatutProduit.choices)
    status_in = filters.BaseInFilter(field_name="status", lookup_expr="in")
    owner = filters.NumberFilter(field_name="owner_id")
    owner_username = filters.CharFilter(
        field_name="owner__username", lookup_expr="iexact"
    )
    est_mis_en_avant = filters.BooleanFilter()

    # --- disponibilite ----------------------------------------------------
    disponible = filters.BooleanFilter(
        method="filtrer_disponible",
        label="Uniquement les annonces avec du stock disponible",
    )
    quantite_min = filters.NumberFilter(
        method="filtrer_quantite_min",
        label="Quantite disponible minimale",
    )

    # --- dates ------------------------------------------------------------
    created_at_gte = filters.DateTimeFilter(field_name="created_at", lookup_expr="gte")
    created_at_lte = filters.DateTimeFilter(field_name="created_at", lookup_expr="lte")
    publie_le_gte = filters.DateTimeFilter(field_name="publie_le", lookup_expr="gte")
    publie_le_lte = filters.DateTimeFilter(field_name="publie_le", lookup_expr="lte")

    class Meta:
        model = Produit
        fields = {
            "prix": ["exact", "gte", "lte"],
            "devise": ["exact"],
            "etat": ["exact"],
            "status": ["exact"],
            "nombre_vues": ["gte", "lte"],
            "created_at": ["exact", "gte", "lte"],
        }

    # ------------------------------------------------------------- methodes
    def filtrer_mots_cles(self, queryset, name, value):
        return queryset.filter(
            Q(titre__icontains=value)
            | Q(description__icontains=value)
            | Q(categorie__nom__icontains=value)
            | Q(localisation__icontains=value)
        )

    def filtrer_categorie_arbre(self, queryset, name, value):
        """Inclut la categorie demandee et toutes ses sous-categories."""
        from modules.categories.models import Categorie

        identifiants = [value]
        niveau = list(
            Categorie.objects.filter(parent_id=value).values_list("id", flat=True)
        )
        while niveau:
            identifiants.extend(niveau)
            niveau = list(
                Categorie.objects.filter(parent_id__in=niveau).values_list(
                    "id", flat=True
                )
            )
        return queryset.filter(categorie_id__in=identifiants)

    def filtrer_disponible(self, queryset, name, value):
        expression = Q(
            inventaire__quantite_totale__gt=F("inventaire__quantite_reservee")
            + F("inventaire__quantite_vendue")
        )
        return queryset.filter(expression) if value else queryset.exclude(expression)

    def filtrer_quantite_min(self, queryset, name, value):
        return queryset.filter(
            inventaire__quantite_totale__gte=F("inventaire__quantite_reservee")
            + F("inventaire__quantite_vendue")
            + value
        )
