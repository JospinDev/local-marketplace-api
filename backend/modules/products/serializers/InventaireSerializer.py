"""Serializers du stock (module 3).

Le vendeur declare uniquement `quantite_totale`. Les quantites reservee et
vendue sont en lecture seule : elles appartiennent aux modules Reservations
et Ventes.
"""
from rest_framework import serializers

from modules.products.models import Inventaire


class InventaireSerializer(serializers.ModelSerializer):
    quantite_disponible = serializers.IntegerField(read_only=True)
    valeur_stock = serializers.DecimalField(
        max_digits=18, decimal_places=2, read_only=True
    )
    valeur_reservations = serializers.DecimalField(
        max_digits=18, decimal_places=2, read_only=True
    )

    class Meta:
        model = Inventaire
        fields = (
            "quantite_totale", "quantite_reservee", "quantite_vendue",
            "quantite_disponible", "valeur_stock", "valeur_reservations",
            "updated_at",
        )
        read_only_fields = (
            "quantite_reservee", "quantite_vendue", "updated_at",
        )

    def validate_quantite_totale(self, value):
        """Le stock total ne peut pas descendre sous ce qui est engage."""
        if self.instance is not None:
            engage = self.instance.quantite_reservee + self.instance.quantite_vendue
            if value < engage:
                raise serializers.ValidationError(
                    f"Le stock total ne peut pas etre inferieur a {engage} "
                    f"({self.instance.quantite_reservee} reserve(s) + "
                    f"{self.instance.quantite_vendue} vendu(s))."
                )
        return value


class InventaireLectureSerializer(serializers.ModelSerializer):
    """Vue stock imbriquee dans le produit."""

    quantite_disponible = serializers.IntegerField(read_only=True)

    class Meta:
        model = Inventaire
        fields = (
            "quantite_totale", "quantite_reservee", "quantite_vendue",
            "quantite_disponible",
        )
        read_only_fields = fields
