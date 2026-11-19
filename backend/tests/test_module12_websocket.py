"""Tests WebSocket du module 12 : flux personnel de notifications.

Comme pour le module 7, la couche de canaux est forcee en memoire : ces
tests ne dependent pas de Redis. Le transport reel se verifie avec
`manage.py verifier_redis`.
"""
import json
from decimal import Decimal

from channels.db import database_sync_to_async
from channels.testing import WebsocketCommunicator
from django.contrib.auth import get_user_model
from django.test import TransactionTestCase, override_settings
from rest_framework_simplejwt.tokens import RefreshToken

from config.asgi import application
from modules.categories.models import Categorie
from modules.notifications.models import Notification, TypeNotification
from modules.products.models import Inventaire, Produit, StatutProduit

User = get_user_model()

#: Meme raison que pour le module 7 : le defaut de `channels` (1 s) rend
#: ces tests fragiles quand toute la suite tourne sur PostgreSQL.
ATTENTE = 10


@override_settings(
    CHANNEL_LAYERS={"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}}
)
class BaseNotificationWebSocketTests(TransactionTestCase):
    def setUp(self):
        self.categorie = Categorie.objects.create(nom="Instruments")
        self.vendeur = User.objects.create_user(
            username="vendeur_ws_notif", password="MotDePasse2026"
        )
        self.acheteur = User.objects.create_user(
            username="acheteur_ws_notif", password="MotDePasse2026"
        )
        self.produit = Produit.objects.create(
            owner=self.vendeur, categorie=self.categorie, titre="Guitare",
            prix=Decimal("250000.00"), status=StatutProduit.ACTIVE,
        )
        Inventaire.objects.create(produit=self.produit, quantite_totale=5)

        # Les jetons sont crees en contexte synchrone : leur generation
        # ecrit en base, ce qui est interdit depuis un test asynchrone.
        self.jetons = {
            utilisateur.pk: str(RefreshToken.for_user(utilisateur).access_token)
            for utilisateur in (self.acheteur, self.vendeur)
        }

    def jeton(self, utilisateur) -> str:
        return self.jetons[utilisateur.pk]

    async def _connecter(self, utilisateur=None):
        chemin = "/ws/notifications/"
        if utilisateur is not None:
            chemin = f"{chemin}?token={self.jeton(utilisateur)}"
        communicateur = WebsocketCommunicator(application, chemin)
        connecte, _ = await communicateur.connect()
        return communicateur, connecte


class ConnexionTests(BaseNotificationWebSocketTests):
    async def test_connexion_authentifiee(self):
        socket, connecte = await self._connecter(self.acheteur)
        self.assertTrue(connecte)

        accueil = json.loads(await socket.receive_from(timeout=ATTENTE))
        self.assertEqual(accueil["type"], "connexion.ok")
        self.assertEqual(accueil["utilisateur"], self.acheteur.pk)
        self.assertEqual(accueil["non_lues"], 0)

        await socket.disconnect()

    async def test_connexion_sans_jeton_refusee(self):
        socket, connecte = await self._connecter(None)
        self.assertFalse(connecte)
        await socket.disconnect()

    async def test_connexion_jeton_invalide_refusee(self):
        communicateur = WebsocketCommunicator(
            application, "/ws/notifications/?token=bidon"
        )
        connecte, _ = await communicateur.connect()
        self.assertFalse(connecte)
        await communicateur.disconnect()

    async def test_compteur_a_la_connexion(self):
        @database_sync_to_async
        def preparer():
            from modules.notifications.services import NotificationService

            for index in range(3):
                NotificationService.creer(
                    self.acheteur,
                    TypeNotification.MESSAGE_NOUVEAU,
                    f"Titre {index}",
                    "",
                )

        await preparer()
        socket, _ = await self._connecter(self.acheteur)
        accueil = json.loads(await socket.receive_from(timeout=ATTENTE))
        self.assertEqual(accueil["non_lues"], 3)
        await socket.disconnect()


class DiffusionTests(BaseNotificationWebSocketTests):
    async def test_une_notification_arrive_en_temps_reel(self):
        socket, _ = await self._connecter(self.vendeur)
        await socket.receive_from(timeout=ATTENTE)  # connexion.ok

        @database_sync_to_async
        def declencher():
            from modules.reservations.services import ReservationService

            return ReservationService.demander(self.produit, self.acheteur, 2)

        reservation = await declencher()

        recu = json.loads(await socket.receive_from(timeout=ATTENTE))
        self.assertEqual(recu["type"], "notification.nouvelle")
        self.assertEqual(
            recu["notification"]["type_notification"],
            TypeNotification.RESERVATION_DEMANDE,
        )
        self.assertEqual(recu["notification"]["reference_id"], reservation.pk)
        self.assertEqual(recu["non_lues"], 1)

        await socket.disconnect()

    async def test_une_notification_ne_part_pas_chez_autrui(self):
        """Le groupe Channels est personnel."""
        socket_acheteur, _ = await self._connecter(self.acheteur)
        await socket_acheteur.receive_from(timeout=ATTENTE)

        @database_sync_to_async
        def notifier_le_vendeur():
            from modules.notifications.services import NotificationService

            NotificationService.creer(
                self.vendeur, TypeNotification.AVIS_NOUVEAU, "Pour le vendeur", ""
            )

        await notifier_le_vendeur()
        self.assertTrue(await socket_acheteur.receive_nothing(timeout=0.5))
        await socket_acheteur.disconnect()

    async def test_accuse_de_lecture(self):
        @database_sync_to_async
        def preparer():
            from modules.notifications.services import NotificationService

            NotificationService.creer(
                self.acheteur, TypeNotification.MESSAGE_NOUVEAU, "Titre", ""
            )

        await preparer()
        socket, _ = await self._connecter(self.acheteur)
        await socket.receive_from(timeout=ATTENTE)

        await socket.send_to(text_data=json.dumps({"type": "lecture"}))

        # Deux trames arrivent : la reponse directe et la diffusion au
        # groupe (les autres appareils du meme utilisateur).
        types = set()
        for _ in range(2):
            trame = json.loads(await socket.receive_from(timeout=ATTENTE))
            types.add(trame["type"])
            self.assertEqual(trame["non_lues"], 0)
        self.assertEqual(types, {"notifications.lues"})

        restantes = await database_sync_to_async(
            lambda: Notification.objects.de(self.acheteur).non_lues().count()
        )()
        self.assertEqual(restantes, 0)
        await socket.disconnect()

    async def test_demande_de_compteur(self):
        socket, _ = await self._connecter(self.acheteur)
        await socket.receive_from(timeout=ATTENTE)

        await socket.send_to(text_data=json.dumps({"type": "compteur"}))
        trame = json.loads(await socket.receive_from(timeout=ATTENTE))
        self.assertEqual(trame["type"], "compteur")
        self.assertEqual(trame["non_lues"], 0)
        await socket.disconnect()

    async def test_type_inconnu_renvoie_une_erreur(self):
        socket, _ = await self._connecter(self.acheteur)
        await socket.receive_from(timeout=ATTENTE)

        await socket.send_to(text_data=json.dumps({"type": "creer"}))
        trame = json.loads(await socket.receive_from(timeout=ATTENTE))
        self.assertEqual(trame["type"], "erreur")
        await socket.disconnect()

    async def test_json_invalide_renvoie_une_erreur(self):
        socket, _ = await self._connecter(self.acheteur)
        await socket.receive_from(timeout=ATTENTE)

        await socket.send_to(text_data="pas du json")
        trame = json.loads(await socket.receive_from(timeout=ATTENTE))
        self.assertEqual(trame["type"], "erreur")
        await socket.disconnect()

    async def test_le_client_ne_peut_pas_creer_de_notification(self):
        """Ce canal est en lecture : on ne harcele personne par WebSocket."""
        socket, _ = await self._connecter(self.acheteur)
        await socket.receive_from(timeout=ATTENTE)

        await socket.send_to(
            text_data=json.dumps(
                {
                    "type": "notification.nouvelle",
                    "notification": {"titre": "Spam"},
                    "destinataire": self.vendeur.pk,
                }
            )
        )
        trame = json.loads(await socket.receive_from(timeout=ATTENTE))
        self.assertEqual(trame["type"], "erreur")

        total = await database_sync_to_async(Notification.objects.count)()
        self.assertEqual(total, 0)
        await socket.disconnect()
