"""Service des notifications (module 12).

Deux principes, qui expliquent tout le fichier :

1. **Une notification ne doit jamais faire echouer l'operation qui la
   declenche.** Accepter une reservation doit reussir meme si Redis est
   tombe, si la table des notifications est verrouillee ou si le service
   push repond 500. Chaque emetteur d'evenement est donc enveloppe par
   `_sans_casser`, qui journalise et laisse passer.

2. **La notification interne est la source de verite.** Le WebSocket et le
   push ne sont que des transports. Si les deux echouent, l'utilisateur
   retrouve tout dans `GET /notifications/`.

Le revers de la premiere regle est qu'une notification perdue est
silencieuse pour l'appelant : c'est pourquoi les echecs sont journalises en
`warning` avec la trace complete, et non ignores.
"""
import logging

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from modules.notifications.models import Notification, TypeNotification
from modules.notifications.services.PushService import PushService

logger = logging.getLogger(__name__)


def _sans_casser(fonction):
    """Rend un emetteur de notification incapable de casser son appelant."""

    def enveloppe(*args, **kwargs):
        try:
            return fonction(*args, **kwargs)
        except Exception:
            logger.warning(
                "Notification non emise par %s", fonction.__name__, exc_info=True
            )
            return None

    enveloppe.__name__ = fonction.__name__
    enveloppe.__doc__ = fonction.__doc__
    return enveloppe


class NotificationService:
    """Creation, diffusion et lecture des notifications."""

    # ------------------------------------------------------------- creation
    @staticmethod
    def creer(
        destinataire,
        type_notification: str,
        titre: str,
        message: str = "",
        reference_type: str = "",
        reference_id=None,
        donnees: dict | None = None,
        declencheur=None,
        meme_si_inactif: bool = False,
    ):
        """Enregistre une notification et la transmet.

        `declencheur` evite l'absurdite la plus courante : se notifier
        soi-meme de sa propre action.

        Un compte desactive ne recoit rien, pour ne pas accumuler des
        notifications que personne ne lira. `meme_si_inactif` leve cette
        regle, et il le faut : la suspension d'un compte met justement
        `is_active` a faux, et c'est precisement l'avis que l'interesse
        doit trouver en revenant.
        """
        if destinataire is None or not getattr(destinataire, "pk", None):
            return None
        if declencheur is not None and declencheur.pk == destinataire.pk:
            return None
        if not destinataire.is_active and not meme_si_inactif:
            return None

        # L'ecriture se fait dans un POINT DE SAUVEGARDE. Ces emetteurs sont
        # appeles depuis l'interieur des transactions metier (accepter une
        # reservation, envoyer un message) : sans ce savepoint, une erreur
        # de base dans la notification marquerait toute la transaction comme
        # cassee et ferait echouer l'operation elle-meme, exactement ce que
        # le module doit garantir de ne jamais provoquer. Avec le savepoint,
        # l'echec est annule tout seul et la transaction reste utilisable.
        try:
            with transaction.atomic():
                notification = Notification.objects.create(
                    destinataire=destinataire,
                    type_notification=type_notification,
                    titre=titre,
                    message=message,
                    reference_type=reference_type,
                    reference_id=reference_id,
                    donnees=donnees or {},
                )
        except Exception:
            logger.warning(
                "Notification non enregistree pour %s (%s)",
                destinataire.pk,
                type_notification,
                exc_info=True,
            )
            return None

        NotificationService.transmettre(notification)
        return notification

    @staticmethod
    def creer_si_absente(destinataire, type_notification, titre, **extra):
        """Ne cree pas de doublon tant que la precedente n'est pas lue.

        Utile pour les alertes repetitives comme "produit presque epuise" :
        chaque vente ferait sinon sonner le telephone du vendeur. Une fois
        l'alerte lue, une nouvelle peut repartir.
        """
        reference_type = extra.get("reference_type", "")
        reference_id = extra.get("reference_id")
        existe = (
            Notification.objects.de(destinataire)
            .non_lues()
            .filter(
                type_notification=type_notification,
                reference_type=reference_type,
                reference_id=reference_id,
            )
            .exists()
        )
        if existe:
            return None
        return NotificationService.creer(
            destinataire, type_notification, titre, **extra
        )

    # ------------------------------------------------------------ transports
    @staticmethod
    def transmettre(notification) -> None:
        """Pousse la notification sur les transports, sans jamais lever."""
        try:
            NotificationService.diffuser(notification)
        except Exception:
            logger.warning("Diffusion impossible", exc_info=True)
        try:
            PushService.envoyer(notification)
        except Exception:
            logger.warning("Push impossible", exc_info=True)

    @staticmethod
    def diffuser(notification) -> None:
        """Envoie la notification au groupe Channels personnel du destinataire.

        Meme garantie que la messagerie du module 7 : le temps reel est un
        confort, la notification est deja en base.
        """
        couche = get_channel_layer()
        if couche is None:
            return
        try:
            async_to_sync(couche.group_send)(
                notification.nom_groupe,
                {
                    "type": "evenement.notification",
                    "contenu": {
                        "type": "notification.nouvelle",
                        "notification": NotificationService.serialiser(notification),
                        "non_lues": NotificationService.compter_non_lues(
                            notification.destinataire
                        ),
                    },
                },
            )
        except Exception:
            logger.warning(
                "Diffusion temps reel impossible pour la notification %s",
                notification.pk,
                exc_info=True,
            )

    @staticmethod
    def serialiser(notification) -> dict:
        """Forme envoyee sur le WebSocket, identique a celle de l'API REST."""
        from modules.notifications.serializers import NotificationSerializer

        return NotificationSerializer(notification).data

    # --------------------------------------------------------------- lecture
    @staticmethod
    def compter_non_lues(utilisateur) -> int:
        return Notification.objects.de(utilisateur).non_lues().count()

    @staticmethod
    def marquer_comme_lues(utilisateur, identifiants=None) -> int:
        """Marque tout, ou seulement les identifiants fournis."""
        queryset = Notification.objects.de(utilisateur).non_lues()
        if identifiants:
            queryset = queryset.filter(pk__in=identifiants)
        nombre = queryset.update(lu_le=timezone.now())

        if nombre:
            NotificationService._diffuser_compteur(utilisateur)
        return nombre

    @staticmethod
    def _diffuser_compteur(utilisateur) -> None:
        """Previent les autres appareils que le compteur a change."""
        couche = get_channel_layer()
        if couche is None:
            return
        try:
            async_to_sync(couche.group_send)(
                Notification.groupe_de(utilisateur.pk),
                {
                    "type": "evenement.notification",
                    "contenu": {
                        "type": "notifications.lues",
                        "non_lues": NotificationService.compter_non_lues(utilisateur),
                    },
                },
            )
        except Exception:
            logger.warning("Diffusion du compteur impossible", exc_info=True)

    # =====================================================================
    # Emetteurs d'evenements : un par ligne du cahier des charges.
    # Tous sont enveloppes : leur echec n'affecte jamais l'operation metier.
    # =====================================================================

    # --------------------------------------------------------- messagerie
    @staticmethod
    @_sans_casser
    def message_recu(message):
        """Nouveau message, pour l'interlocuteur (acheteur ou vendeur)."""
        conversation = message.conversation
        destinataire = conversation.interlocuteur_de(message.expediteur)
        apercu = message.contenu or "[image]"
        return NotificationService.creer(
            destinataire,
            TypeNotification.MESSAGE_NOUVEAU,
            titre=f"Message de {message.expediteur.username}",
            message=apercu[:200],
            reference_type="conversation",
            reference_id=conversation.pk,
            donnees={"message_id": message.pk},
            declencheur=message.expediteur,
        )

    # -------------------------------------------------------- reservations
    @staticmethod
    @_sans_casser
    def reservation_demandee(reservation):
        """Nouvelle demande de reservation, pour le vendeur."""
        return NotificationService.creer(
            reservation.vendeur,
            TypeNotification.RESERVATION_DEMANDE,
            titre="Nouvelle demande de reservation",
            message=(
                f"{reservation.acheteur.username} demande "
                f"{reservation.quantite_demandee} x {reservation.produit.titre}."
            ),
            reference_type="reservation",
            reference_id=reservation.pk,
            donnees={"produit_id": reservation.produit_id},
            declencheur=reservation.acheteur,
        )

    @staticmethod
    @_sans_casser
    def reservation_acceptee(reservation):
        """Reservation acceptee, pour l'acheteur."""
        return NotificationService.creer(
            reservation.acheteur,
            TypeNotification.RESERVATION_ACCEPTEE,
            titre="Reservation acceptee",
            message=(
                f"{reservation.quantite_confirmee} x {reservation.produit.titre} "
                "mis de cote pour vous. A retirer avant le "
                f"{timezone.localtime(reservation.expire_le):%d/%m/%Y a %Hh%M}."
            ),
            reference_type="reservation",
            reference_id=reservation.pk,
            donnees={"produit_id": reservation.produit_id},
            declencheur=reservation.vendeur,
        )

    @staticmethod
    @_sans_casser
    def reservation_refusee(reservation):
        """Demande refusee, pour l'acheteur."""
        return NotificationService.creer(
            reservation.acheteur,
            TypeNotification.RESERVATION_REFUSEE,
            titre="Demande de reservation refusee",
            message=(
                f"{reservation.produit.titre} : {reservation.motif}"
                if reservation.motif
                else f"Votre demande sur {reservation.produit.titre} a ete refusee."
            ),
            reference_type="reservation",
            reference_id=reservation.pk,
            declencheur=reservation.vendeur,
        )

    @staticmethod
    @_sans_casser
    def reservation_annulee(reservation, par_qui):
        """Annulation, pour celle des deux parties qui ne l'a pas demandee."""
        destinataire = (
            reservation.vendeur
            if par_qui.pk == reservation.acheteur_id
            else reservation.acheteur
        )
        return NotificationService.creer(
            destinataire,
            TypeNotification.RESERVATION_ANNULEE,
            titre="Reservation annulee",
            message=(
                f"{reservation.produit.titre} : annulation par "
                f"{par_qui.username}."
                + (f" Motif : {reservation.motif}" if reservation.motif else "")
            ),
            reference_type="reservation",
            reference_id=reservation.pk,
            declencheur=par_qui,
        )

    @staticmethod
    @_sans_casser
    def reservation_expiree(reservation):
        """Expiration : les DEUX parties sont concernees.

        L'acheteur perd sa reservation ; le vendeur recupere son stock et
        doit le savoir pour le revendre.
        """
        creees = []
        for destinataire, titre, message in (
            (
                reservation.acheteur,
                "Reservation expiree",
                f"Le delai de retrait de {reservation.produit.titre} est depasse.",
            ),
            (
                reservation.vendeur,
                "Reservation expiree",
                (
                    f"La reservation de {reservation.acheteur.username} a expire : "
                    f"{reservation.quantite_confirmee or reservation.quantite_demandee} "
                    f"x {reservation.produit.titre} sont de nouveau disponibles."
                ),
            ),
        ):
            notification = NotificationService.creer(
                destinataire,
                TypeNotification.RESERVATION_EXPIREE,
                titre=titre,
                message=message,
                reference_type="reservation",
                reference_id=reservation.pk,
            )
            if notification is not None:
                creees.append(notification)
        return creees

    # --------------------------------------------------------------- ventes
    @staticmethod
    @_sans_casser
    def achat_confirme(vente):
        """Confirmation de reception par le client, pour le vendeur."""
        return NotificationService.creer(
            vente.vendeur,
            TypeNotification.ACHAT_CONFIRME,
            titre="Achat confirme par le client",
            message=(
                f"{vente.acheteur.username} a confirme la reception "
                f"({vente.montant_total} {vente.devise})."
            ),
            reference_type="vente",
            reference_id=vente.pk,
            declencheur=vente.acheteur,
        )

    # ----------------------------------------------------------- evaluations
    @staticmethod
    @_sans_casser
    def avis_recu(evaluation):
        """Nouveau commentaire, pour le vendeur."""
        return NotificationService.creer(
            evaluation.vendeur,
            TypeNotification.AVIS_NOUVEAU,
            titre=f"Nouvel avis : {evaluation.note_vendeur}/5",
            message=(
                evaluation.commentaire[:200]
                if evaluation.commentaire
                else f"{evaluation.produit.titre} a recu une note sans commentaire."
            ),
            reference_type="evaluation",
            reference_id=evaluation.pk,
            donnees={
                "produit_id": evaluation.produit_id,
                "note_produit": evaluation.note_produit,
                "note_vendeur": evaluation.note_vendeur,
            },
            declencheur=evaluation.auteur,
        )

    # ---------------------------------------------------------------- stock
    @staticmethod
    @_sans_casser
    def stock_epuise(produit):
        """Rupture de stock, pour le vendeur."""
        return NotificationService.creer_si_absente(
            produit.owner,
            TypeNotification.STOCK_EPUISE,
            titre="Produit en rupture de stock",
            message=(
                f"{produit.titre} n'a plus aucune quantite disponible. "
                "Mettez votre stock a jour pour le remettre en vente."
            ),
            reference_type="produit",
            reference_id=produit.pk,
        )

    @staticmethod
    @_sans_casser
    def stock_presque_epuise(produit, disponible: int):
        """Alerte de stock faible, pour le vendeur."""
        return NotificationService.creer_si_absente(
            produit.owner,
            TypeNotification.STOCK_PRESQUE_EPUISE,
            titre="Produit presque epuise",
            message=(
                f"{produit.titre} : il ne reste que {disponible} unite(s) "
                "disponible(s)."
            ),
            reference_type="produit",
            reference_id=produit.pk,
            donnees={"quantite_disponible": disponible},
        )

    # -------------------------------------------------------------- favoris
    @staticmethod
    @_sans_casser
    def favori_indisponible(produit):
        """Un favori n'est plus disponible, pour ceux qui l'ont sauvegarde."""
        from modules.favorites.models import Favori

        favoris = Favori.objects.filter(produit=produit).select_related("utilisateur")
        creees = []
        for favori in favoris:
            if favori.utilisateur_id == produit.owner_id:
                continue
            notification = NotificationService.creer_si_absente(
                favori.utilisateur,
                TypeNotification.FAVORI_INDISPONIBLE,
                titre="Un favori n'est plus disponible",
                message=f"{produit.titre} n'est plus disponible pour le moment.",
                reference_type="produit",
                reference_id=produit.pk,
            )
            if notification is not None:
                creees.append(notification)
        return creees

    # ------------------------------------------------------ vendeurs suivis
    @staticmethod
    @_sans_casser
    def nouvelle_annonce_de_vendeur_suivi(produit):
        """Nouvelle publication d'un vendeur suivi, pour ses abonnes."""
        from modules.sellers.models import AbonnementVendeur

        abonnements = AbonnementVendeur.objects.filter(
            vendeur=produit.owner
        ).select_related("abonne")
        creees = []
        for abonnement in abonnements:
            notification = NotificationService.creer(
                abonnement.abonne,
                TypeNotification.VENDEUR_NOUVELLE_ANNONCE,
                titre=f"Nouvelle annonce de {produit.owner.username}",
                message=f"{produit.titre} - {produit.prix} {produit.devise}",
                reference_type="produit",
                reference_id=produit.pk,
                declencheur=produit.owner,
            )
            if notification is not None:
                creees.append(notification)
        return creees

    # ------------------------------------------------------- administration
    @staticmethod
    @_sans_casser
    def compte_suspendu(utilisateur, motif: str = ""):
        return NotificationService.creer(
            utilisateur,
            TypeNotification.COMPTE_SUSPENDU,
            titre="Votre compte est suspendu",
            message=motif or "Contactez l'administration pour en savoir plus.",
            reference_type="utilisateur",
            reference_id=utilisateur.pk,
            # La suspension desactive le compte : sans cela, l'interesse ne
            # serait jamais informe de la decision prise a son sujet.
            meme_si_inactif=True,
        )

    @staticmethod
    @_sans_casser
    def compte_reactive(utilisateur):
        return NotificationService.creer(
            utilisateur,
            TypeNotification.COMPTE_REACTIVE,
            titre="Votre compte est reactive",
            message="Vous pouvez de nouveau publier et contacter les vendeurs.",
            reference_type="utilisateur",
            reference_id=utilisateur.pk,
        )

    @staticmethod
    @_sans_casser
    def annonce_moderee(produit, motif: str = ""):
        return NotificationService.creer(
            produit.owner,
            TypeNotification.ANNONCE_MODEREE,
            titre=f"Annonce moderee : {produit.titre}",
            message=motif or f"Nouveau statut : {produit.status}.",
            reference_type="produit",
            reference_id=produit.pk,
            donnees={"statut": produit.status},
        )

    @staticmethod
    @_sans_casser
    def avis_modere(evaluation, motif: str = ""):
        return NotificationService.creer(
            evaluation.auteur,
            TypeNotification.AVIS_MODERE,
            titre="Votre avis a ete modere",
            message=motif or f"Nouveau statut : {evaluation.statut}.",
            reference_type="evaluation",
            reference_id=evaluation.pk,
        )

    # ------------------------------------------------------------ outillage
    @staticmethod
    def seuil_de_stock_faible() -> int:
        """Seuil configurable de l'alerte "produit presque epuise".

        Modifiable depuis `/admin/settings/` (module 14), avec repli sur le
        `.env` puis sur 3 unites.
        """
        from modules.moderation.models import ParametrePlateforme

        return int(
            ParametrePlateforme.valeur_de(
                "STOCK_SEUIL_ALERTE", getattr(settings, "STOCK_SEUIL_ALERTE", 3)
            )
        )
