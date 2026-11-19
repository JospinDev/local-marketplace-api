"""Module 6 - Serializers des favoris.

Chaque favori signale a l'utilisateur :
- si le produit est toujours disponible,
- si l'annonce a ete retiree ou archivee,
- si le prix a change depuis la mise en favori.
"""
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from modules.favorites.models import Favori
from modules.search.serializers import ProduitPublicListeSerializer


class FavoriSerializer(serializers.ModelSerializer):
    """Ligne de la liste des favoris."""

    produit = ProduitPublicListeSerializer(read_only=True)
    prix_actuel = serializers.DecimalField(
        source="produit.prix", max_digits=14, decimal_places=2, read_only=True
    )
    variation_prix = serializers.DecimalField(
        max_digits=14, decimal_places=2, read_only=True
    )
    prix_a_change = serializers.BooleanField(read_only=True)
    est_toujours_disponible = serializers.BooleanField(read_only=True)
    est_retire = serializers.BooleanField(read_only=True)
    alerte = serializers.SerializerMethodField()

    class Meta:
        model = Favori
        fields = (
            "id", "produit", "prix_a_l_ajout", "prix_actuel", "variation_prix",
            "prix_a_change", "est_toujours_disponible", "est_retire",
            "alerte", "created_at",
        )
        read_only_fields = fields

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_alerte(self, obj):
        """Message pret a afficher dans l'application mobile."""
        if obj.est_retire:
            return "Cette annonce n'est plus disponible : elle a ete retiree."
        if not obj.est_toujours_disponible:
            return "Ce produit est momentanement en rupture de stock."
        if obj.prix_a_change:
            variation = obj.variation_prix
            sens = "augmente" if variation > 0 else "baisse"
            return (
                f"Le prix a {sens} de {abs(variation)} "
                f"{obj.produit.devise} depuis votre mise en favori."
            )
        return None
