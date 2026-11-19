"""Tests du module 2 : catalogue public, permissions par groupe, filtres."""
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from rest_framework import status
from rest_framework.test import APITestCase

from modules.categories.models import Categorie

User = get_user_model()


class CataloguePublicTests(APITestCase):
    url = "/api/v1/public/categories/"

    def setUp(self):
        self.electronique = Categorie.objects.create(nom="Electronique", ordre=1)
        self.telephones = Categorie.objects.create(
            nom="Telephones", parent=self.electronique, ordre=1
        )
        Categorie.objects.create(nom="Ordinateurs", parent=self.electronique, ordre=2)
        self.masquee = Categorie.objects.create(nom="Immobilier", is_active=False)

    def test_visiteur_non_connecte_peut_lister(self):
        reponse = self.client.get(self.url)
        self.assertEqual(reponse.status_code, status.HTTP_200_OK)
        noms = [c["nom"] for c in reponse.data["results"]]
        self.assertIn("Electronique", noms)
        self.assertNotIn("Immobilier", noms)  # categorie inactive masquee

    def test_arborescence(self):
        reponse = self.client.get(f"{self.url}tree/")
        self.assertEqual(reponse.status_code, status.HTTP_200_OK)
        racines = {c["nom"]: c for c in reponse.data}
        self.assertIn("Electronique", racines)
        self.assertEqual(len(racines["Electronique"]["sous_categories"]), 2)

    def test_sous_categories(self):
        reponse = self.client.get(f"{self.url}{self.electronique.pk}/children/")
        self.assertEqual(reponse.status_code, status.HTTP_200_OK)
        self.assertEqual(reponse.data["count"], 2)

    def test_filtre_nom_icontains(self):
        reponse = self.client.get(self.url, {"nom": "telep"})
        self.assertEqual(reponse.data["count"], 1)
        self.assertEqual(reponse.data["results"][0]["nom"], "Telephones")

    def test_filtre_racines_et_parent(self):
        racines = self.client.get(self.url, {"racines": "true"})
        self.assertEqual(racines.data["count"], 1)

        enfants = self.client.get(self.url, {"parent": self.electronique.pk})
        self.assertEqual(enfants.data["count"], 2)

    def test_filtre_ordre_gte_lte(self):
        reponse = self.client.get(self.url, {"ordre_gte": 2})
        noms = [c["nom"] for c in reponse.data["results"]]
        self.assertEqual(noms, ["Ordinateurs"])

    def test_ecriture_interdite_en_public(self):
        reponse = self.client.post(self.url, {"nom": "Pirate"}, format="json")
        self.assertEqual(reponse.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)


class PermissionsCategoriesTests(APITestCase):
    """Le groupe determine exactement ce que le membre peut faire."""

    url = "/api/v1/admin/categories/"

    def setUp(self):
        self.membre = User.objects.create_user(
            username="agent", password="MotDePasse2026"
        )
        self.client.force_authenticate(self.membre)
        self.categorie = Categorie.objects.create(nom="Vehicules")

    def _donner(self, *codenames):
        groupe = Group.objects.create(name="G-" + "-".join(codenames))
        for codename in codenames:
            groupe.permissions.add(
                Permission.objects.get(
                    content_type__app_label="categories", codename=codename
                )
            )
        self.membre.groups.add(groupe)
        self.membre = User.objects.get(pk=self.membre.pk)
        self.client.force_authenticate(self.membre)

    def test_anonyme_refuse(self):
        self.client.force_authenticate(None)
        self.assertEqual(
            self.client.get(self.url).status_code, status.HTTP_401_UNAUTHORIZED
        )

    def test_connecte_sans_groupe_refuse(self):
        self.assertEqual(
            self.client.get(self.url).status_code, status.HTTP_403_FORBIDDEN
        )

    def test_add_categorie_seul_autorise_uniquement_la_creation(self):
        self._donner("add_categorie")

        creation = self.client.post(self.url, {"nom": "Mode"}, format="json")
        self.assertEqual(creation.status_code, status.HTTP_201_CREATED, creation.data)

        # Tout le reste est refuse : lecture, modification, suppression.
        self.assertEqual(
            self.client.get(self.url).status_code, status.HTTP_403_FORBIDDEN
        )
        self.assertEqual(
            self.client.patch(
                f"{self.url}{self.categorie.pk}/", {"nom": "X"}, format="json"
            ).status_code,
            status.HTTP_403_FORBIDDEN,
        )
        self.assertEqual(
            self.client.delete(f"{self.url}{self.categorie.pk}/").status_code,
            status.HTTP_403_FORBIDDEN,
        )
        # L'action de desactivation exige change_categorie, pas add_categorie.
        self.assertEqual(
            self.client.post(f"{self.url}{self.categorie.pk}/deactivate/").status_code,
            status.HTTP_403_FORBIDDEN,
        )

    def test_view_categorie_seul_autorise_uniquement_la_lecture(self):
        self._donner("view_categorie")
        self.assertEqual(self.client.get(self.url).status_code, status.HTTP_200_OK)
        self.assertEqual(
            self.client.post(self.url, {"nom": "Mode"}, format="json").status_code,
            status.HTTP_403_FORBIDDEN,
        )

    def test_change_categorie_autorise_modification_et_desactivation(self):
        self._donner("view_categorie", "change_categorie")
        maj = self.client.patch(
            f"{self.url}{self.categorie.pk}/", {"ordre": 5}, format="json"
        )
        self.assertEqual(maj.status_code, status.HTTP_200_OK, maj.data)

        desactivation = self.client.post(
            f"{self.url}{self.categorie.pk}/deactivate/"
        )
        self.assertEqual(desactivation.status_code, status.HTTP_200_OK)
        self.categorie.refresh_from_db()
        self.assertFalse(self.categorie.is_active)

        self.assertEqual(
            self.client.delete(f"{self.url}{self.categorie.pk}/").status_code,
            status.HTTP_403_FORBIDDEN,
        )

    def test_delete_categorie(self):
        self._donner("view_categorie", "delete_categorie")
        reponse = self.client.delete(f"{self.url}{self.categorie.pk}/")
        self.assertEqual(reponse.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(Categorie.objects.filter(pk=self.categorie.pk).exists())

    def test_doublon_sous_meme_parent_refuse(self):
        self._donner("view_categorie", "add_categorie")
        self.client.post(
            self.url, {"nom": "Motos", "parent": self.categorie.pk}, format="json"
        )
        doublon = self.client.post(
            self.url, {"nom": "motos", "parent": self.categorie.pk}, format="json"
        )
        self.assertEqual(doublon.status_code, status.HTTP_400_BAD_REQUEST)

    def test_hierarchie_circulaire_refusee(self):
        enfant = Categorie.objects.create(nom="Motos", parent=self.categorie)
        self._donner("view_categorie", "change_categorie")
        reponse = self.client.patch(
            f"{self.url}{self.categorie.pk}/", {"parent": enfant.pk}, format="json"
        )
        self.assertEqual(reponse.status_code, status.HTTP_400_BAD_REQUEST)

    def test_slug_genere_automatiquement(self):
        self._donner("view_categorie", "add_categorie")
        reponse = self.client.post(
            self.url, {"nom": "Instruments de musique"}, format="json"
        )
        self.assertEqual(reponse.data["slug"], "instruments-de-musique")


class SuperuserTests(APITestCase):
    def test_superuser_a_tous_les_droits(self):
        admin = User.objects.create_superuser(
            username="admin", password="MotDePasse2026"
        )
        self.client.force_authenticate(admin)
        creation = self.client.post(
            "/api/v1/admin/categories/", {"nom": "Agriculture"}, format="json"
        )
        self.assertEqual(creation.status_code, status.HTTP_201_CREATED, creation.data)
