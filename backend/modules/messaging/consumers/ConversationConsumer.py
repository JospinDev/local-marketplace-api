"""Consumer WebSocket d'une conversation : `/ws/conversations/{id}/`.

Securite, conforme au cahier des charges : la connexion est refusee si le
client n'est pas authentifie, si la conversation n'existe pas, ou si
l'utilisateur n'en est pas un participant.

Les messages ne sont jamais acceptes "tels quels" : ils passent par
`MessagerieService`, le meme point d'entree que l'API REST, donc ils sont
enregistres en base avec les memes controles (blocage, contenu non vide).
"""
import json

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer
from rest_framework import serializers

CODE_NON_AUTHENTIFIE = 4401
CODE_INTERDIT = 4403
CODE_INTROUVABLE = 4404


class ConversationConsumer(AsyncWebsocketConsumer):
    """Temps reel d'une conversation : nouveaux messages et accuses de lecture."""

    async def connect(self):
        self.utilisateur = self.scope.get("user")
        self.conversation_id = self.scope["url_route"]["kwargs"]["conversation_id"]

        if self.utilisateur is None or not self.utilisateur.is_authenticated:
            await self.close(code=CODE_NON_AUTHENTIFIE)
            return

        if getattr(self.utilisateur, "statut_compte", "ACTIF") == "SUSPENDU":
            await self.close(code=CODE_INTERDIT)
            return

        self.conversation = await self._charger_conversation()
        if self.conversation is None:
            await self.close(code=CODE_INTROUVABLE)
            return

        if not await self._est_participant():
            # L'utilisateur n'a rien a faire dans cette conversation.
            await self.close(code=CODE_INTERDIT)
            return

        self.nom_groupe = f"conversation_{self.conversation_id}"
        await self.channel_layer.group_add(self.nom_groupe, self.channel_name)
        await self.accept()

        await self.send(
            text_data=json.dumps(
                {
                    "type": "connexion.ok",
                    "conversation": int(self.conversation_id),
                    "utilisateur": self.utilisateur.pk,
                }
            )
        )

    async def disconnect(self, code):
        nom_groupe = getattr(self, "nom_groupe", None)
        if nom_groupe:
            await self.channel_layer.group_discard(nom_groupe, self.channel_name)

    async def receive(self, text_data=None, bytes_data=None):
        """Recoit un message du client.

        Formats acceptes :
          {"type": "message", "contenu": "Bonjour"}
          {"type": "lecture"}        -> marque les messages recus comme lus
          {"type": "saisie", "en_cours": true}
        """
        try:
            donnees = json.loads(text_data or "{}")
        except json.JSONDecodeError:
            await self._erreur("Format JSON invalide.")
            return

        type_evenement = donnees.get("type", "message")

        if type_evenement == "message":
            contenu = (donnees.get("contenu") or "").strip()
            if not contenu:
                await self._erreur("Un message doit contenir du texte.")
                return
            try:
                # Le service enregistre en base ET diffuse au groupe : il n'y
                # a donc rien a renvoyer ici, l'evenement reviendra par le
                # groupe, y compris a l'expediteur.
                await self._enregistrer_message(contenu)
            except serializers.ValidationError as exc:
                await self._erreur(self._premier_message_erreur(exc))
            return

        if type_evenement == "lecture":
            await self._marquer_lus()
            return

        if type_evenement == "saisie":
            await self.channel_layer.group_send(
                self.nom_groupe,
                {
                    "type": "evenement.messagerie",
                    "contenu": {
                        "type": "saisie",
                        "utilisateur": self.utilisateur.pk,
                        "username": self.utilisateur.username,
                        "en_cours": bool(donnees.get("en_cours", True)),
                    },
                },
            )
            return

        await self._erreur(f"Type d'evenement inconnu : {type_evenement}")

    # ------------------------------------------------------ diffusion groupe
    async def evenement_messagerie(self, evenement):
        """Relaie au client un evenement diffuse dans le groupe."""
        contenu = evenement.get("contenu", {})
        # L'indicateur de saisie ne revient pas a son propre auteur.
        if (
            contenu.get("type") == "saisie"
            and contenu.get("utilisateur") == self.utilisateur.pk
        ):
            return
        await self.send(text_data=json.dumps(contenu))

    async def _erreur(self, message: str):
        await self.send(
            text_data=json.dumps({"type": "erreur", "message": message})
        )

    @staticmethod
    def _premier_message_erreur(exc) -> str:
        detail = exc.detail
        if isinstance(detail, dict):
            premiere = next(iter(detail.values()))
            if isinstance(premiere, (list, tuple)) and premiere:
                return str(premiere[0])
            return str(premiere)
        if isinstance(detail, (list, tuple)) and detail:
            return str(detail[0])
        return str(detail)

    # --------------------------------------------------------- acces base
    @database_sync_to_async
    def _charger_conversation(self):
        from modules.messaging.models import Conversation

        return Conversation.objects.filter(pk=self.conversation_id).first()

    @database_sync_to_async
    def _est_participant(self):
        return self.conversation.est_participant(self.utilisateur)

    @database_sync_to_async
    def _enregistrer_message(self, contenu):
        from modules.messaging.services import MessagerieService

        return MessagerieService.envoyer_message(
            self.conversation, self.utilisateur, contenu=contenu
        )

    @database_sync_to_async
    def _marquer_lus(self):
        from modules.messaging.services import MessagerieService

        return MessagerieService.marquer_comme_lus(self.conversation, self.utilisateur)
