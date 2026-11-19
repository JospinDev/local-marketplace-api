"""Tests du module 1 : inscription, verification email, connexion, permissions."""
import re

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.core import mail
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from modules.accounts.models import StatutCompte

User = get_user_model()


class InscriptionSansEmailTests(APITestCase):
    url = "/api/v1/auth/register/"

    def test_username_obligatoire_et_compte_actif_sans_email(self):
        reponse = self.client.post(
            self.url,
            {
                "username": "jospin",
                "password": "MotDePasse2026",
                "password_confirmation": "MotDePasse2026",
                "nom_complet": "Jospin Ndayizeye",
                "localisation": "Mukaza, Bujumbura Mairie",
            },
            format="json",
        )
        self.assertEqual(reponse.status_code, status.HTTP_201_CREATED, reponse.data)
        self.assertFalse(reponse.data["email_verification_requise"])

        utilisateur = User.objects.get(username="jospin")
        self.assertTrue(utilisateur.is_active)
        self.assertEqual(utilisateur.statut_compte, StatutCompte.ACTIF)
        self.assertIsNone(utilisateur.email)
        self.assertEqual(len(mail.outbox), 0)

    def test_username_unique(self):
        User.objects.create_user(username="jospin", password="MotDePasse2026")
        reponse = self.client.post(
            self.url,
            {
                "username": "JOSPIN",
                "password": "MotDePasse2026",
                "password_confirmation": "MotDePasse2026",
            },
            format="json",
        )
        self.assertEqual(reponse.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("username", reponse.data["errors"])

    def test_username_manquant_refuse(self):
        reponse = self.client.post(
            self.url,
            {"password": "MotDePasse2026", "password_confirmation": "MotDePasse2026"},
            format="json",
        )
        self.assertEqual(reponse.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("username", reponse.data["errors"])


class InscriptionAvecEmailTests(APITestCase):
    url_register = "/api/v1/auth/register/"
    url_verify = "/api/v1/auth/email/verify/"
    url_login = "/api/v1/auth/login/"

    def _inscrire(self):
        return self.client.post(
            self.url_register,
            {
                "username": "vendeur1",
                "email": "vendeur1@example.com",
                "password": "MotDePasse2026",
                "password_confirmation": "MotDePasse2026",
            },
            format="json",
        )

    def test_compte_inactif_jusqu_a_la_saisie_du_code(self):
        reponse = self._inscrire()
        self.assertEqual(reponse.status_code, status.HTTP_201_CREATED, reponse.data)
        self.assertTrue(reponse.data["email_verification_requise"])

        utilisateur = User.objects.get(username="vendeur1")
        self.assertFalse(utilisateur.is_active)
        self.assertFalse(utilisateur.email_verifie)
        self.assertEqual(utilisateur.statut_compte, StatutCompte.EN_ATTENTE)
        self.assertEqual(len(mail.outbox), 1)

        # Sans le code, la connexion est refusee : l'email n'est pas prouve.
        connexion = self.client.post(
            self.url_login,
            {"username": "vendeur1", "password": "MotDePasse2026"},
            format="json",
        )
        self.assertEqual(connexion.status_code, status.HTTP_400_BAD_REQUEST)

    def test_code_correct_active_le_compte(self):
        self._inscrire()
        code = re.search(r"\b(\d{6})\b", mail.outbox[0].body).group(1)

        reponse = self.client.post(
            self.url_verify,
            {"username": "vendeur1", "code": code},
            format="json",
        )
        self.assertEqual(reponse.status_code, status.HTTP_200_OK, reponse.data)

        utilisateur = User.objects.get(username="vendeur1")
        self.assertTrue(utilisateur.is_active)
        self.assertTrue(utilisateur.email_verifie)
        self.assertEqual(utilisateur.statut_compte, StatutCompte.ACTIF)

        connexion = self.client.post(
            self.url_login,
            {"username": "vendeur1", "password": "MotDePasse2026"},
            format="json",
        )
        self.assertEqual(connexion.status_code, status.HTTP_200_OK, connexion.data)
        self.assertIn("access", connexion.data)

    def test_code_incorrect_refuse(self):
        self._inscrire()
        reponse = self.client.post(
            self.url_verify,
            {"username": "vendeur1", "code": "000000"},
            format="json",
        )
        self.assertEqual(reponse.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(User.objects.get(username="vendeur1").email_verifie)

    def test_email_deja_utilise_refuse(self):
        self._inscrire()
        reponse = self.client.post(
            self.url_register,
            {
                "username": "vendeur2",
                "email": "VENDEUR1@example.com",
                "password": "MotDePasse2026",
                "password_confirmation": "MotDePasse2026",
            },
            format="json",
        )
        self.assertEqual(reponse.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("email", reponse.data["errors"])


class MonProfilTests(APITestCase):
    def setUp(self):
        self.utilisateur = User.objects.create_user(
            username="acheteur", password="MotDePasse2026", localisation="Gitega"
        )
        self.client.force_authenticate(self.utilisateur)

    def test_lecture_et_modification(self):
        reponse = self.client.get("/api/v1/me/")
        self.assertEqual(reponse.status_code, status.HTTP_200_OK)
        self.assertEqual(reponse.data["username"], "acheteur")

        maj = self.client.patch(
            "/api/v1/me/", {"nom_complet": "Acheteur Test"}, format="json"
        )
        self.assertEqual(maj.status_code, status.HTTP_200_OK, maj.data)
        self.assertEqual(maj.data["nom_complet"], "Acheteur Test")

    def test_anonyme_refuse(self):
        self.client.force_authenticate(None)
        reponse = self.client.get("/api/v1/me/")
        self.assertEqual(reponse.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_suppression_douce(self):
        reponse = self.client.delete("/api/v1/me/")
        self.assertEqual(reponse.status_code, status.HTTP_204_NO_CONTENT)
        self.utilisateur.refresh_from_db()
        self.assertFalse(self.utilisateur.is_active)
        self.assertIsNotNone(self.utilisateur.suppression_demandee_le)


class PermissionsUtilisateursAdminTests(APITestCase):
    """Un groupe ne donne acces qu'a ce que ses permissions autorisent."""

    url = "/api/v1/admin/users/"

    def setUp(self):
        self.membre = User.objects.create_user(
            username="moderateur", password="MotDePasse2026"
        )
        self.client.force_authenticate(self.membre)

    def _donner(self, *codenames):
        groupe = Group.objects.create(name="Groupe test " + "-".join(codenames))
        for codename in codenames:
            groupe.permissions.add(
                Permission.objects.get(
                    content_type__app_label="accounts", codename=codename
                )
            )
        self.membre.groups.add(groupe)
        self.membre = User.objects.get(pk=self.membre.pk)
        self.client.force_authenticate(self.membre)

    def test_sans_permission_tout_est_refuse(self):
        self.assertEqual(
            self.client.get(self.url).status_code, status.HTTP_403_FORBIDDEN
        )

    def test_view_user_autorise_seulement_la_lecture(self):
        self._donner("view_user")
        self.assertEqual(self.client.get(self.url).status_code, status.HTTP_200_OK)
        creation = self.client.post(
            self.url, {"username": "nouveau"}, format="json"
        )
        self.assertEqual(creation.status_code, status.HTTP_403_FORBIDDEN)

    def test_change_user_autorise_la_suspension(self):
        cible = User.objects.create_user(username="cible", password="MotDePasse2026")
        self._donner("view_user", "change_user")
        reponse = self.client.post(
            f"{self.url}{cible.pk}/suspend/", {"motif": "Annonce interdite"},
            format="json",
        )
        self.assertEqual(reponse.status_code, status.HTTP_200_OK, reponse.data)
        cible.refresh_from_db()
        self.assertEqual(cible.statut_compte, StatutCompte.SUSPENDU)

        suppression = self.client.delete(f"{self.url}{cible.pk}/")
        self.assertEqual(suppression.status_code, status.HTTP_403_FORBIDDEN)

    def test_filtre_localisation_fragment(self):
        """La localisation se cherche par fragment (lookup `icontains`)."""
        User.objects.create_user(
            username="vendeur_buja", password="MotDePasse2026",
            localisation="Taba, Mukaza, Bujumbura Mairie",
        )
        User.objects.create_user(
            username="vendeur_gitega", password="MotDePasse2026",
            localisation="Gitega centre",
        )
        self._donner("view_user")
        reponse = self.client.get(self.url, {"localisation": "jumbura"})
        self.assertEqual(reponse.status_code, status.HTTP_200_OK)
        noms = [u["username"] for u in reponse.data["results"]]
        self.assertIn("vendeur_buja", noms)
        self.assertNotIn("vendeur_gitega", noms)

        # Nimporte quel fragment du texte saisi fonctionne.
        for fragment in ("Taba", "Mukaza", "centre"):
            trouve = self.client.get(self.url, {"localisation": fragment})
            self.assertEqual(
                trouve.data["count"], 1, f"fragment={fragment}"
            )

    def test_filtre_localisation_insensible_a_la_casse(self):
        """`icontains` : la casse saisie par le client n'a pas d'importance."""
        User.objects.create_user(
            username="vendeur_buja", password="MotDePasse2026",
            localisation="Bujumbura Mairie",
        )
        self._donner("view_user")
        for fragment in ("bujum", "BUJUM", "Mairie", "mAiRiE"):
            reponse = self.client.get(self.url, {"localisation": fragment})
            noms = [u["username"] for u in reponse.data["results"]]
            self.assertIn("vendeur_buja", noms, f"fragment={fragment}")
