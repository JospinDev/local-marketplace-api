"""Tests du module 7 : conversations, messages, blocage, signalement."""
from decimal import Decimal

from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APITestCase

from modules.categories.models import Categorie
from modules.messaging.models import (
    Conversation,
    Message,
    SignalementConversation,
)
from modules.products.models import Inventaire, Produit, StatutProduit

User = get_user_model()
URL = "/api/v1/conversations/"


class BaseMessagerieTests(APITestCase):
    def setUp(self):
        self.categorie = Categorie.objects.create(nom="Instruments de musique")
        self.vendeur = User.objects.create_user(
            username="vendeur", password="MotDePasse2026",
            nom_commercial="Boutique Taba", localisation="Taba, Mukaza",
        )
        self.acheteur = User.objects.create_user(
            username="acheteur", password="MotDePasse2026"
        )
        self.tiers = User.objects.create_user(
            username="curieux", password="MotDePasse2026"
        )

        self.produit = Produit.objects.create(
            owner=self.vendeur, categorie=self.categorie,
            titre="Guitare acoustique Yamaha", prix=Decimal("250000.00"),
            status=StatutProduit.ACTIVE, localisation="Taba, Mukaza",
        )
        Inventaire.objects.create(produit=self.produit, quantite_totale=5)

        self.client.force_authenticate(self.acheteur)

    def _ouvrir(self, message=None):
        donnees = {"produit": self.produit.pk}
        if message:
            donnees["message"] = message
        return self.client.post(URL, donnees, format="json")


class CreationConversationTests(BaseMessagerieTests):
    def test_creation_depuis_une_annonce(self):
        """Exemple du cahier des charges : le prix affiche est fige."""
        reponse = self._ouvrir()
        self.assertEqual(reponse.status_code, status.HTTP_201_CREATED, reponse.data)
        self.assertTrue(reponse.data["cree"])

        conversation = reponse.data["conversation"]
        self.assertEqual(conversation["acheteur"], self.acheteur.pk)
        self.assertEqual(conversation["vendeur"], self.vendeur.pk)
        self.assertEqual(conversation["produit"]["id"], self.produit.pk)
        self.assertEqual(Decimal(conversation["prix_initial"]), Decimal("250000.00"))
        self.assertEqual(conversation["interlocuteur"]["username"], "vendeur")

    def test_prix_initial_fige_apres_changement_de_prix(self):
        reponse = self._ouvrir()
        identifiant = reponse.data["conversation"]["id"]

        self.produit.prix = Decimal("300000.00")
        self.produit.save(update_fields=["prix"])

        detail = self.client.get(f"{URL}{identifiant}/")
        self.assertEqual(Decimal(detail.data["prix_initial"]), Decimal("250000.00"))
        self.assertEqual(
            Decimal(detail.data["prix_actuel_produit"]), Decimal("300000.00")
        )

    def test_pas_de_duplication(self):
        """Regle : une conversation ne doit pas etre dupliquee."""
        premiere = self._ouvrir()
        seconde = self._ouvrir()
        self.assertEqual(premiere.status_code, status.HTTP_201_CREATED)
        self.assertEqual(seconde.status_code, status.HTTP_200_OK)
        self.assertFalse(seconde.data["cree"])
        self.assertEqual(
            premiere.data["conversation"]["id"], seconde.data["conversation"]["id"]
        )
        self.assertEqual(Conversation.objects.count(), 1)

    def test_le_vendeur_retrouve_la_meme_conversation(self):
        """Roles inverses, meme annonce : aucune seconde conversation."""
        self._ouvrir()
        self.client.force_authenticate(self.vendeur)
        reponse = self.client.post(
            URL,
            {"produit": self.produit.pk, "interlocuteur": self.acheteur.pk},
            format="json",
        )
        self.assertEqual(reponse.status_code, status.HTTP_200_OK, reponse.data)
        self.assertEqual(Conversation.objects.count(), 1)

    def test_premier_message_a_la_creation(self):
        reponse = self._ouvrir(message="Bonjour, la guitare est-elle disponible ?")
        identifiant = reponse.data["conversation"]["id"]
        self.assertEqual(Message.objects.filter(conversation_id=identifiant).count(), 1)
        self.assertEqual(
            reponse.data["conversation"]["dernier_message"]["contenu"],
            "Bonjour, la guitare est-elle disponible ?",
        )

    def test_conversation_sans_produit(self):
        reponse = self.client.post(
            URL, {"interlocuteur": self.vendeur.pk}, format="json"
        )
        self.assertEqual(reponse.status_code, status.HTTP_201_CREATED, reponse.data)
        self.assertIsNone(reponse.data["conversation"]["produit"])
        self.assertIsNone(reponse.data["conversation"]["prix_initial"])

    def test_pas_de_conversation_avec_soi_meme(self):
        """Regle : un utilisateur ne peut pas s'envoyer de message."""
        self.client.force_authenticate(self.vendeur)
        reponse = self.client.post(
            URL,
            {"produit": self.produit.pk, "interlocuteur": self.vendeur.pk},
            format="json",
        )
        self.assertEqual(reponse.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(Conversation.objects.exists())

    def test_vendeur_doit_designer_son_acheteur(self):
        """Sur sa propre annonce, le vendeur precise qui il contacte."""
        self.client.force_authenticate(self.vendeur)
        reponse = self.client.post(
            URL, {"produit": self.produit.pk}, format="json"
        )
        self.assertEqual(reponse.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("interlocuteur", reponse.data["errors"])

    def test_roles_imposes_par_l_annonce(self):
        """Le proprietaire de l'annonce est toujours le vendeur."""
        self.client.force_authenticate(self.vendeur)
        reponse = self.client.post(
            URL,
            {
                "produit": self.produit.pk,
                "interlocuteur": self.acheteur.pk,
                "message": "Bonjour, ce produit vous interesse ?",
            },
            format="json",
        )
        self.assertEqual(reponse.status_code, status.HTTP_201_CREATED, reponse.data)
        conversation = Conversation.objects.get()
        self.assertEqual(conversation.vendeur, self.vendeur)
        self.assertEqual(conversation.acheteur, self.acheteur)

    def test_produit_non_visible_refuse(self):
        self.produit.status = StatutProduit.DRAFT
        self.produit.save(update_fields=["status"])
        reponse = self._ouvrir()
        self.assertEqual(reponse.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("produit", reponse.data["errors"])

    def test_ni_produit_ni_vendeur_refuse(self):
        reponse = self.client.post(URL, {}, format="json")
        self.assertEqual(reponse.status_code, status.HTTP_400_BAD_REQUEST)

    def test_anonyme_refuse(self):
        self.client.force_authenticate(None)
        self.assertEqual(
            self.client.post(URL, {"produit": self.produit.pk}, format="json").status_code,
            status.HTTP_401_UNAUTHORIZED,
        )

    def test_compte_suspendu_refuse(self):
        self.acheteur.suspendre("Spam")
        self.client.force_authenticate(self.acheteur)
        reponse = self._ouvrir()
        self.assertEqual(reponse.status_code, status.HTTP_403_FORBIDDEN)


class IsolationConversationTests(BaseMessagerieTests):
    """Regle : on n'accede jamais aux conversations d'autrui."""

    def setUp(self):
        super().setUp()
        self.conversation = Conversation.objects.create(
            acheteur=self.acheteur, vendeur=self.vendeur, produit=self.produit,
            prix_initial=self.produit.prix,
        )
        self.client.force_authenticate(self.tiers)

    def test_liste_ne_montre_rien_au_tiers(self):
        reponse = self.client.get(URL)
        self.assertEqual(reponse.data["count"], 0)

    def test_detail_introuvable_pour_le_tiers(self):
        reponse = self.client.get(f"{URL}{self.conversation.pk}/")
        self.assertEqual(reponse.status_code, status.HTTP_404_NOT_FOUND)

    def test_historique_introuvable_pour_le_tiers(self):
        reponse = self.client.get(f"{URL}{self.conversation.pk}/messages/")
        self.assertEqual(reponse.status_code, status.HTTP_404_NOT_FOUND)

    def test_envoi_impossible_pour_le_tiers(self):
        reponse = self.client.post(
            f"{URL}{self.conversation.pk}/messages/",
            {"contenu": "Je m'immisce"}, format="json",
        )
        self.assertEqual(reponse.status_code, status.HTTP_404_NOT_FOUND)
        self.assertFalse(Message.objects.exists())

    def test_blocage_impossible_pour_le_tiers(self):
        reponse = self.client.post(f"{URL}{self.conversation.pk}/block/")
        self.assertEqual(reponse.status_code, status.HTTP_404_NOT_FOUND)

    def test_les_deux_participants_y_accedent(self):
        for utilisateur in (self.acheteur, self.vendeur):
            self.client.force_authenticate(utilisateur)
            reponse = self.client.get(f"{URL}{self.conversation.pk}/")
            self.assertEqual(
                reponse.status_code, status.HTTP_200_OK, utilisateur.username
            )


class MessagesTests(BaseMessagerieTests):
    def setUp(self):
        super().setUp()
        self.conversation = Conversation.objects.create(
            acheteur=self.acheteur, vendeur=self.vendeur, produit=self.produit,
            prix_initial=self.produit.prix,
        )
        self.url_messages = f"{URL}{self.conversation.pk}/messages/"

    def test_envoi_et_historique(self):
        envoi = self.client.post(
            self.url_messages, {"contenu": "Bonjour"}, format="json"
        )
        self.assertEqual(envoi.status_code, status.HTTP_201_CREATED, envoi.data)
        self.assertEqual(envoi.data["contenu"], "Bonjour")
        self.assertTrue(envoi.data["est_de_moi"])
        self.assertFalse(envoi.data["est_lu"])

        self.client.force_authenticate(self.vendeur)
        self.client.post(
            self.url_messages, {"contenu": "Oui, elle est disponible"}, format="json"
        )

        historique = self.client.get(self.url_messages)
        self.assertEqual(historique.data["count"], 2)
        contenus = [m["contenu"] for m in historique.data["results"]]
        self.assertEqual(contenus, ["Bonjour", "Oui, elle est disponible"])

    def test_message_enregistre_en_base(self):
        """Regle : le message doit etre sauvegarde dans la base."""
        self.client.post(self.url_messages, {"contenu": "Test"}, format="json")
        message = Message.objects.get()
        self.assertEqual(message.contenu, "Test")
        self.assertEqual(message.expediteur, self.acheteur)
        self.assertEqual(message.conversation, self.conversation)

    def test_message_vide_refuse(self):
        reponse = self.client.post(self.url_messages, {"contenu": "   "}, format="json")
        self.assertEqual(reponse.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(Message.objects.exists())

    def test_dernier_message_le_mis_a_jour(self):
        self.assertIsNone(self.conversation.dernier_message_le)
        self.client.post(self.url_messages, {"contenu": "Bonjour"}, format="json")
        self.conversation.refresh_from_db()
        self.assertIsNotNone(self.conversation.dernier_message_le)

    def test_compteur_de_non_lus(self):
        self.client.post(self.url_messages, {"contenu": "Un"}, format="json")
        self.client.post(self.url_messages, {"contenu": "Deux"}, format="json")

        # L'expediteur n'a aucun message non lu.
        liste = self.client.get(URL)
        self.assertEqual(liste.data["results"][0]["messages_non_lus"], 0)

        # Le destinataire en a deux.
        self.client.force_authenticate(self.vendeur)
        liste = self.client.get(URL)
        self.assertEqual(liste.data["results"][0]["messages_non_lus"], 2)

        total = self.client.get(f"{URL}unread-count/")
        self.assertEqual(total.data["messages_non_lus"], 2)

    def test_marquer_comme_lu(self):
        self.client.post(self.url_messages, {"contenu": "Bonjour"}, format="json")

        self.client.force_authenticate(self.vendeur)
        reponse = self.client.post(f"{URL}{self.conversation.pk}/read/")
        self.assertEqual(reponse.status_code, status.HTTP_200_OK)
        self.assertEqual(reponse.data["messages_marques"], 1)

        message = Message.objects.get()
        self.assertIsNotNone(message.lu_le)

        # Marquer deux fois ne change rien.
        encore = self.client.post(f"{URL}{self.conversation.pk}/read/")
        self.assertEqual(encore.data["messages_marques"], 0)

    def test_marquer_lu_ne_touche_pas_ses_propres_messages(self):
        self.client.post(self.url_messages, {"contenu": "Bonjour"}, format="json")
        self.client.post(f"{URL}{self.conversation.pk}/read/")
        self.assertIsNone(Message.objects.get().lu_le)

    def test_filtre_messages_non_lus(self):
        self.client.post(self.url_messages, {"contenu": "Un"}, format="json")
        self.client.force_authenticate(self.vendeur)
        self.client.post(self.url_messages, {"contenu": "Deux"}, format="json")
        self.client.post(f"{URL}{self.conversation.pk}/read/")

        reponse = self.client.get(self.url_messages, {"non_lus": "true"})
        contenus = [m["contenu"] for m in reponse.data["results"]]
        self.assertEqual(contenus, ["Deux"])

    def test_filtre_contenu(self):
        self.client.post(self.url_messages, {"contenu": "Le prix est negociable"}, format="json")
        self.client.post(self.url_messages, {"contenu": "Merci"}, format="json")
        reponse = self.client.get(self.url_messages, {"contenu": "prix"})
        self.assertEqual(reponse.data["count"], 1)


class BlocageTests(BaseMessagerieTests):
    def setUp(self):
        super().setUp()
        self.conversation = Conversation.objects.create(
            acheteur=self.acheteur, vendeur=self.vendeur, produit=self.produit,
        )
        self.url_block = f"{URL}{self.conversation.pk}/block/"
        self.url_messages = f"{URL}{self.conversation.pk}/messages/"

    def test_bloquer_empeche_les_deux_parties_d_ecrire(self):
        reponse = self.client.post(self.url_block)
        self.assertEqual(reponse.status_code, status.HTTP_200_OK, reponse.data)
        self.assertTrue(reponse.data["est_bloquee"])

        refus = self.client.post(self.url_messages, {"contenu": "Hello"}, format="json")
        self.assertEqual(refus.status_code, status.HTTP_400_BAD_REQUEST)

        self.client.force_authenticate(self.vendeur)
        refus = self.client.post(self.url_messages, {"contenu": "Hello"}, format="json")
        self.assertEqual(refus.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(Message.objects.exists())

    def test_historique_reste_lisible_apres_blocage(self):
        self.client.post(self.url_messages, {"contenu": "Avant blocage"}, format="json")
        self.client.post(self.url_block)
        historique = self.client.get(self.url_messages)
        self.assertEqual(historique.data["count"], 1)

    def test_seul_l_auteur_du_blocage_peut_debloquer(self):
        self.client.post(self.url_block)

        self.client.force_authenticate(self.vendeur)
        refus = self.client.delete(self.url_block)
        self.assertEqual(refus.status_code, status.HTTP_403_FORBIDDEN)

        self.client.force_authenticate(self.acheteur)
        reponse = self.client.delete(self.url_block)
        self.assertEqual(reponse.status_code, status.HTTP_200_OK)
        self.assertFalse(reponse.data["est_bloquee"])

        envoi = self.client.post(self.url_messages, {"contenu": "Re"}, format="json")
        self.assertEqual(envoi.status_code, status.HTTP_201_CREATED)

    def test_double_blocage_refuse(self):
        self.client.post(self.url_block)
        reponse = self.client.post(self.url_block)
        self.assertEqual(reponse.status_code, status.HTTP_400_BAD_REQUEST)

    def test_debloquer_sans_blocage(self):
        reponse = self.client.delete(self.url_block)
        self.assertEqual(reponse.status_code, status.HTTP_400_BAD_REQUEST)


class SignalementTests(BaseMessagerieTests):
    def setUp(self):
        super().setUp()
        self.conversation = Conversation.objects.create(
            acheteur=self.acheteur, vendeur=self.vendeur, produit=self.produit,
        )
        self.url_report = f"{URL}{self.conversation.pk}/report/"

    def test_signaler_une_conversation(self):
        reponse = self.client.post(
            self.url_report,
            {"motif": "ARNAQUE", "description": "Demande un paiement a l'avance."},
            format="json",
        )
        self.assertEqual(reponse.status_code, status.HTTP_201_CREATED, reponse.data)
        signalement = SignalementConversation.objects.get()
        self.assertEqual(signalement.signale_par, self.acheteur)
        self.assertEqual(signalement.motif, "ARNAQUE")

    def test_pas_de_doublon_de_signalement(self):
        self.client.post(self.url_report, {"motif": "SPAM"}, format="json")
        reponse = self.client.post(self.url_report, {"motif": "SPAM"}, format="json")
        self.assertEqual(reponse.status_code, status.HTTP_200_OK)
        self.assertFalse(reponse.data["cree"])
        self.assertEqual(SignalementConversation.objects.count(), 1)

    def test_motif_invalide_refuse(self):
        reponse = self.client.post(
            self.url_report, {"motif": "PAS_UN_MOTIF"}, format="json"
        )
        self.assertEqual(reponse.status_code, status.HTTP_400_BAD_REQUEST)
