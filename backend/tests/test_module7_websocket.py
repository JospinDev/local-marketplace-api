"""Tests WebSocket du module 7.

La couche de canaux utilisee en test est `InMemoryChannelLayer` (voir
`config/settings/test.py`) : ces tests ne dependent donc pas de Redis.
En developpement et en production, c'est `channels_redis` qui transporte
les memes evenements.
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
from modules.messaging.models import Conversation, Message
from modules.products.models import Inventaire, Produit, StatutProduit

User = get_user_model()

#: Delai d'attente d'un evenement WebSocket, en secondes. Le defaut de
#: `channels` (1 s) suffit a la main mais rend ces tests fragiles quand
#: toute la suite tourne sur PostgreSQL : la machine est chargee et un
#: evenement peut arriver en un peu plus d'une seconde.
ATTENTE = 10


@override_settings(
    CHANNEL_LAYERS={"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}}
)
class BaseWebSocketTests(TransactionTestCase):
    """Prepare deux participants et une conversation.

    La couche de canaux est forcee en memoire, quelle que soit la
    configuration utilisee pour lancer les tests : le comportement du
    consumer ne depend pas du transport, et les tests n'ont pas a toucher
    au Redis de developpement (ni a subir sa latence de connexion).
    Le transport Redis lui-meme se verifie avec la commande
    `manage.py verifier_redis`.
    """

    def setUp(self):
        self.categorie = Categorie.objects.create(nom="Instruments")
        self.vendeur = User.objects.create_user(
            username="vendeur_ws", password="MotDePasse2026"
        )
        self.acheteur = User.objects.create_user(
            username="acheteur_ws", password="MotDePasse2026"
        )
        self.tiers = User.objects.create_user(
            username="tiers_ws", password="MotDePasse2026"
        )

        self.produit = Produit.objects.create(
            owner=self.vendeur, categorie=self.categorie, titre="Guitare",
            prix=Decimal("250000.00"), status=StatutProduit.ACTIVE,
        )
        Inventaire.objects.create(produit=self.produit, quantite_totale=5)

        self.conversation = Conversation.objects.create(
            acheteur=self.acheteur, vendeur=self.vendeur, produit=self.produit,
            prix_initial=self.produit.prix,
        )

        # Les jetons sont crees ici, en contexte synchrone : leur
        # generation ecrit en base (liste des tokens revocables), ce
        # qui est interdit depuis un test asynchrone.
        self.jetons = {
            utilisateur.pk: str(RefreshToken.for_user(utilisateur).access_token)
            for utilisateur in (self.acheteur, self.vendeur, self.tiers)
        }

    def jeton(self, utilisateur) -> str:
        return self.jetons[utilisateur.pk]

    def chemin(self, token=None, conversation_id=None):
        identifiant = conversation_id or self.conversation.pk
        url = f"/ws/conversations/{identifiant}/"
        return f"{url}?token={token}" if token else url

    async def _connecter(self, utilisateur=None, conversation_id=None):
        token = self.jeton(utilisateur) if utilisateur else None
        communicateur = WebsocketCommunicator(
            application, self.chemin(token, conversation_id)
        )
        connecte, _ = await communicateur.connect()
        return communicateur, connecte


class ConnexionWebSocketTests(BaseWebSocketTests):
    async def test_connexion_authentifiee_acceptee(self):
        communicateur, connecte = await self._connecter(self.acheteur)
        self.assertTrue(connecte)

        accueil = json.loads(await communicateur.receive_from(timeout=ATTENTE))
        self.assertEqual(accueil["type"], "connexion.ok")
        self.assertEqual(accueil["conversation"], self.conversation.pk)
        self.assertEqual(accueil["utilisateur"], self.acheteur.pk)

        await communicateur.disconnect()

    async def test_connexion_sans_token_refusee(self):
        """Le cahier des charges exige une connexion authentifiee."""
        communicateur, connecte = await self._connecter(None)
        self.assertFalse(connecte)
        await communicateur.disconnect()

    async def test_connexion_token_invalide_refusee(self):
        communicateur = WebsocketCommunicator(
            application, self.chemin("un.token.bidon")
        )
        connecte, _ = await communicateur.connect()
        self.assertFalse(connecte)
        await communicateur.disconnect()

    async def test_non_participant_refuse(self):
        """Verification de l'appartenance a la conversation."""
        communicateur, connecte = await self._connecter(self.tiers)
        self.assertFalse(connecte)
        await communicateur.disconnect()

    async def test_conversation_inexistante_refusee(self):
        communicateur, connecte = await self._connecter(
            self.acheteur, conversation_id=999999
        )
        self.assertFalse(connecte)
        await communicateur.disconnect()


class EchangeTempsReelTests(BaseWebSocketTests):
    async def test_message_recu_en_temps_reel_par_les_deux(self):
        """Scenario 3 du cahier des charges."""
        socket_acheteur, ok1 = await self._connecter(self.acheteur)
        socket_vendeur, ok2 = await self._connecter(self.vendeur)
        self.assertTrue(ok1)
        self.assertTrue(ok2)
        await socket_acheteur.receive_from(timeout=ATTENTE)  # connexion.ok
        await socket_vendeur.receive_from(timeout=ATTENTE)

        await socket_acheteur.send_to(
            text_data=json.dumps(
                {"type": "message", "contenu": "Bonjour, la guitare est dispo ?"}
            )
        )

        recu_vendeur = json.loads(await socket_vendeur.receive_from(timeout=ATTENTE))
        self.assertEqual(recu_vendeur["type"], "message.nouveau")
        self.assertEqual(
            recu_vendeur["message"]["contenu"], "Bonjour, la guitare est dispo ?"
        )
        self.assertEqual(recu_vendeur["message"]["expediteur"], self.acheteur.pk)

        # L'expediteur recoit aussi l'evenement : son message est confirme.
        recu_acheteur = json.loads(await socket_acheteur.receive_from(timeout=ATTENTE))
        self.assertEqual(recu_acheteur["message"]["id"], recu_vendeur["message"]["id"])

        # Et le message est bien enregistre en base.
        nombre = await database_sync_to_async(Message.objects.count)()
        self.assertEqual(nombre, 1)

        await socket_acheteur.disconnect()
        await socket_vendeur.disconnect()

    async def test_message_vide_renvoie_une_erreur(self):
        socket, _ = await self._connecter(self.acheteur)
        await socket.receive_from(timeout=ATTENTE)

        await socket.send_to(text_data=json.dumps({"type": "message", "contenu": "  "}))
        reponse = json.loads(await socket.receive_from(timeout=ATTENTE))
        self.assertEqual(reponse["type"], "erreur")

        nombre = await database_sync_to_async(Message.objects.count)()
        self.assertEqual(nombre, 0)
        await socket.disconnect()

    async def test_json_invalide_renvoie_une_erreur(self):
        socket, _ = await self._connecter(self.acheteur)
        await socket.receive_from(timeout=ATTENTE)

        await socket.send_to(text_data="ceci n'est pas du json")
        reponse = json.loads(await socket.receive_from(timeout=ATTENTE))
        self.assertEqual(reponse["type"], "erreur")
        await socket.disconnect()

    async def test_accuse_de_lecture_diffuse(self):
        socket_acheteur, _ = await self._connecter(self.acheteur)
        socket_vendeur, _ = await self._connecter(self.vendeur)
        await socket_acheteur.receive_from(timeout=ATTENTE)
        await socket_vendeur.receive_from(timeout=ATTENTE)

        await socket_acheteur.send_to(
            text_data=json.dumps({"type": "message", "contenu": "Bonjour"})
        )
        await socket_vendeur.receive_from(timeout=ATTENTE)
        await socket_acheteur.receive_from(timeout=ATTENTE)

        # Le vendeur lit : l'acheteur doit voir l'accuse de lecture.
        await socket_vendeur.send_to(text_data=json.dumps({"type": "lecture"}))

        accuse = json.loads(await socket_acheteur.receive_from(timeout=ATTENTE))
        self.assertEqual(accuse["type"], "messages.lus")
        self.assertEqual(accuse["lu_par"], self.vendeur.pk)
        self.assertEqual(len(accuse["message_ids"]), 1)

        await socket_acheteur.disconnect()
        await socket_vendeur.disconnect()

    async def test_indicateur_de_saisie(self):
        socket_acheteur, _ = await self._connecter(self.acheteur)
        socket_vendeur, _ = await self._connecter(self.vendeur)
        await socket_acheteur.receive_from(timeout=ATTENTE)
        await socket_vendeur.receive_from(timeout=ATTENTE)

        await socket_acheteur.send_to(
            text_data=json.dumps({"type": "saisie", "en_cours": True})
        )

        recu = json.loads(await socket_vendeur.receive_from(timeout=ATTENTE))
        self.assertEqual(recu["type"], "saisie")
        self.assertEqual(recu["utilisateur"], self.acheteur.pk)
        self.assertTrue(recu["en_cours"])

        # L'auteur de la saisie ne recoit pas son propre indicateur.
        self.assertTrue(await socket_acheteur.receive_nothing(timeout=0.2))

        await socket_acheteur.disconnect()
        await socket_vendeur.disconnect()

    async def test_conversation_bloquee_refuse_l_envoi(self):
        await database_sync_to_async(self.conversation.bloquer)(self.vendeur)

        socket, _ = await self._connecter(self.acheteur)
        await socket.receive_from(timeout=ATTENTE)
        await socket.send_to(
            text_data=json.dumps({"type": "message", "contenu": "Hello"})
        )
        reponse = json.loads(await socket.receive_from(timeout=ATTENTE))
        self.assertEqual(reponse["type"], "erreur")
        self.assertIn("bloquee", reponse["message"])

        nombre = await database_sync_to_async(Message.objects.count)()
        self.assertEqual(nombre, 0)
        await socket.disconnect()


class PontRestWebSocketTests(BaseWebSocketTests):
    """Un message envoye par l'API REST doit arriver sur le WebSocket."""

    async def test_message_rest_diffuse_sur_le_socket(self):
        socket, _ = await self._connecter(self.vendeur)
        await socket.receive_from(timeout=ATTENTE)

        @database_sync_to_async
        def envoyer_en_rest():
            from modules.messaging.services import MessagerieService

            return MessagerieService.envoyer_message(
                self.conversation, self.acheteur, contenu="Envoye via REST"
            )

        await envoyer_en_rest()

        recu = json.loads(await socket.receive_from(timeout=ATTENTE))
        self.assertEqual(recu["type"], "message.nouveau")
        self.assertEqual(recu["message"]["contenu"], "Envoye via REST")

        await socket.disconnect()
