"""Serializers du module 14."""
from rest_framework import serializers

from modules.moderation.models import (
    ActionAudit,
    JournalAudit,
    ParametrePlateforme,
    TypeValeurParametre,
)
from modules.products.models import MouvementStock


class MouvementStockSerializer(serializers.ModelSerializer):
    """Une variation de quantite, avec sa raison et son auteur.

    Expose la photographie du stock apres l'operation : l'historique se
    relit sans rien recalculer, ce qui est exactement ce dont on a besoin
    devant un litige.
    """

    type_libelle = serializers.CharField(
        source="get_type_mouvement_display", read_only=True
    )
    produit_titre = serializers.CharField(source="produit.titre", read_only=True)
    vendeur_username = serializers.CharField(
        source="produit.owner.username", read_only=True
    )
    effectue_par_username = serializers.CharField(
        source="effectue_par.username", read_only=True, default=""
    )
    quantite_disponible_apres = serializers.IntegerField(read_only=True)

    class Meta:
        model = MouvementStock
        fields = (
            "id", "produit", "produit_titre", "vendeur_username",
            "type_mouvement", "type_libelle", "quantite",
            "reference_type", "reference_id",
            "effectue_par", "effectue_par_username", "commentaire",
            "quantite_totale_apres", "quantite_reservee_apres",
            "quantite_vendue_apres", "quantite_disponible_apres",
            "created_at",
        )
        read_only_fields = fields


class JournalAuditSerializer(serializers.ModelSerializer):
    """Entree du journal d'audit, en lecture seule."""

    action_libelle = serializers.CharField(source="get_action_display", read_only=True)

    class Meta:
        model = JournalAudit
        fields = (
            "id", "acteur", "acteur_username", "action", "action_libelle",
            "cible_type", "cible_id", "cible_libelle", "motif", "donnees",
            "adresse_ip", "created_at",
        )
        read_only_fields = fields


class ParametrePlateformeSerializer(serializers.ModelSerializer):
    """Parametre de la plateforme."""

    valeur_typee = serializers.SerializerMethodField()
    modifie_par_username = serializers.CharField(
        source="modifie_par.username", read_only=True, default=""
    )

    class Meta:
        model = ParametrePlateforme
        fields = (
            "id", "cle", "valeur", "valeur_typee", "type_valeur",
            "description", "modifie_par", "modifie_par_username",
            "created_at", "updated_at",
        )
        read_only_fields = (
            "id", "valeur_typee", "modifie_par", "modifie_par_username",
            "created_at", "updated_at",
        )

    def get_valeur_typee(self, obj) -> str:
        """Valeur convertie, rendue en texte pour rester typable en JSON."""
        valeur = obj.valeur_typee
        return "" if valeur is None else str(valeur)

    def validate(self, attributs):
        """Une valeur doit etre convertible dans le type annonce."""
        type_valeur = attributs.get(
            "type_valeur",
            getattr(self.instance, "type_valeur", TypeValeurParametre.TEXTE),
        )
        valeur = attributs.get("valeur", getattr(self.instance, "valeur", ""))

        if ParametrePlateforme._convertir(valeur, type_valeur) is None:
            raise serializers.ValidationError(
                {
                    "valeur": (
                        f"Valeur incompatible avec le type {type_valeur} : "
                        "le reglage serait ignore au profit de la valeur "
                        "par defaut du serveur."
                    )
                }
            )
        return attributs


class ClesConnuesSerializer(serializers.Serializer):
    """Catalogue des parametres que le code sait lire."""

    cle = serializers.CharField()
    type_valeur = serializers.CharField()
    description = serializers.CharField()
    valeur_active = serializers.CharField(
        help_text="Valeur reellement utilisee : base de donnees, sinon `.env`."
    )
    definie_en_base = serializers.BooleanField()


# ---------------------------------------------------------------- statistiques
class StatistiquesUtilisateursSerializer(serializers.Serializer):
    total = serializers.IntegerField()
    actifs = serializers.IntegerField()
    suspendus = serializers.IntegerField()
    email_verifie = serializers.IntegerField()
    inscrits_ce_mois = serializers.IntegerField()
    vendeurs = serializers.IntegerField(
        help_text="Comptes ayant au moins une annonce visible."
    )


class StatistiquesAnnoncesSerializer(serializers.Serializer):
    total = serializers.IntegerField()
    par_statut = serializers.DictField(child=serializers.IntegerField())
    visibles = serializers.IntegerField()
    mises_en_avant = serializers.IntegerField()
    vues_cumulees = serializers.IntegerField()


class StatistiquesReservationsSerializer(serializers.Serializer):
    total = serializers.IntegerField()
    en_attente = serializers.IntegerField()
    acceptees = serializers.IntegerField()
    annulees = serializers.IntegerField()
    expirees = serializers.IntegerField()
    transformees = serializers.IntegerField()
    taux_de_transformation = serializers.FloatField(allow_null=True)


class StatistiquesVentesSerializer(serializers.Serializer):
    total = serializers.IntegerField()
    statut_initiated = serializers.IntegerField()
    statut_paid = serializers.IntegerField()
    statut_completed = serializers.IntegerField()
    statut_cancelled = serializers.IntegerField()
    statut_refunded = serializers.IntegerField()
    ventes_comptabilisees = serializers.IntegerField()
    chiffre_affaires = serializers.DecimalField(max_digits=20, decimal_places=2)
    quantite_vendue = serializers.IntegerField()
    panier_moyen = serializers.DecimalField(max_digits=20, decimal_places=2)
    devise = serializers.CharField()


class StatistiquesMessagerieSerializer(serializers.Serializer):
    conversations = serializers.IntegerField()
    messages = serializers.IntegerField()
    conversations_bloquees = serializers.IntegerField()


class StatistiquesEvaluationsSerializer(serializers.Serializer):
    total = serializers.IntegerField()
    visibles = serializers.IntegerField()
    masquees = serializers.IntegerField()
    retirees = serializers.IntegerField()
    note_produit_moyenne = serializers.FloatField(allow_null=True)
    note_vendeur_moyenne = serializers.FloatField(allow_null=True)


class StatistiquesModerationSerializer(serializers.Serializer):
    signalements_conversations_en_attente = serializers.IntegerField()
    signalements_avis_en_attente = serializers.IntegerField()
    annonces_en_attente_de_moderation = serializers.IntegerField()
    annonces_retirees = serializers.IntegerField()


class StatistiquesGlobalesSerializer(serializers.Serializer):
    """Sortie de GET /admin/statistics/."""

    utilisateurs = StatistiquesUtilisateursSerializer()
    annonces = StatistiquesAnnoncesSerializer()
    reservations = StatistiquesReservationsSerializer()
    ventes = StatistiquesVentesSerializer()
    messagerie = StatistiquesMessagerieSerializer()
    evaluations = StatistiquesEvaluationsSerializer()
    moderation = StatistiquesModerationSerializer()
    genere_le = serializers.DateTimeField()


# ---------------------------------------------------------------- signalements
class ResumeSignalementsSerializer(serializers.Serializer):
    """Sortie de GET /admin/reports/."""

    conversations_en_attente = serializers.IntegerField()
    avis_en_attente = serializers.IntegerField()
    conversations_traitees = serializers.IntegerField()
    avis_traites = serializers.IntegerField()


class ActionAuditSerializer(serializers.Serializer):
    """Liste des actions tracables, pour alimenter un filtre cote client."""

    valeur = serializers.CharField()
    libelle = serializers.CharField()

    @staticmethod
    def toutes():
        return [
            {"valeur": valeur, "libelle": libelle}
            for valeur, libelle in ActionAudit.choices
        ]
