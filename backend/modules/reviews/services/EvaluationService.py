"""Service metier des evaluations (module 11).

Toutes les regles du cahier des charges sont ici, et nulle part ailleurs :
le ViewSet prive, la vitrine publique du vendeur (module 5) et la moderation
appellent ce meme service.

Point de conception important : une evaluation n'est possible que sur une
vente TERMINEE, c'est-a-dire confirmee par le vendeur PUIS par l'acheteur.
C'est ce qui donne tout son sens au double accuse du module 9 : sans la
confirmation de l'acheteur, n'importe quel vendeur pourrait declarer une
fausse vente pour s'offrir une bonne note.
"""
from datetime import timedelta

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied

from modules.notifications.services import NotificationService
from modules.reviews.models import (
    Evaluation,
    SignalementEvaluation,
    StatutEvaluation,
)
from modules.sales.models import StatutVente, Vente


class EvaluationService:
    """Creation, modification, retrait, signalement et moderation des avis."""

    # ------------------------------------------------------------- outillage
    @staticmethod
    def delai_de_modification():
        """Duree pendant laquelle l'auteur peut encore corriger son avis.

        Modifiable depuis `/admin/settings/` (module 14), avec repli sur le
        `.env` puis sur 48 heures.
        """
        from modules.moderation.models import ParametrePlateforme

        return int(
            ParametrePlateforme.valeur_de(
                "EVALUATION_DELAI_MODIFICATION_HEURES",
                getattr(settings, "EVALUATION_DELAI_MODIFICATION_HEURES", 48),
            )
        )

    @staticmethod
    def _produit_de_la_vente(vente: Vente):
        """Produit evalue : celui de la vente (une vente = une annonce ici)."""
        ligne = vente.lignes.select_related("produit").first()
        if ligne is None:
            raise serializers.ValidationError(
                {"vente": "Cette vente ne contient aucune ligne : rien a evaluer."}
            )
        return ligne.produit

    # --------------------------------------------------------------- creation
    @staticmethod
    @transaction.atomic
    def creer(
        vente: Vente,
        auteur,
        note_produit: int,
        note_vendeur: int,
        commentaire: str = "",
    ) -> Evaluation:
        """Depose un avis sur une vente terminee."""
        # Seul l'acheteur evalue : c'est lui qui a recu le produit.
        if vente.acheteur_id != auteur.pk:
            if vente.vendeur_id == auteur.pk:
                raise PermissionDenied(
                    "Un vendeur n'evalue pas sa propre vente. Seul l'acheteur "
                    "peut noter le produit et le vendeur."
                )
            raise PermissionDenied("Cette vente ne vous concerne pas.")

        if vente.statut != StatutVente.COMPLETED:
            raise serializers.ValidationError(
                {
                    "vente": (
                        "Seule une vente terminee peut etre evaluee. Confirmez "
                        "d'abord la reception du produit avec "
                        "/sales/{id}/buyer-confirmation/ "
                        f"(statut actuel : {vente.statut})."
                    )
                }
            )

        produit = EvaluationService._produit_de_la_vente(vente)
        if produit.owner_id == auteur.pk:
            raise serializers.ValidationError(
                {"vente": "Vous ne pouvez pas evaluer votre propre produit."}
            )

        try:
            evaluation = Evaluation.objects.create(
                vente=vente,
                auteur=auteur,
                produit=produit,
                vendeur=vente.vendeur,
                note_produit=note_produit,
                note_vendeur=note_vendeur,
                commentaire=commentaire,
            )
        except IntegrityError as exc:
            # Contrainte `evaluation_unique_par_vente`.
            raise serializers.ValidationError(
                {
                    "vente": (
                        "Vous avez deja evalue cette vente. Vous pouvez "
                        "modifier votre avis existant."
                    )
                }
            ) from exc

        # Module 12 : le vendeur est prevenu du nouveau commentaire.
        NotificationService.avis_recu(evaluation)
        return evaluation

    # ----------------------------------------------------------- modification
    @staticmethod
    @transaction.atomic
    def modifier(evaluation: Evaluation, auteur, donnees: dict) -> Evaluation:
        """Corrige son propre avis, dans le delai autorise.

        Regle retenue pour "modifier un avis selon les regles" : l'auteur
        garde la main pendant `EVALUATION_DELAI_MODIFICATION_HEURES`. Passe
        ce delai, l'avis est fige : une reputation ne doit pas pouvoir etre
        reecrite des mois plus tard, par exemple sous la pression du vendeur.
        Un avis masque par la moderation n'est plus modifiable non plus.
        """
        if evaluation.auteur_id != auteur.pk:
            raise PermissionDenied("Vous ne pouvez modifier que vos propres avis.")
        if evaluation.statut == StatutEvaluation.MASQUEE:
            raise serializers.ValidationError(
                {
                    "statut": (
                        "Cet avis a ete masque par la moderation : il n'est "
                        "plus modifiable."
                    )
                }
            )

        heures = EvaluationService.delai_de_modification()
        limite = evaluation.created_at + timedelta(hours=heures)
        if timezone.now() > limite:
            raise serializers.ValidationError(
                {
                    "detail": (
                        f"Le delai de modification de {heures} heures est "
                        "depasse : cet avis est desormais definitif."
                    )
                }
            )

        champs = []
        for champ in ("note_produit", "note_vendeur", "commentaire"):
            if champ in donnees:
                setattr(evaluation, champ, donnees[champ])
                champs.append(champ)

        if not champs:
            return evaluation

        # Un avis retire puis corrige redevient visible.
        if evaluation.statut == StatutEvaluation.RETIREE:
            evaluation.statut = StatutEvaluation.VISIBLE
            champs.append("statut")

        evaluation.modifiee_le = timezone.now()
        champs += ["modifiee_le", "updated_at"]
        evaluation.save(update_fields=champs)
        return evaluation

    # ---------------------------------------------------------------- retrait
    @staticmethod
    @transaction.atomic
    def retirer(evaluation: Evaluation, auteur) -> Evaluation:
        """Retrait par l'auteur : suppression douce.

        L'avis sort des moyennes et des listes publiques mais reste en base.
        Le cahier des charges demande de "supprimer OU masquer selon les
        regles" : effacer une ligne rendrait l'historique d'une reputation
        invérifiable, et un vendeur pourrait faire disparaitre un mauvais
        avis en obtenant son retrait.
        """
        if evaluation.auteur_id != auteur.pk:
            raise PermissionDenied("Vous ne pouvez retirer que vos propres avis.")
        if evaluation.statut == StatutEvaluation.MASQUEE:
            raise serializers.ValidationError(
                {"statut": "Cet avis est deja masque par la moderation."}
            )

        evaluation.statut = StatutEvaluation.RETIREE
        evaluation.save(update_fields=["statut", "updated_at"])
        return evaluation

    # ------------------------------------------------------------ signalement
    @staticmethod
    @transaction.atomic
    def signaler(
        evaluation: Evaluation, utilisateur, motif: str, description: str = ""
    ) -> SignalementEvaluation:
        """Signale un avis abusif a la moderation.

        Ouvert a tous les utilisateurs connectes, et pas seulement au vendeur
        concerne : un avis insultant nuit a toute la plateforme. L'auteur de
        l'avis, lui, n'a rien a signaler.
        """
        if evaluation.auteur_id == utilisateur.pk:
            raise serializers.ValidationError(
                {"detail": "Vous ne pouvez pas signaler votre propre avis."}
            )

        try:
            signalement = SignalementEvaluation.objects.create(
                evaluation=evaluation,
                signale_par=utilisateur,
                motif=motif,
                description=description,
            )
        except IntegrityError as exc:
            raise serializers.ValidationError(
                {
                    "detail": (
                        "Vous avez deja signale cet avis : la moderation "
                        "n'a pas encore traite votre signalement."
                    )
                }
            ) from exc
        return signalement

    # -------------------------------------------------------------- moderation
    @staticmethod
    @transaction.atomic
    def moderer(evaluation: Evaluation, moderateur, statut: str, motif: str = ""):
        """Decision de moderation (groupe disposant de `change_evaluation`).

        Masquer un avis le retire des moyennes sans l'effacer. Le motif est
        conserve : une decision de moderation doit rester explicable.
        """
        if statut not in StatutEvaluation.values:
            raise serializers.ValidationError(
                {"statut": f"Statut inconnu : {statut}."}
            )

        evaluation.statut = statut
        evaluation.motif_moderation = motif
        evaluation.moderee_par = moderateur
        evaluation.moderee_le = timezone.now()
        evaluation.save(
            update_fields=[
                "statut", "motif_moderation", "moderee_par", "moderee_le",
                "updated_at",
            ]
        )

        # Les signalements de cet avis sont consideres comme traites.
        evaluation.signalements.filter(traite_le__isnull=True).update(
            traite_le=timezone.now()
        )
        return evaluation

    # ------------------------------------------------------------ statistiques
    @staticmethod
    def statistiques_vendeur(vendeur) -> dict:
        """Reputation d'un vendeur, pour la vitrine publique (module 5)."""
        queryset = Evaluation.objects.recues_par(vendeur)
        donnees = queryset.moyennes()
        donnees["repartition"] = queryset.repartition()
        return donnees

    @staticmethod
    def statistiques_produit(produit) -> dict:
        """Note d'un produit, pour la fiche publique (module 4)."""
        return Evaluation.objects.du_produit(produit).moyennes()
