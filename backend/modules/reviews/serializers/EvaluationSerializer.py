"""Serializers du module 11.

Le client ne choisit jamais le produit ni le vendeur evalue : ils sont
deduits de la vente, ce qui rend impossible de noter un vendeur chez qui on
n'a rien achete.
"""
from rest_framework import serializers

from modules.reviews.models import (
    NOTE_MAXIMALE,
    NOTE_MINIMALE,
    Evaluation,
    MotifSignalementEvaluation,
    SignalementEvaluation,
)
from modules.sales.models import Vente


class EvaluationSerializer(serializers.ModelSerializer):
    """Lecture d'un avis, cote prive comme cote public."""

    auteur_username = serializers.CharField(source="auteur.username", read_only=True)
    auteur_photo = serializers.ImageField(source="auteur.photo", read_only=True)
    vendeur_username = serializers.CharField(source="vendeur.username", read_only=True)
    produit_titre = serializers.CharField(source="produit.titre", read_only=True)
    produit_slug = serializers.CharField(source="produit.slug", read_only=True)
    statut_libelle = serializers.CharField(source="get_statut_display", read_only=True)
    note_globale = serializers.FloatField(read_only=True)
    est_valide = serializers.BooleanField(read_only=True)

    class Meta:
        model = Evaluation
        fields = (
            "id", "vente", "produit", "produit_titre", "produit_slug",
            "auteur", "auteur_username", "auteur_photo",
            "vendeur", "vendeur_username",
            "note_produit", "note_vendeur", "note_globale", "commentaire",
            "statut", "statut_libelle", "est_valide", "motif_moderation",
            "moderee_par", "moderee_le", "modifiee_le",
            "created_at", "updated_at",
        )
        read_only_fields = fields


class EvaluationPubliqueSerializer(serializers.ModelSerializer):
    """Avis affiche sur une vitrine ou une fiche produit.

    Volontairement plus pauvre que la version privee : ni identifiant de
    vente, ni statut de moderation, ni motif. Un visiteur n'a pas a savoir
    qu'un autre avis a ete masque, ni a remonter jusqu'a une transaction.
    """

    auteur_username = serializers.CharField(source="auteur.username", read_only=True)
    auteur_photo = serializers.ImageField(source="auteur.photo", read_only=True)
    produit_titre = serializers.CharField(source="produit.titre", read_only=True)
    produit_slug = serializers.CharField(source="produit.slug", read_only=True)
    note_globale = serializers.FloatField(read_only=True)

    class Meta:
        model = Evaluation
        fields = (
            "id", "produit", "produit_titre", "produit_slug",
            "auteur_username", "auteur_photo",
            "note_produit", "note_vendeur", "note_globale", "commentaire",
            "modifiee_le", "created_at",
        )
        read_only_fields = fields


class EvaluationCreationSerializer(serializers.Serializer):
    """Depot d'un avis : POST /reviews/."""

    vente = serializers.PrimaryKeyRelatedField(
        queryset=Vente.objects.all(),
        help_text=(
            "Vente terminee a evaluer. Le produit et le vendeur en sont "
            "deduits : on ne peut pas noter un vendeur sans achat."
        ),
    )
    note_produit = serializers.IntegerField(
        min_value=NOTE_MINIMALE, max_value=NOTE_MAXIMALE,
        help_text="Qualite du produit, de 1 a 5 etoiles.",
    )
    note_vendeur = serializers.IntegerField(
        min_value=NOTE_MINIMALE, max_value=NOTE_MAXIMALE,
        help_text="Qualite du vendeur, de 1 a 5 etoiles.",
    )
    commentaire = serializers.CharField(
        required=False, allow_blank=True, max_length=2000
    )


class EvaluationModificationSerializer(serializers.Serializer):
    """Correction d'un avis : PATCH /reviews/{id}/. Tous champs optionnels."""

    note_produit = serializers.IntegerField(
        min_value=NOTE_MINIMALE, max_value=NOTE_MAXIMALE, required=False
    )
    note_vendeur = serializers.IntegerField(
        min_value=NOTE_MINIMALE, max_value=NOTE_MAXIMALE, required=False
    )
    commentaire = serializers.CharField(
        required=False, allow_blank=True, max_length=2000
    )

    def validate(self, attributs):
        if not attributs:
            raise serializers.ValidationError(
                {"detail": "Indiquez au moins un champ a modifier."}
            )
        return attributs


class SignalementEvaluationSerializer(serializers.ModelSerializer):
    """Signalement d'un avis abusif."""

    signale_par_username = serializers.CharField(
        source="signale_par.username", read_only=True
    )
    motif_libelle = serializers.CharField(source="get_motif_display", read_only=True)

    class Meta:
        model = SignalementEvaluation
        fields = (
            "id", "evaluation", "signale_par", "signale_par_username",
            "motif", "motif_libelle", "description", "traite_le", "created_at",
        )
        read_only_fields = (
            "id", "evaluation", "signale_par", "signale_par_username",
            "motif_libelle", "traite_le", "created_at",
        )


class SignalementCreationSerializer(serializers.Serializer):
    """Entree de POST /reviews/{id}/report/."""

    motif = serializers.ChoiceField(choices=MotifSignalementEvaluation.choices)
    description = serializers.CharField(required=False, allow_blank=True)


class ModerationEvaluationSerializer(serializers.Serializer):
    """Decision de moderation : POST /admin/reviews/{id}/moderate/."""

    statut = serializers.ChoiceField(
        choices=[
            ("VISIBLE", "Visible"),
            ("MASQUEE", "Masquee par la moderation"),
        ],
        help_text="MASQUEE retire l'avis des moyennes sans l'effacer.",
    )
    motif = serializers.CharField(
        required=False, allow_blank=True, max_length=255,
        help_text="Conserve : une decision de moderation doit rester explicable.",
    )


class ReputationSerializer(serializers.Serializer):
    """Notes moyennes d'un vendeur ou d'un produit."""

    note_produit = serializers.FloatField(
        allow_null=True, help_text="Moyenne des notes de produit."
    )
    note_vendeur = serializers.FloatField(
        allow_null=True, help_text="Moyenne des notes de vendeur."
    )
    nombre_evaluations = serializers.IntegerField(
        help_text="Nombre d'avis valides pris en compte."
    )


class ReputationVendeurSerializer(ReputationSerializer):
    """Reputation complete affichee sur la vitrine d'un vendeur."""

    repartition = serializers.DictField(
        child=serializers.IntegerField(),
        help_text=(
            "Nombre d'avis par note de vendeur : les cles vont de \"1\" a "
            "\"5\" et sont toujours presentes, meme a zero."
        ),
    )
