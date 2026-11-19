"""Serializers du module 9.

Le montant total n'est jamais accepte depuis le client : il est derive des
lignes (quantite x prix unitaire fige). Le statut, les dates et le statut de
paiement sont pilotes par le service.
"""
from decimal import Decimal

from rest_framework import serializers

from modules.products.models import Produit
from modules.reservations.models import Reservation
from modules.sales.models import LigneVente, MoyenPaiement, Vente


class LigneVenteSerializer(serializers.ModelSerializer):
    produit_titre = serializers.CharField(source="produit.titre", read_only=True)
    produit_slug = serializers.CharField(source="produit.slug", read_only=True)

    class Meta:
        model = LigneVente
        fields = (
            "id", "produit", "produit_titre", "produit_slug",
            "quantite", "prix_unitaire", "sous_total",
        )
        read_only_fields = fields


class VenteSerializer(serializers.ModelSerializer):
    """Lecture d'une vente, pour le vendeur comme pour l'acheteur."""

    lignes = LigneVenteSerializer(many=True, read_only=True)
    acheteur_username = serializers.CharField(source="acheteur.username", read_only=True)
    vendeur_username = serializers.CharField(source="vendeur.username", read_only=True)
    statut_libelle = serializers.CharField(source="get_statut_display", read_only=True)
    moyen_paiement_libelle = serializers.CharField(
        source="get_moyen_paiement_display", read_only=True
    )
    quantite_totale = serializers.IntegerField(read_only=True)
    est_comptabilisable = serializers.BooleanField(
        read_only=True,
        help_text="Vrai si cette vente entre dans le chiffre d'affaires.",
    )
    mon_role = serializers.SerializerMethodField()

    class Meta:
        model = Vente
        fields = (
            "id", "reservation",
            "acheteur", "acheteur_username", "vendeur", "vendeur_username",
            "lignes", "quantite_totale", "montant_total", "devise",
            "moyen_paiement", "moyen_paiement_libelle",
            "statut", "statut_libelle", "statut_paiement",
            "est_comptabilisable", "note",
            "confirmee_le", "confirmee_par_acheteur_le",
            "annulee_le", "motif_annulation",
            "mon_role", "created_at", "updated_at",
        )
        read_only_fields = fields

    def get_mon_role(self, obj) -> str:
        """ACHETEUR ou VENDEUR, selon qui consulte la vente."""
        utilisateur = getattr(self.context.get("request"), "user", None)
        if utilisateur is None or not utilisateur.is_authenticated:
            return ""
        if utilisateur.pk == obj.acheteur_id:
            return "ACHETEUR"
        if utilisateur.pk == obj.vendeur_id:
            return "VENDEUR"
        return ""


class VenteCreationSerializer(serializers.Serializer):
    """Declaration d'une vente : POST /sales/.

    Deux usages, mutuellement exclusifs :

    - `reservation` : le client avait reserve, il vient retirer. La quantite
      peut etre inferieure a la quantite reservee (vente partielle) ;
    - `produit` + `acheteur` : vente directe, sans reservation prealable.
    """

    reservation = serializers.PrimaryKeyRelatedField(
        queryset=Reservation.objects.all(), required=False,
        help_text="Reservation acceptee a transformer en vente.",
    )
    produit = serializers.PrimaryKeyRelatedField(
        queryset=Produit.objects.all(), required=False,
        help_text="Vente directe : annonce concernee.",
    )
    acheteur = serializers.IntegerField(
        required=False,
        help_text="Vente directe : identifiant du client.",
    )
    quantite = serializers.IntegerField(
        min_value=1, required=False,
        help_text=(
            "Quantite reellement vendue. Obligatoire pour une vente directe ; "
            "par defaut la quantite reservee sinon."
        ),
    )
    prix_unitaire = serializers.DecimalField(
        max_digits=14, decimal_places=2, min_value=Decimal("0"), required=False,
        help_text="Prix convenu. Par defaut le prix affiche de l'annonce.",
    )
    moyen_paiement = serializers.ChoiceField(
        choices=MoyenPaiement.choices, default=MoyenPaiement.CASH,
        help_text="Information declarative : aucune verification bancaire.",
    )
    note = serializers.CharField(required=False, allow_blank=True, max_length=500)

    def validate(self, attributs):
        reservation = attributs.get("reservation")
        produit = attributs.get("produit")

        if reservation is None and produit is None:
            raise serializers.ValidationError(
                {
                    "reservation": (
                        "Indiquez soit une reservation a transformer, soit un "
                        "produit et un acheteur pour une vente directe."
                    )
                }
            )
        if reservation is not None and produit is not None:
            raise serializers.ValidationError(
                {
                    "produit": (
                        "Choisissez l'un ou l'autre : une reservation porte "
                        "deja son produit."
                    )
                }
            )
        if produit is not None:
            if not attributs.get("acheteur"):
                raise serializers.ValidationError(
                    {"acheteur": "Une vente directe doit designer son acheteur."}
                )
            if not attributs.get("quantite"):
                raise serializers.ValidationError(
                    {"quantite": "Une vente directe doit preciser la quantite."}
                )
        return attributs


class MotifAnnulationSerializer(serializers.Serializer):
    """Motif obligatoire pour annuler une vente (paragraphe 8.2 du CD)."""

    motif = serializers.CharField(
        max_length=255,
        help_text=(
            "Obligatoire : une vente confirmee ne doit pas etre modifiee "
            "silencieusement, l'annulation doit etre explicable."
        ),
    )


class RevenusSerializer(serializers.Serializer):
    """Totaux renvoyes par /sales/summary/ (base du module 10)."""

    ventes_confirmees = serializers.IntegerField()
    quantite_vendue = serializers.IntegerField()
    chiffre_affaires = serializers.DecimalField(max_digits=18, decimal_places=2)
    ventes_en_attente_de_confirmation = serializers.IntegerField()
    ventes_annulees = serializers.IntegerField()
    nombre_clients = serializers.IntegerField()
