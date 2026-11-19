"""Service metier de la messagerie.

Point important : ce service est le SEUL endroit qui cree une conversation ou
un message. L'API REST et le consumer WebSocket l'appellent tous les deux, ce
qui garantit que les memes regles s'appliquent (participants, blocage,
enregistrement en base) et qu'un message envoye en REST est bien diffuse aux
sockets ouverts, et inversement.
"""
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework import serializers

from modules.messaging.models import Conversation, Message


class MessagerieService:
    """Creation de conversations, envoi de messages, accuses de lecture."""

    # ------------------------------------------------------- conversations
    @staticmethod
    @transaction.atomic
    def obtenir_ou_creer_conversation(acheteur, vendeur, produit=None):
        """Retourne la conversation existante ou la cree.

        Evite les doublons pour un meme trio acheteur / vendeur / produit,
        et fige le prix affiche au demarrage de la discussion.
        """
        if acheteur == vendeur:
            raise serializers.ValidationError(
                {"vendeur": "Vous ne pouvez pas vous envoyer de message a vous-meme."}
            )

        # Si les roles sont inverses (le vendeur recontacte l'acheteur sur la
        # meme annonce), on reutilise la conversation deja ouverte.
        existante = (
            Conversation.objects.filter(produit=produit)
            .filter(
                acheteur__in=[acheteur, vendeur], vendeur__in=[acheteur, vendeur]
            )
            .first()
        )
        if existante is not None:
            return existante, False

        try:
            conversation = Conversation.objects.create(
                acheteur=acheteur,
                vendeur=vendeur,
                produit=produit,
                prix_initial=produit.prix if produit is not None else None,
            )
        except IntegrityError:
            # Course entre deux requetes simultanees : on relit l'existante.
            conversation = (
                Conversation.objects.filter(produit=produit)
                .filter(
                    acheteur__in=[acheteur, vendeur],
                    vendeur__in=[acheteur, vendeur],
                )
                .first()
            )
            if conversation is None:
                raise
            return conversation, False

        return conversation, True

    # ------------------------------------------------------------ messages
    @staticmethod
    @transaction.atomic
    def envoyer_message(conversation, expediteur, contenu="", image=None):
        """Enregistre un message puis le diffuse aux sockets de la conversation."""
        if not conversation.est_participant(expediteur):
            raise serializers.ValidationError(
                {"detail": "Vous ne participez pas a cette conversation."}
            )

        if conversation.est_bloquee:
            raise serializers.ValidationError(
                {
                    "detail": (
                        "Cette conversation est bloquee : aucun message ne peut "
                        "y etre envoye."
                    )
                }
            )

        contenu = (contenu or "").strip()
        if not contenu and image is None:
            raise serializers.ValidationError(
                {"contenu": "Un message doit contenir du texte ou une image."}
            )

        message = Message.objects.create(
            conversation=conversation,
            expediteur=expediteur,
            contenu=contenu,
            image=image,
        )

        conversation.dernier_message_le = message.created_at
        conversation.save(update_fields=["dernier_message_le", "updated_at"])

        MessagerieService.diffuser(
            conversation,
            {
                "type": "message.nouveau",
                "message": MessagerieService.serialiser_message(message),
            },
        )

        # Module 12 : l'interlocuteur est prevenu meme s'il est hors ligne.
        # Import local : le module des notifications importe la messagerie
        # pour serialiser ses evenements, un import global ferait un cycle.
        from modules.notifications.services import NotificationService

        NotificationService.message_recu(message)
        return message

    @staticmethod
    @transaction.atomic
    def marquer_comme_lus(conversation, utilisateur):
        """Marque comme lus les messages recus par cet utilisateur."""
        maintenant = timezone.now()
        identifiants = list(
            conversation.messages.non_lus_pour(utilisateur).values_list(
                "id", flat=True
            )
        )
        if not identifiants:
            return 0

        Message.objects.filter(id__in=identifiants).update(lu_le=maintenant)

        MessagerieService.diffuser(
            conversation,
            {
                "type": "messages.lus",
                "lu_par": utilisateur.pk,
                "lu_par_username": utilisateur.username,
                "message_ids": identifiants,
                "lu_le": maintenant.isoformat(),
            },
        )
        return len(identifiants)

    # ------------------------------------------------------------ diffusion
    @staticmethod
    def serialiser_message(message) -> dict:
        """Charge utile envoyee sur le WebSocket."""
        return {
            "id": message.pk,
            "conversation": message.conversation_id,
            "expediteur": message.expediteur_id,
            "expediteur_username": message.expediteur.username,
            "contenu": message.contenu,
            "image": message.image.url if message.image else None,
            "est_lu": message.est_lu,
            "lu_le": message.lu_le.isoformat() if message.lu_le else None,
            "created_at": message.created_at.isoformat(),
        }

    @staticmethod
    def diffuser(conversation, evenement: dict):
        """Envoie un evenement au groupe Channels de la conversation.

        Le temps reel est un confort : si la couche de transport est
        indisponible, l'operation metier reste valide puisque le message est
        deja enregistre en base.
        """
        couche = get_channel_layer()
        if couche is None:
            return
        try:
            async_to_sync(couche.group_send)(
                conversation.nom_groupe,
                {"type": "evenement.messagerie", "contenu": evenement},
            )
        except Exception:  # Redis indisponible, par exemple.
            import logging

            logging.getLogger(__name__).warning(
                "Diffusion temps reel impossible pour la conversation %s",
                conversation.pk,
                exc_info=True,
            )
