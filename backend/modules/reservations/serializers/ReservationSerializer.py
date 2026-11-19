"""Serializers du module 8.

Aucun champ de stock n'est modifiable par le client : l'acheteur saisit une
quantite et un message, tout le reste (vendeur, statut, quantites confirmee
et livree, dates) est calcule par le service.
"""
from decimal import Decimal

from rest_framework import serializers

from modules.products.models import Produit
from modules.products.serializers import ProduitListeSerializer
from modules.reservations.models import Reservation, StatutReservation


class ReservationSerializer(serializers.ModelSerializer):
    """Lecture d'une reservation, du point de vue des deux parties."""

    produit_detail = ProduitListeSerializer(source="produit", read_only=True)
    acheteur_username = serializers.CharField(
        source="acheteur.username", read_only=True
    )
    vendeur_username = serializers.CharField(source="vendeur.username", read_only=True)
    statut_libelle = serializers.CharField(
        source="get_statut_display", read_only=True
    )
    quantite_immobilisee = serializers.IntegerField(read_only=True)
    quantite_non_achetee = serializers.IntegerField(read_only=True)
    valeur_estimee = serializers.DecimalField(
        max_digits=16, decimal_places=2, read_only=True,
        help_text="Indicatif, au prix actuel de l'annonce. Jamais un revenu.",
    )
    est_expiree = serializers.BooleanField(read_only=True)
    mon_role = serializers.SerializerMethodField()

    class Meta:
        model = Reservation
        fields = (
            "id", "produit", "produit_detail",
            "acheteur", "acheteur_username", "vendeur", "vendeur_username",
            "quantite_demandee", "quantite_confirmee", "quantite_livree",
            "quantite_immobilisee", "quantite_non_achetee", "valeur_estimee",
            "statut", "statut_libelle", "est_expiree", "message",
            "expire_le", "confirmee_le", "cloturee_le", "cloturee_par",
            "motif", "mon_role", "created_at", "updated_at",
        )
        read_only_fields = fields

    def get_mon_role(self, obj) -> str:
        """ACHETEUR ou VENDEUR, selon qui consulte la reservation."""
        utilisateur = getattr(self.context.get("request"), "user", None)
        if utilisateur is None or not utilisateur.is_authenticated:
            return ""
        return obj.role_de(utilisateur)


class ReservationCreationSerializer(serializers.Serializer):
    """Demande de reservation : POST /reservations/."""

    produit = serializers.PrimaryKeyRelatedField(
        queryset=Produit.objects.all(),
        help_text="Annonce concernee. Elle doit etre active et avoir du stock.",
    )
    quantite_demandee = serializers.IntegerField(
        min_value=1,
        help_text="Quantite souhaitee, strictement positive.",
    )
    message = serializers.CharField(
        required=False, allow_blank=True, max_length=500,
        help_text="Facultatif : heure de passage, point de retrait...",
    )


class QuantiteSerializer(serializers.Serializer):
    """Quantite transmise a /accept/ et /quantity/."""

    quantite = serializers.IntegerField(
        min_value=1,
        required=False,
        help_text=(
            "Pour /accept/ : quantite reellement mise de cote (par defaut "
            "toute la quantite demandee). Pour /quantity/ : nouvelle quantite."
        ),
    )


class MotifSerializer(serializers.Serializer):
    """Motif transmis a /reject/ et /cancel/."""

    motif = serializers.CharField(
        required=False, allow_blank=True, max_length=255,
        help_text="Raison communiquee a l'autre partie.",
    )


class VenteDepuisReservationSerializer(serializers.Serializer):
    """Transformation d'une reservation en vente : /reservations/{id}/complete/.

    La quantite peut etre inferieure a la quantite reservee : c'est la vente
    partielle du cahier des charges. Le solde non achete est libere
    automatiquement.
    """

    quantite = serializers.IntegerField(
        min_value=1,
        required=False,
        help_text=(
            "Quantite reellement achetee. Par defaut, toute la quantite "
            "reservee."
        ),
    )
    prix_unitaire = serializers.DecimalField(
        max_digits=14, decimal_places=2, min_value=Decimal("0"),
        required=False,
        help_text=(
            "Prix finalement convenu. Par defaut, le prix affiche de "
            "l'annonce. Il est fige dans la ligne de vente."
        ),
    )
    moyen_paiement = serializers.CharField(
        required=False,
        help_text="CASH, LUMICASH, ECOCASH, VIREMENT ou AUTRE. Declaratif.",
    )
    note = serializers.CharField(
        required=False, allow_blank=True, max_length=500
    )


class StatistiquesReservationSerializer(serializers.Serializer):
    """Compteurs renvoyes par /reservations/summary/."""

    demandes_en_attente = serializers.IntegerField()
    demandes_acceptees = serializers.IntegerField()
    a_traiter = serializers.IntegerField(
        help_text="Demandes recues en attente de votre reponse."
    )
    reservations_acceptees_recues = serializers.IntegerField()
    quantite_immobilisee = serializers.IntegerField(
        help_text="Total des unites de vos annonces actuellement mises de cote."
    )


STATUTS_OUVERTS = (StatutReservation.PENDING, StatutReservation.CONFIRMED)
