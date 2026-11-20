"""Tests du module 12 : notifications internes, temps reel et push.

Deux exigences du cahier des charges structurent ces tests :

- chaque evenement de sa liste produit bien une notification ;
- une notification ne doit JAMAIS faire echouer l'operation qui la
  declenche (classe `RobustesseTests`).
"""
from datetime import timedelta
from decimal import Decimal
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import override_settings
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from modules.categories.models import Categorie
from modules.favorites.models import Favori
from modules.messaging.models import Conversation
from modules.messaging.services import MessagerieService
from modules.notifications.models import (
    AppareilPush,
    Notification,
    TypeNotification,
)
from modules.notifications.services import NotificationService, PushService
from modules.products.models import Inventaire, Produit, StatutProduit
from modules.products.services import ProduitStatutService
from modules.reservations.models import Reservation
from modules.reservations.services import ReservationService
from modules.reviews.services import EvaluationService
from modules.sales.services import VenteService
from modules.sellers.models import AbonnementVendeur

User = get_user_model()
URL = "/api/v1/notifications/"


class BaseNotificationTests(APITestCase):
    def setUp(self):
        self.categorie = Categorie.objects.create(nom="Electronique")
        self.vendeur = User.objects.create_user(
            username="vendeur", password="MotDePasse2026"
        )
        self.acheteur = User.objects.create_user(
            username="acheteur", password="MotDePasse2026"
        )
        self.tiers = User.objects.create_user(
            username="tiers", password="MotDePasse2026"
        )
        self.produit = self._creer("Telephone", "450000", quantite=10)
        self.client.force_authenticate(self.acheteur)

    def _creer(self, titre, prix, quantite=10, statut=StatutProduit.ACTIVE, owner=None):
        produit = Produit.objects.create(
            owner=owner or self.vendeur, categorie=self.categorie, titre=titre,
            prix=Decimal(prix), status=statut, localisation="Rohero",
        )
        Inventaire.objects.create(produit=produit, quantite_totale=quantite)
        return produit

    def _notifications(self, utilisateur, type_notification=None):
        queryset = Notification.objects.de(utilisateur)
        if type_notification:
            queryset = queryset.filter(type_notification=type_notification)
        return queryset

    def _vente_terminee(self, acheteur=None, produit=None, quantite=1):
        acheteur = acheteur or self.acheteur
        vente = VenteService.enregistrer_vente_directe(
            produit or self.produit, self.vendeur, acheteur, quantite
        )
        VenteService.confirmer_paiement(vente, self.vendeur)
        VenteService.confirmer_reception(vente, acheteur)
        return vente


class EvenementsMessagerieTests(BaseNotificationTests):
    def test_nouveau_message_notifie_l_interlocuteur(self):
        conversation = Conversation.objects.create(
            acheteur=self.acheteur, vendeur=self.vendeur, produit=self.produit,
            prix_initial=self.produit.prix,
        )
        MessagerieService.envoyer_message(
            conversation, self.acheteur, contenu="Bonjour, c'est disponible ?"
        )

        notification = self._notifications(
            self.vendeur, TypeNotification.MESSAGE_NOUVEAU
        ).get()
        self.assertIn("acheteur", notification.titre)
        self.assertEqual(notification.message, "Bonjour, c'est disponible ?")
        self.assertEqual(notification.reference_type, "conversation")
        self.assertEqual(notification.reference_id, conversation.pk)

        # L'expediteur ne se notifie pas lui-meme.
        self.assertEqual(self._notifications(self.acheteur).count(), 0)


class EvenementsReservationTests(BaseNotificationTests):
    def test_demande_notifie_le_vendeur(self):
        reservation = ReservationService.demander(self.produit, self.acheteur, 3)
        notification = self._notifications(
            self.vendeur, TypeNotification.RESERVATION_DEMANDE
        ).get()
        self.assertEqual(notification.reference_id, reservation.pk)
        self.assertIn("3", notification.message)
        self.assertEqual(self._notifications(self.acheteur).count(), 0)

    def test_acceptation_notifie_l_acheteur(self):
        reservation = ReservationService.demander(self.produit, self.acheteur, 2)
        ReservationService.accepter(reservation, self.vendeur)

        notification = self._notifications(
            self.acheteur, TypeNotification.RESERVATION_ACCEPTEE
        ).get()
        self.assertIn("2", notification.message)

    def test_refus_notifie_l_acheteur_avec_le_motif(self):
        reservation = ReservationService.demander(self.produit, self.acheteur, 1)
        ReservationService.refuser(reservation, self.vendeur, "Plus en stock")

        notification = self._notifications(
            self.acheteur, TypeNotification.RESERVATION_REFUSEE
        ).get()
        self.assertIn("Plus en stock", notification.message)

    def test_annulation_notifie_seulement_l_autre_partie(self):
        reservation = ReservationService.accepter(
            ReservationService.demander(self.produit, self.acheteur, 2), self.vendeur
        )
        ReservationService.annuler(reservation, self.acheteur, "Je ne viens plus")

        # Le vendeur est prevenu...
        self.assertEqual(
            self._notifications(
                self.vendeur, TypeNotification.RESERVATION_ANNULEE
            ).count(),
            1,
        )
        # ... l'acheteur, qui a annule, ne l'est pas.
        self.assertEqual(
            self._notifications(
                self.acheteur, TypeNotification.RESERVATION_ANNULEE
            ).count(),
            0,
        )

    def test_expiration_notifie_les_deux_parties(self):
        """L'acheteur perd sa reservation, le vendeur recupere son stock."""
        reservation = ReservationService.accepter(
            ReservationService.demander(self.produit, self.acheteur, 4), self.vendeur
        )
        Reservation.objects.filter(pk=reservation.pk).update(
            expire_le=timezone.now() - timedelta(hours=1)
        )
        ReservationService.expirer_les_depassees()

        for utilisateur in (self.acheteur, self.vendeur):
            self.assertEqual(
                self._notifications(
                    utilisateur, TypeNotification.RESERVATION_EXPIREE
                ).count(),
                1,
                utilisateur.username,
            )


class EvenementsVenteEtAvisTests(BaseNotificationTests):
    def test_confirmation_de_reception_notifie_le_vendeur(self):
        vente = VenteService.enregistrer_vente_directe(
            self.produit, self.vendeur, self.acheteur, 1
        )
        VenteService.confirmer_paiement(vente, self.vendeur)
        VenteService.confirmer_reception(vente, self.acheteur)

        notification = self._notifications(
            self.vendeur, TypeNotification.ACHAT_CONFIRME
        ).get()
        self.assertEqual(notification.reference_id, vente.pk)

    def test_nouvel_avis_notifie_le_vendeur(self):
        vente = self._vente_terminee()
        Notification.objects.all().delete()

        evaluation = EvaluationService.creer(
            vente, self.acheteur, note_produit=5, note_vendeur=4,
            commentaire="Tres bon vendeur",
        )
        notification = self._notifications(
            self.vendeur, TypeNotification.AVIS_NOUVEAU
        ).get()
        self.assertIn("4/5", notification.titre)
        self.assertEqual(notification.message, "Tres bon vendeur")
        self.assertEqual(notification.reference_id, evaluation.pk)


class EvenementsStockTests(BaseNotificationTests):
    def test_rupture_de_stock_notifie_le_vendeur(self):
        produit = self._creer("Derniere piece", "1000", quantite=1)
        VenteService.enregistrer_vente_directe(
            produit, self.vendeur, self.acheteur, 1
        )
        notification = self._notifications(
            self.vendeur, TypeNotification.STOCK_EPUISE
        ).get()
        self.assertEqual(notification.reference_id, produit.pk)

    @override_settings(STOCK_SEUIL_ALERTE=3)
    def test_stock_faible_notifie_le_vendeur(self):
        produit = self._creer("Bientot fini", "1000", quantite=5)
        VenteService.enregistrer_vente_directe(
            produit, self.vendeur, self.acheteur, 3
        )
        notification = self._notifications(
            self.vendeur, TypeNotification.STOCK_PRESQUE_EPUISE
        ).get()
        self.assertIn("2", notification.message)

    @override_settings(STOCK_SEUIL_ALERTE=3)
    def test_pas_de_doublon_tant_que_l_alerte_n_est_pas_lue(self):
        """Sinon chaque vente ferait sonner le telephone du vendeur."""
        produit = self._creer("Bientot fini", "1000", quantite=5)
        VenteService.enregistrer_vente_directe(
            produit, self.vendeur, self.acheteur, 2
        )
        VenteService.enregistrer_vente_directe(
            produit, self.vendeur, self.tiers, 1
        )
        self.assertEqual(
            self._notifications(
                self.vendeur, TypeNotification.STOCK_PRESQUE_EPUISE
            ).count(),
            1,
        )

    @override_settings(STOCK_SEUIL_ALERTE=3)
    def test_une_nouvelle_alerte_apres_lecture(self):
        produit = self._creer("Bientot fini", "1000", quantite=5)
        VenteService.enregistrer_vente_directe(
            produit, self.vendeur, self.acheteur, 2
        )
        NotificationService.marquer_comme_lues(self.vendeur)
        VenteService.enregistrer_vente_directe(
            produit, self.vendeur, self.tiers, 1
        )
        self.assertEqual(
            self._notifications(
                self.vendeur, TypeNotification.STOCK_PRESQUE_EPUISE
            ).count(),
            2,
        )

    def test_un_brouillon_ne_declenche_aucune_alerte(self):
        """Prevenir qu'un brouillon est epuise n'aurait aucun sens."""
        brouillon = self._creer(
            "Brouillon", "1000", quantite=1, statut=StatutProduit.DRAFT
        )
        ProduitStatutService.synchroniser_statut_stock(brouillon)
        self.assertEqual(self._notifications(self.vendeur).count(), 0)

    def test_favori_indisponible(self):
        produit = self._creer("Convoite", "1000", quantite=1)
        Favori.objects.create(
            utilisateur=self.tiers, produit=produit, prix_a_l_ajout=produit.prix
        )
        VenteService.enregistrer_vente_directe(
            produit, self.vendeur, self.acheteur, 1
        )
        notification = self._notifications(
            self.tiers, TypeNotification.FAVORI_INDISPONIBLE
        ).get()
        self.assertEqual(notification.reference_id, produit.pk)


class EvenementsVendeurSuiviTests(BaseNotificationTests):
    def test_nouvelle_annonce_notifie_les_abonnes(self):
        AbonnementVendeur.objects.create(abonne=self.acheteur, vendeur=self.vendeur)
        nouvelle = self._creer(
            "Nouveaute", "70000", quantite=3, statut=StatutProduit.DRAFT
        )
        ProduitStatutService.publier(nouvelle)

        notification = self._notifications(
            self.acheteur, TypeNotification.VENDEUR_NOUVELLE_ANNONCE
        ).get()
        self.assertEqual(notification.reference_id, nouvelle.pk)
        self.assertIn("Nouveaute", notification.message)

    def test_republication_ne_renotifie_pas(self):
        """Une annonce mise en pause puis republiee ne resonne pas."""
        AbonnementVendeur.objects.create(abonne=self.acheteur, vendeur=self.vendeur)
        nouvelle = self._creer(
            "Nouveaute", "70000", quantite=3, statut=StatutProduit.DRAFT
        )
        ProduitStatutService.publier(nouvelle)
        ProduitStatutService.mettre_en_pause(nouvelle)
        ProduitStatutService.publier(nouvelle)

        self.assertEqual(
            self._notifications(
                self.acheteur, TypeNotification.VENDEUR_NOUVELLE_ANNONCE
            ).count(),
            1,
        )

    def test_sans_abonne_aucune_notification(self):
        nouvelle = self._creer(
            "Discrete", "1000", quantite=1, statut=StatutProduit.DRAFT
        )
        ProduitStatutService.publier(nouvelle)
        self.assertEqual(Notification.objects.count(), 0)


class ApiNotificationTests(BaseNotificationTests):
    def setUp(self):
        super().setUp()
        self.premiere = NotificationService.creer(
            self.acheteur, TypeNotification.MESSAGE_NOUVEAU, "Premier", "Bonjour"
        )
        self.seconde = NotificationService.creer(
            self.acheteur,
            TypeNotification.RESERVATION_ACCEPTEE,
            "Second",
            "Accepte",
            reference_type="reservation",
            reference_id=42,
        )
        NotificationService.creer(
            self.tiers, TypeNotification.MESSAGE_NOUVEAU, "Pas pour vous", ""
        )

    def test_liste_privee(self):
        reponse = self.client.get(URL)
        self.assertEqual(reponse.status_code, status.HTTP_200_OK)
        identifiants = {ligne["id"] for ligne in reponse.data["results"]}
        self.assertEqual(identifiants, {self.premiere.pk, self.seconde.pk})

    def test_notification_d_autrui_invisible(self):
        autre = Notification.objects.de(self.tiers).get()
        self.assertEqual(
            self.client.get(f"{URL}{autre.pk}/").status_code,
            status.HTTP_404_NOT_FOUND,
        )

    def test_compteur_non_lues(self):
        reponse = self.client.get(f"{URL}unread-count/")
        self.assertEqual(reponse.data["non_lues"], 2)

    def test_marquer_tout_comme_lu(self):
        reponse = self.client.post(f"{URL}read/", {}, format="json")
        self.assertEqual(reponse.status_code, status.HTTP_200_OK, reponse.data)
        self.assertEqual(reponse.data["marquees"], 2)
        self.assertEqual(reponse.data["non_lues"], 0)
        # Les notifications d'autrui ne sont pas touchees.
        self.assertEqual(
            Notification.objects.de(self.tiers).non_lues().count(), 1
        )

    def test_marquer_une_selection(self):
        reponse = self.client.post(
            f"{URL}read/", {"identifiants": [self.premiere.pk]}, format="json"
        )
        self.assertEqual(reponse.data["marquees"], 1)
        self.assertEqual(reponse.data["non_lues"], 1)

    def test_marquer_une_notification(self):
        reponse = self.client.post(f"{URL}{self.seconde.pk}/read/", {}, format="json")
        self.assertEqual(reponse.status_code, status.HTTP_200_OK)
        self.assertTrue(reponse.data["est_lue"])

    def test_marquer_une_notification_d_autrui_impossible(self):
        autre = Notification.objects.de(self.tiers).get()
        reponse = self.client.post(f"{URL}{autre.pk}/read/", {}, format="json")
        self.assertEqual(reponse.status_code, status.HTTP_404_NOT_FOUND)
        autre.refresh_from_db()
        self.assertIsNone(autre.lu_le)

    def test_supprimer_une_notification(self):
        reponse = self.client.delete(f"{URL}{self.premiere.pk}/")
        self.assertEqual(reponse.status_code, status.HTTP_204_NO_CONTENT)
        self.assertEqual(Notification.objects.de(self.acheteur).count(), 1)

    def test_filtre_non_lues(self):
        self.premiere.marquer_comme_lue()
        reponse = self.client.get(f"{URL}?non_lues=true")
        identifiants = [ligne["id"] for ligne in reponse.data["results"]]
        self.assertEqual(identifiants, [self.seconde.pk])

    def test_filtre_type(self):
        reponse = self.client.get(f"{URL}?type_notification=RESERVATION_ACCEPTEE")
        identifiants = [ligne["id"] for ligne in reponse.data["results"]]
        self.assertEqual(identifiants, [self.seconde.pk])

    def test_filtre_reference(self):
        reponse = self.client.get(f"{URL}?reference_type=reservation&reference_id=42")
        identifiants = [ligne["id"] for ligne in reponse.data["results"]]
        self.assertEqual(identifiants, [self.seconde.pk])

    def test_aucune_creation_par_l_api(self):
        """On ne doit pas pouvoir notifier quelqu'un depuis l'API."""
        reponse = self.client.post(
            URL,
            {"destinataire": self.tiers.pk, "titre": "Spam", "message": "Achetez"},
            format="json",
        )
        self.assertEqual(reponse.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

    def test_anonyme_refuse(self):
        self.client.force_authenticate(None)
        self.assertEqual(
            self.client.get(URL).status_code, status.HTTP_401_UNAUTHORIZED
        )


class AppareilsPushTests(BaseNotificationTests):
    def test_enregistrer_un_appareil(self):
        reponse = self.client.post(
            f"{URL}devices/",
            {"jeton": "jeton-abc", "plateforme": "ANDROID", "libelle": "Mon telephone"},
            format="json",
        )
        self.assertEqual(reponse.status_code, status.HTTP_201_CREATED, reponse.data)
        appareil = AppareilPush.objects.get()
        self.assertEqual(appareil.utilisateur, self.acheteur)
        self.assertTrue(appareil.actif)

    def test_enregistrement_idempotent(self):
        donnees = {"jeton": "jeton-abc", "plateforme": "ANDROID"}
        self.client.post(f"{URL}devices/", donnees, format="json")
        reponse = self.client.post(
            f"{URL}devices/", {**donnees, "libelle": "Renomme"}, format="json"
        )
        self.assertEqual(reponse.status_code, status.HTTP_200_OK)
        self.assertFalse(reponse.data["cree"])
        self.assertEqual(AppareilPush.objects.count(), 1)
        self.assertEqual(AppareilPush.objects.get().libelle, "Renomme")

    def test_lister_mes_appareils(self):
        self.client.post(
            f"{URL}devices/",
            {"jeton": "a-moi", "plateforme": "IOS"},
            format="json",
        )
        AppareilPush.objects.create(
            utilisateur=self.tiers, jeton="a-lui", plateforme="WEB"
        )
        reponse = self.client.get(f"{URL}devices/")
        jetons = [ligne["jeton"] for ligne in reponse.data]
        self.assertEqual(jetons, ["a-moi"])

    def test_desinscrire_un_appareil(self):
        self.client.post(
            f"{URL}devices/", {"jeton": "jeton-abc", "plateforme": "WEB"},
            format="json",
        )
        reponse = self.client.delete(f"{URL}devices/jeton-abc/")
        self.assertEqual(reponse.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(AppareilPush.objects.exists())

    def test_desinscrire_un_jeton_inconnu(self):
        reponse = self.client.delete(f"{URL}devices/inconnu/")
        self.assertEqual(reponse.status_code, status.HTTP_404_NOT_FOUND)

    def test_etat_du_push_sans_configuration(self):
        """Le client doit savoir si le push est operationnel."""
        reponse = self.client.get(f"{URL}devices/status/")
        self.assertEqual(reponse.status_code, status.HTTP_200_OK)
        self.assertFalse(reponse.data["push_configure"])
        self.assertEqual(reponse.data["appareils_actifs"], 0)

    def test_etat_du_push_configure(self):
        """`push_configure` ne vaut vrai que si tout est reellement pret.

        Le service verifie trois choses : le reglage renseigne, le fichier
        d'identifiants existant, et `firebase-admin` installe. On simule
        donc le verdict du service plutot que de poser un vrai fichier.
        """
        AppareilPush.objects.create(
            utilisateur=self.acheteur, jeton="j", plateforme="ANDROID"
        )
        with mock.patch.object(PushService, "est_configure", return_value=True):
            reponse = self.client.get(f"{URL}devices/status/")
        self.assertTrue(reponse.data["push_configure"])
        self.assertEqual(reponse.data["appareils_actifs"], 1)


class PushTests(BaseNotificationTests):
    """Transport push, API FCM HTTP v1 (compte de service).

    Aucun de ces tests ne sort sur le reseau ni n'exige `firebase-admin` :
    le module de messagerie de Firebase est simule. C'est volontaire — le
    push est une dependance FACULTATIVE, et la suite doit passer sur une
    machine qui ne l'a jamais installe.
    """

    def setUp(self):
        super().setUp()
        # Chaque test repart d'un service non initialise.
        PushService.reinitialiser()
        self.addCleanup(PushService.reinitialiser)

    def _messagerie_simulee(self):
        """Faux module `firebase_admin.messaging`, reduit a l'utile."""
        faux = mock.MagicMock()

        class UnregisteredError(Exception):
            pass

        class SenderIdMismatchError(Exception):
            pass

        faux.UnregisteredError = UnregisteredError
        faux.SenderIdMismatchError = SenderIdMismatchError
        return faux

    def test_sans_configuration_le_push_est_inactif(self):
        """Regle du CD : l'application fonctionne sans service push."""
        AppareilPush.objects.create(
            utilisateur=self.acheteur, jeton="j", plateforme="ANDROID"
        )
        notification = NotificationService.creer(
            self.acheteur, TypeNotification.MESSAGE_NOUVEAU, "Titre", "Corps"
        )
        self.assertFalse(PushService.est_configure())
        self.assertEqual(PushService.envoyer(notification), 0)
        # La notification interne existe quand meme.
        self.assertIsNotNone(notification.pk)
        self.assertEqual(Notification.objects.de(self.acheteur).count(), 1)

    @override_settings(FIREBASE_CREDENTIALS_PATH="C:/introuvable/compte.json")
    def test_un_chemin_errone_ne_casse_rien(self):
        """L'erreur de configuration la plus courante : un chemin mal copie."""
        AppareilPush.objects.create(
            utilisateur=self.acheteur, jeton="j", plateforme="ANDROID"
        )
        self.assertFalse(PushService.est_configure())
        notification = NotificationService.creer(
            self.acheteur, TypeNotification.MESSAGE_NOUVEAU, "Titre", ""
        )
        self.assertIsNotNone(notification)

    @override_settings(FIREBASE_CREDENTIALS_PATH="C:/faux/compte.json")
    def test_un_envoi_par_appareil(self):
        for jeton in ("j1", "j2"):
            AppareilPush.objects.create(
                utilisateur=self.acheteur, jeton=jeton, plateforme="ANDROID"
            )
        messagerie = self._messagerie_simulee()

        with mock.patch.object(
            PushService, "_messagerie", return_value=messagerie
        ):
            notification = NotificationService.creer(
                self.acheteur, TypeNotification.MESSAGE_NOUVEAU, "Titre", "Corps"
            )
            # `creer` a deja declenche un envoi par appareil.
            self.assertEqual(messagerie.send.call_count, 2)
            self.assertEqual(PushService.envoyer(notification), 2)

        self.assertEqual(messagerie.send.call_count, 4)

    @override_settings(FIREBASE_CREDENTIALS_PATH="C:/faux/compte.json")
    def test_la_charge_utile_porte_le_lien_profond(self):
        """L'application mobile doit pouvoir ouvrir le bon ecran."""
        AppareilPush.objects.create(
            utilisateur=self.acheteur, jeton="j", plateforme="ANDROID"
        )
        messagerie = self._messagerie_simulee()

        with mock.patch.object(
            PushService, "_messagerie", return_value=messagerie
        ):
            NotificationService.creer(
                self.acheteur,
                TypeNotification.RESERVATION_ACCEPTEE,
                "Reservation acceptee",
                "2 unites mises de cote",
                reference_type="reservation",
                reference_id=42,
                donnees={"produit_id": 5},
            )

        # `Message(...)` a bien ete construit avec les donnees de routage.
        _, kwargs = messagerie.Message.call_args
        donnees = kwargs["data"]
        self.assertEqual(donnees["type"], "RESERVATION_ACCEPTEE")
        self.assertEqual(donnees["reference_type"], "reservation")
        self.assertEqual(donnees["reference_id"], "42")
        # FCM v1 n'accepte que des chaines : tout est converti.
        self.assertEqual(donnees["produit_id"], "5")
        self.assertTrue(all(isinstance(v, str) for v in donnees.values()))

    @override_settings(FIREBASE_CREDENTIALS_PATH="C:/faux/compte.json")
    def test_un_jeton_desinscrit_est_desactive(self):
        """Un appareil desinstalle ne doit pas etre retente indefiniment."""
        AppareilPush.objects.create(
            utilisateur=self.acheteur, jeton="perime", plateforme="ANDROID"
        )
        messagerie = self._messagerie_simulee()
        messagerie.send.side_effect = messagerie.UnregisteredError("inconnu")

        with mock.patch.object(
            PushService, "_messagerie", return_value=messagerie
        ):
            notification = NotificationService.creer(
                self.acheteur, TypeNotification.MESSAGE_NOUVEAU, "Titre", ""
            )
            self.assertEqual(PushService.envoyer(notification), 0)

        self.assertFalse(
            AppareilPush.objects.get(jeton="perime").actif,
            "Un jeton refuse par Google doit etre desactive.",
        )

    @override_settings(FIREBASE_CREDENTIALS_PATH="C:/faux/compte.json")
    def test_une_panne_passagere_ne_desactive_pas_le_jeton(self):
        """Une coupure reseau n'est pas un appareil desinscrit."""
        AppareilPush.objects.create(
            utilisateur=self.acheteur, jeton="valide", plateforme="ANDROID"
        )
        messagerie = self._messagerie_simulee()
        messagerie.send.side_effect = OSError("reseau coupe")

        with mock.patch.object(
            PushService, "_messagerie", return_value=messagerie
        ):
            notification = NotificationService.creer(
                self.acheteur, TypeNotification.MESSAGE_NOUVEAU, "Titre", ""
            )

        self.assertIsNotNone(notification)
        self.assertTrue(
            AppareilPush.objects.get(jeton="valide").actif,
            "Une panne passagere ne doit pas condamner le jeton.",
        )
        self.assertEqual(Notification.objects.de(self.acheteur).count(), 1)

    @override_settings(FIREBASE_CREDENTIALS_PATH="C:/faux/compte.json")
    def test_un_appareil_inactif_est_ignore(self):
        AppareilPush.objects.create(
            utilisateur=self.acheteur,
            jeton="j",
            plateforme="ANDROID",
            actif=False,
        )
        messagerie = self._messagerie_simulee()
        with mock.patch.object(
            PushService, "_messagerie", return_value=messagerie
        ):
            notification = NotificationService.creer(
                self.acheteur, TypeNotification.MESSAGE_NOUVEAU, "Titre", ""
            )
            self.assertEqual(PushService.envoyer(notification), 0)
        messagerie.send.assert_not_called()

    def test_sans_firebase_admin_le_service_se_tait(self):
        """La bibliotheque est facultative : son absence n'est pas une erreur."""
        AppareilPush.objects.create(
            utilisateur=self.acheteur, jeton="j", plateforme="ANDROID"
        )
        with mock.patch.object(PushService, "_messagerie", return_value=None):
            notification = NotificationService.creer(
                self.acheteur, TypeNotification.MESSAGE_NOUVEAU, "Titre", ""
            )
            self.assertEqual(PushService.envoyer(notification), 0)
        self.assertIsNotNone(notification)


class RobustesseTests(BaseNotificationTests):
    """Une notification ne doit jamais faire echouer l'operation metier."""

    def test_une_panne_de_notification_ne_bloque_pas_une_reservation(self):
        with mock.patch(
            "modules.notifications.models.Notification.objects.create",
            side_effect=RuntimeError("table verrouillee"),
        ):
            reservation = ReservationService.demander(self.produit, self.acheteur, 2)

        # La reservation existe, malgre la panne de notification.
        self.assertIsNotNone(reservation.pk)
        self.assertEqual(Notification.objects.count(), 0)

    def test_une_panne_de_notification_ne_bloque_pas_une_acceptation(self):
        reservation = ReservationService.demander(self.produit, self.acheteur, 2)
        with mock.patch(
            "modules.notifications.models.Notification.objects.create",
            side_effect=RuntimeError("panne"),
        ):
            reservation = ReservationService.accepter(reservation, self.vendeur)

        reservation.refresh_from_db()
        self.assertEqual(reservation.statut, "CONFIRMED")
        inventaire = Inventaire.objects.get(produit=self.produit)
        self.assertEqual(inventaire.quantite_reservee, 2)

    def test_une_panne_de_notification_ne_bloque_pas_un_message(self):
        """`envoyer_message` est transactionnel.

        C'est le point de sauvegarde pose par `NotificationService.creer`
        qui empeche l'echec d'ecriture d'annuler le message lui-meme.
        """
        conversation = Conversation.objects.create(
            acheteur=self.acheteur, vendeur=self.vendeur, produit=self.produit,
            prix_initial=self.produit.prix,
        )
        with mock.patch(
            "modules.notifications.models.Notification.objects.create",
            side_effect=RuntimeError("panne"),
        ):
            message = MessagerieService.envoyer_message(
                conversation, self.acheteur, contenu="Bonjour"
            )

        self.assertIsNotNone(message.pk)
        self.assertEqual(conversation.messages.count(), 1)
        self.assertEqual(Notification.objects.count(), 0)

    def test_une_panne_de_notification_ne_bloque_pas_une_vente(self):
        vente = VenteService.enregistrer_vente_directe(
            self.produit, self.vendeur, self.acheteur, 1
        )
        VenteService.confirmer_paiement(vente, self.vendeur)
        with mock.patch(
            "modules.notifications.models.Notification.objects.create",
            side_effect=RuntimeError("panne"),
        ):
            vente = VenteService.confirmer_reception(vente, self.acheteur)
        self.assertEqual(vente.statut, "COMPLETED")

    def test_redis_indisponible_ne_bloque_rien(self):
        """Le temps reel est un confort, la base est la source de verite."""
        with mock.patch.object(
            NotificationService, "diffuser", side_effect=RuntimeError("Redis absent")
        ):
            notification = NotificationService.creer(
                self.acheteur, TypeNotification.MESSAGE_NOUVEAU, "Titre", ""
            )

        # Aucune exception levee, et la notification est bien en base : le
        # temps reel est un confort, la base est la source de verite.
        self.assertIsNotNone(notification)
        self.assertEqual(Notification.objects.de(self.acheteur).count(), 1)

    def test_un_destinataire_inactif_ne_recoit_rien(self):
        self.tiers.is_active = False
        self.tiers.save(update_fields=["is_active"])
        resultat = NotificationService.creer(
            self.tiers, TypeNotification.MESSAGE_NOUVEAU, "Titre", ""
        )
        self.assertIsNone(resultat)
        self.assertEqual(Notification.objects.count(), 0)

    def test_pas_d_auto_notification(self):
        resultat = NotificationService.creer(
            self.acheteur,
            TypeNotification.MESSAGE_NOUVEAU,
            "Titre",
            "",
            declencheur=self.acheteur,
        )
        self.assertIsNone(resultat)
