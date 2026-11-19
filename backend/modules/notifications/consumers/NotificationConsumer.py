"""Consumer WebSocket des notifications (module 12).

    ws://127.0.0.1:8000/ws/notifications/?token=<access>

Un seul socket par utilisateur suffit pour toute l'application : il recoit
les notifications de tous les modules. Le groupe Channels est personnel
(`notifications_<id>`), donc une notification ne peut pas partir chez
quelqu'un d'autre.

Ce canal est en LECTURE : le client ne peut pas creer de notification, il
peut seulement accuser lecture. Toute autre trame recoit une erreur.

Codes de fermeture : `4401` non authentifie, `4403` compte suspendu.
"""
import json

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer

from modules.notifications.models import Notification


class NotificationConsumer(AsyncWebsocketConsumer):
    """Flux personnel de notifications en temps reel."""

    async def connect(self):
        self.utilisateur = self.scope.get("user")

        if self.utilisateur is None or not self.utilisateur.is_authenticated:
            await self.close(code=4401)
            return

        if await self._est_suspendu():
            await self.close(code=4403)
            return

        self.groupe = Notification.groupe_de(self.utilisateur.pk)
        await self.channel_layer.group_add(self.groupe, self.channel_name)
        await self.accept()

        await self.send(
            text_data=json.dumps(
                {
                    "type": "connexion.ok",
                    "utilisateur": self.utilisateur.pk,
                    "non_lues": await self._compter_non_lues(),
                }
            )
        )

    async def disconnect(self, code):
        groupe = getattr(self, "groupe", None)
        if groupe:
            await self.channel_layer.group_discard(groupe, self.channel_name)

    async def receive(self, text_data=None, bytes_data=None):
        try:
            trame = json.loads(text_data or "{}")
        except json.JSONDecodeError:
            await self._erreur("Trame JSON invalide.")
            return

        type_trame = trame.get("type")

        if type_trame == "lecture":
            # `identifiants` absent : tout marquer comme lu.
            marquees = await self._marquer_lues(trame.get("identifiants"))
            await self.send(
                text_data=json.dumps(
                    {
                        "type": "notifications.lues",
                        "marquees": marquees,
                        "non_lues": await self._compter_non_lues(),
                    }
                )
            )
            return

        if type_trame == "compteur":
            await self.send(
                text_data=json.dumps(
                    {
                        "type": "compteur",
                        "non_lues": await self._compter_non_lues(),
                    }
                )
            )
            return

        await self._erreur(
            "Type inconnu. Ce canal accepte `lecture` et `compteur` ; les "
            "notifications sont emises par le serveur."
        )

    # ------------------------------------------------- evenements du groupe
    async def evenement_notification(self, evenement):
        """Relaie un evenement pousse par `NotificationService`."""
        await self.send(text_data=json.dumps(evenement["contenu"]))

    # --------------------------------------------------------------- interne
    async def _erreur(self, message):
        await self.send(text_data=json.dumps({"type": "erreur", "message": message}))

    @database_sync_to_async
    def _est_suspendu(self) -> bool:
        return getattr(self.utilisateur, "statut_compte", "ACTIF") == "SUSPENDU"

    @database_sync_to_async
    def _compter_non_lues(self) -> int:
        return Notification.objects.de(self.utilisateur).non_lues().count()

    @database_sync_to_async
    def _marquer_lues(self, identifiants=None) -> int:
        from modules.notifications.services import NotificationService

        return NotificationService.marquer_comme_lues(self.utilisateur, identifiants)
