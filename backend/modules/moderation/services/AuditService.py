"""Journal d'audit (module 14).

Comme les notifications, une trace d'audit ne doit jamais faire echouer
l'action qu'elle documente : un administrateur ne doit pas se retrouver
incapable de suspendre un compte abusif parce que la table d'audit est
indisponible. L'echec est donc journalise, pas propage.

La difference avec les notifications : ici, perdre une trace est GRAVE.
C'est pourquoi l'echec est enregistre en `error` et non en `warning`.
"""
import logging

from django.db import transaction

from modules.moderation.models import ActionAudit, JournalAudit

logger = logging.getLogger(__name__)


class AuditService:
    """Ecriture du journal d'audit."""

    @staticmethod
    def tracer(
        acteur,
        action: str,
        cible=None,
        cible_type: str = "",
        cible_libelle: str = "",
        motif: str = "",
        avant=None,
        apres=None,
        requete=None,
    ):
        """Enregistre une decision d'administration.

        `avant` et `apres` sont libres : un dictionnaire de champs, une
        valeur simple, un statut. Ils servent a comprendre la decision des
        mois plus tard, pas a rejouer une transaction.
        """
        try:
            donnees = {}
            if avant is not None:
                donnees["avant"] = avant
            if apres is not None:
                donnees["apres"] = apres

            # Point de sauvegarde, pour la meme raison que les
            # notifications : `tracer` est appele depuis l'interieur des
            # vues d'administration, parfois dans une transaction. Sans ce
            # savepoint, une erreur de base rattrapee ici laisserait la
            # transaction de l'appelant inutilisable et ferait echouer
            # l'action administrative elle-meme.
            with transaction.atomic():
                return JournalAudit.objects.create(
                    acteur=acteur if getattr(acteur, "pk", None) else None,
                    acteur_username=getattr(acteur, "username", "") or "",
                    action=action,
                    cible_type=(cible_type or AuditService._type_de(cible))[:30],
                    cible_id=getattr(cible, "pk", None),
                    cible_libelle=(
                        (cible_libelle or str(cible))[:255] if cible else ""
                    ),
                    motif=(motif or "")[:500],
                    donnees=donnees,
                    adresse_ip=AuditService.adresse_ip(requete),
                )
        except Exception:
            logger.error(
                "Trace d'audit non enregistree : action=%s cible=%s",
                action,
                getattr(cible, "pk", None),
                exc_info=True,
            )
            return None

    # ------------------------------------------------------------- outillage
    @staticmethod
    def _type_de(cible) -> str:
        if cible is None:
            return ""
        return cible._meta.model_name

    @staticmethod
    def adresse_ip(requete):
        """Adresse du client, en tenant compte d'un eventuel proxy.

        `X-Forwarded-For` est fourni par le client et donc falsifiable : on
        ne s'en sert qu'a titre indicatif dans le journal, jamais pour une
        decision de securite.
        """
        if requete is None:
            return None
        entete = requete.META.get("HTTP_X_FORWARDED_FOR", "")
        if entete:
            return entete.split(",")[0].strip() or None
        return requete.META.get("REMOTE_ADDR") or None

    # -------------------------------------------------- raccourcis metier
    @staticmethod
    def suspension(acteur, utilisateur, motif, requete=None):
        return AuditService.tracer(
            acteur,
            ActionAudit.SUSPENSION_COMPTE,
            cible=utilisateur,
            cible_type="utilisateur",
            cible_libelle=utilisateur.username,
            motif=motif,
            avant={"statut_compte": "ACTIF"},
            apres={"statut_compte": utilisateur.statut_compte},
            requete=requete,
        )

    @staticmethod
    def reactivation(acteur, utilisateur, requete=None):
        return AuditService.tracer(
            acteur,
            ActionAudit.REACTIVATION_COMPTE,
            cible=utilisateur,
            cible_type="utilisateur",
            cible_libelle=utilisateur.username,
            apres={"statut_compte": utilisateur.statut_compte},
            requete=requete,
        )

    @staticmethod
    def moderation_annonce(acteur, produit, statut_avant, motif, requete=None):
        return AuditService.tracer(
            acteur,
            ActionAudit.MODERATION_ANNONCE,
            cible=produit,
            cible_type="produit",
            cible_libelle=produit.titre,
            motif=motif,
            avant={"status": statut_avant},
            apres={"status": produit.status},
            requete=requete,
        )

    @staticmethod
    def suppression_annonce(acteur, produit, requete=None):
        return AuditService.tracer(
            acteur,
            ActionAudit.SUPPRESSION_ANNONCE,
            cible=produit,
            cible_type="produit",
            cible_libelle=produit.titre,
            avant={"status": produit.status, "owner": produit.owner.username},
            requete=requete,
        )

    @staticmethod
    def moderation_avis(acteur, evaluation, statut_avant, motif, requete=None):
        return AuditService.tracer(
            acteur,
            ActionAudit.MODERATION_AVIS,
            cible=evaluation,
            cible_type="evaluation",
            cible_libelle=f"avis de {evaluation.auteur.username}",
            motif=motif,
            avant={"statut": statut_avant},
            apres={"statut": evaluation.statut},
            requete=requete,
        )

    @staticmethod
    def traitement_signalement(acteur, signalement, genre: str, requete=None):
        return AuditService.tracer(
            acteur,
            ActionAudit.TRAITEMENT_SIGNALEMENT,
            cible=signalement,
            cible_type=f"signalement_{genre}",
            cible_libelle=f"signalement {signalement.pk} ({signalement.motif})",
            apres={"traite_le": str(signalement.traite_le)},
            requete=requete,
        )

    @staticmethod
    def modification_parametre(acteur, parametre, valeur_avant, requete=None):
        return AuditService.tracer(
            acteur,
            ActionAudit.MODIFICATION_PARAMETRE,
            cible=parametre,
            cible_type="parametre",
            cible_libelle=parametre.cle,
            avant={"valeur": valeur_avant},
            apres={"valeur": parametre.valeur},
            requete=requete,
        )
