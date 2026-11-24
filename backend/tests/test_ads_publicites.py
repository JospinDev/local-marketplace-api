"""Tests des publicites : bandeau public, interrupteur global, droits."""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from modules.ads.models import Publicite, TypeCiblePublicite
from modules.ads.services import CLE_INTERRUPTEUR, PubliciteService
from modules.moderation.models import ParametrePlateforme

User = get_user_model()

#: Le plus petit GIF valide : evite de dependre d'un fichier du depot.
GIF_MINIMAL = (
    b"GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff!"
    b"\xf9\x04\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00"
    b"\x00\x02\x02D\x01\x00;"
)


def image(nom="pub.gif"):
    return SimpleUploadedFile(nom, GIF_MINIMAL, content_type="image/gif")


class BandeauPublic(APITestCase):
    """La route publique ne montre que ce qui est reellement diffusable."""

    def setUp(self):
        self.url = reverse("public-ads-list")
        self.maintenant = timezone.now()

    def test_bandeau_vide_quand_aucune_publicite(self):
        """Pas de publicite : liste vide, donc emplacement supprime."""
        reponse = self.client.get(self.url)
        self.assertEqual(reponse.status_code, status.HTTP_200_OK)
        self.assertEqual(reponse.data, [])

    def test_sans_compte(self):
        """Le bandeau s'affiche aussi pour un visiteur non connecte."""
        Publicite.objects.create(titre="Soldes", image=image())
        reponse = self.client.get(self.url)
        self.assertEqual(reponse.status_code, status.HTTP_200_OK)
        self.assertEqual(len(reponse.data), 1)

    def test_publicite_inactive_exclue(self):
        Publicite.objects.create(titre="Active", image=image())
        Publicite.objects.create(titre="Coupee", image=image(), actif=False)

        reponse = self.client.get(self.url)
        titres = [p["titre"] for p in reponse.data]
        self.assertEqual(titres, ["Active"])

    def test_fenetre_de_diffusion(self):
        """Une publicite pas encore commencee ou deja finie est exclue."""
        Publicite.objects.create(
            titre="Future",
            image=image(),
            debut_le=self.maintenant + timedelta(days=1),
        )
        Publicite.objects.create(
            titre="Passee",
            image=image(),
            fin_le=self.maintenant - timedelta(days=1),
        )
        Publicite.objects.create(
            titre="En cours",
            image=image(),
            debut_le=self.maintenant - timedelta(hours=1),
            fin_le=self.maintenant + timedelta(hours=1),
        )
        Publicite.objects.create(titre="Permanente", image=image())

        reponse = self.client.get(self.url)
        titres = sorted(p["titre"] for p in reponse.data)
        self.assertEqual(titres, ["En cours", "Permanente"])

    def test_ordre_respecte(self):
        Publicite.objects.create(titre="Troisieme", image=image(), ordre=30)
        Publicite.objects.create(titre="Premiere", image=image(), ordre=10)
        Publicite.objects.create(titre="Deuxieme", image=image(), ordre=20)

        reponse = self.client.get(self.url)
        self.assertEqual(
            [p["titre"] for p in reponse.data],
            ["Premiere", "Deuxieme", "Troisieme"],
        )

    def test_champs_publics_seulement(self):
        """Les compteurs et la fenetre ne sortent pas de l'administration."""
        Publicite.objects.create(titre="Soldes", image=image())
        reponse = self.client.get(self.url)
        champs = set(reponse.data[0].keys())

        for interdit in (
            "nombre_clics",
            "nombre_affichages",
            "actif",
            "debut_le",
            "fin_le",
            "cree_par",
        ):
            self.assertNotIn(interdit, champs, interdit)

    def test_interrupteur_global_coupe_tout(self):
        """Coupe, le bandeau disparait sans toucher aux publicites."""
        Publicite.objects.create(titre="Soldes", image=image(), actif=True)
        PubliciteService.basculer(False)

        reponse = self.client.get(self.url)
        self.assertEqual(reponse.data, [])

        # Les publicites elles-memes n'ont pas ete modifiees.
        self.assertTrue(Publicite.objects.get(titre="Soldes").actif)

        PubliciteService.basculer(True)
        self.assertEqual(len(self.client.get(self.url).data), 1)

    def test_etat_du_bandeau(self):
        Publicite.objects.create(titre="Soldes", image=image())
        reponse = self.client.get(reverse("public-ads-etat"))
        self.assertEqual(reponse.status_code, status.HTTP_200_OK)
        self.assertTrue(reponse.data["actives"])
        self.assertEqual(reponse.data["nombre_diffusables"], 1)

    def test_compteur_affichages(self):
        publicite = Publicite.objects.create(titre="Soldes", image=image())
        self.client.get(self.url)
        publicite.refresh_from_db()
        self.assertEqual(publicite.nombre_affichages, 1)

    def test_compteur_clics(self):
        publicite = Publicite.objects.create(titre="Soldes", image=image())
        reponse = self.client.post(
            reverse("public-ads-clic", kwargs={"pk": publicite.pk})
        )
        self.assertEqual(reponse.status_code, status.HTTP_204_NO_CONTENT)
        publicite.refresh_from_db()
        self.assertEqual(publicite.nombre_clics, 1)


class AdministrationPublicites(APITestCase):
    """Droits stricts : chaque permission n'ouvre que son action."""

    def setUp(self):
        self.url = reverse("admin-ads-list")
        self.ordinaire = User.objects.create_user(
            username="ordinaire", password="MotDePasse123!"
        )
        self.superutilisateur = User.objects.create_superuser(
            username="chef", password="MotDePasse123!"
        )

    def _avec_permissions(self, *codes):
        utilisateur = User.objects.create_user(
            username="agent_" + "_".join(c.split(".")[-1] for c in codes),
            password="MotDePasse123!",
        )
        groupe = Group.objects.create(name="groupe_" + utilisateur.username)
        for code in codes:
            app_label, codename = code.split(".")
            groupe.permissions.add(
                Permission.objects.get(
                    content_type__app_label=app_label, codename=codename
                )
            )
        utilisateur.groups.add(groupe)
        return utilisateur

    def test_anonyme_refuse(self):
        reponse = self.client.get(self.url)
        self.assertIn(
            reponse.status_code,
            (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN),
        )

    def test_compte_ordinaire_refuse(self):
        self.client.force_authenticate(self.ordinaire)
        self.assertEqual(
            self.client.get(self.url).status_code, status.HTTP_403_FORBIDDEN
        )

    def test_view_seul_ne_permet_pas_de_creer(self):
        """La regle stricte du projet : `view_*` ne donne que la lecture."""
        self.client.force_authenticate(self._avec_permissions("ads.view_publicite"))

        self.assertEqual(
            self.client.get(self.url).status_code, status.HTTP_200_OK
        )
        reponse = self.client.post(
            self.url, {"titre": "Soldes", "image": image()}, format="multipart"
        )
        self.assertEqual(reponse.status_code, status.HTTP_403_FORBIDDEN)

    def test_add_seul_ne_permet_pas_de_lire(self):
        self.client.force_authenticate(self._avec_permissions("ads.add_publicite"))

        reponse = self.client.post(
            self.url, {"titre": "Soldes", "image": image()}, format="multipart"
        )
        self.assertEqual(reponse.status_code, status.HTTP_201_CREATED)
        self.assertEqual(
            self.client.get(self.url).status_code, status.HTTP_403_FORBIDDEN
        )

    def test_creation_enregistre_son_auteur(self):
        self.client.force_authenticate(self.superutilisateur)
        reponse = self.client.post(
            self.url, {"titre": "Soldes", "image": image()}, format="multipart"
        )
        self.assertEqual(reponse.status_code, status.HTTP_201_CREATED)
        self.assertEqual(
            Publicite.objects.get(pk=reponse.data["id"]).cree_par,
            self.superutilisateur,
        )

    def test_voit_aussi_les_publicites_inactives(self):
        Publicite.objects.create(titre="Coupee", image=image(), actif=False)
        self.client.force_authenticate(self.superutilisateur)
        reponse = self.client.get(self.url)
        self.assertEqual(reponse.data["count"], 1)

    def test_cible_produit_exige_un_identifiant(self):
        """Une publicite cliquable sans cible ne ferait rien a l'appui."""
        self.client.force_authenticate(self.superutilisateur)
        reponse = self.client.post(
            self.url,
            {
                "titre": "Soldes",
                "image": image(),
                "type_cible": TypeCiblePublicite.PRODUIT,
            },
            format="multipart",
        )
        self.assertEqual(reponse.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("cible_id", reponse.data.get("errors", reponse.data))

    def test_cible_url_exige_une_adresse(self):
        self.client.force_authenticate(self.superutilisateur)
        reponse = self.client.post(
            self.url,
            {
                "titre": "Soldes",
                "image": image(),
                "type_cible": TypeCiblePublicite.URL,
            },
            format="multipart",
        )
        self.assertEqual(reponse.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("cible_url", reponse.data.get("errors", reponse.data))

    def test_fenetre_incoherente_refusee(self):
        self.client.force_authenticate(self.superutilisateur)
        maintenant = timezone.now()
        reponse = self.client.post(
            self.url,
            {
                "titre": "Soldes",
                "image": image(),
                "debut_le": (maintenant + timedelta(days=2)).isoformat(),
                "fin_le": maintenant.isoformat(),
            },
            format="multipart",
        )
        self.assertEqual(reponse.status_code, status.HTTP_400_BAD_REQUEST)

    def test_interrupteur_par_la_route(self):
        self.client.force_authenticate(self.superutilisateur)
        url = reverse("admin-ads-basculer")

        reponse = self.client.post(url, {"actives": False}, format="json")
        self.assertEqual(reponse.status_code, status.HTTP_200_OK)
        self.assertFalse(reponse.data["actives"])
        self.assertFalse(PubliciteService.bandeau_actif())

        # Le reglage est bien persiste dans les parametres de plateforme.
        self.assertTrue(
            ParametrePlateforme.objects.filter(cle=CLE_INTERRUPTEUR).exists()
        )

        reponse = self.client.post(url, {"actives": True}, format="json")
        self.assertTrue(reponse.data["actives"])

    def test_interrupteur_refuse_sans_change(self):
        """Lire l'etat et le changer sont deux droits distincts.

        Avec une seule action acceptant GET et POST, `action_permissions`
        n'aurait pu exiger qu'une seule permission : un compte en lecture
        seule aurait pu eteindre tout le bandeau. Ce test garde la
        separation.
        """
        self.client.force_authenticate(self._avec_permissions("ads.view_publicite"))

        # Lire l'etat reste permis.
        self.assertEqual(
            self.client.get(reverse("admin-ads-etat")).status_code,
            status.HTTP_200_OK,
        )
        # Le basculer, non.
        reponse = self.client.post(
            reverse("admin-ads-basculer"), {"actives": False}, format="json"
        )
        self.assertEqual(reponse.status_code, status.HTTP_403_FORBIDDEN)

    def test_reordonner(self):
        premiere = Publicite.objects.create(titre="A", image=image(), ordre=0)
        seconde = Publicite.objects.create(titre="B", image=image(), ordre=1)

        self.client.force_authenticate(self.superutilisateur)
        reponse = self.client.post(
            reverse("admin-ads-reordonner"),
            {"identifiants": [seconde.pk, premiere.pk]},
            format="json",
        )
        self.assertEqual(reponse.status_code, status.HTTP_200_OK)

        premiere.refresh_from_db()
        seconde.refresh_from_db()
        self.assertEqual(seconde.ordre, 0)
        self.assertEqual(premiere.ordre, 1)

    def test_reordonner_sans_liste_refuse(self):
        self.client.force_authenticate(self.superutilisateur)
        reponse = self.client.post(
            reverse("admin-ads-reordonner"), {}, format="json"
        )
        self.assertEqual(reponse.status_code, status.HTTP_400_BAD_REQUEST)

    def test_moderateur_gere_le_bandeau_sans_supprimer(self):
        """Le groupe Moderateur cree et modifie, mais ne supprime pas."""
        from django.core.management import call_command

        call_command("init_groupes", verbosity=0)
        moderateur = User.objects.create_user(
            username="moderateur", password="MotDePasse123!"
        )
        moderateur.groups.add(Group.objects.get(name="Moderateur"))
        self.client.force_authenticate(moderateur)

        reponse = self.client.post(
            self.url, {"titre": "Soldes", "image": image()}, format="multipart"
        )
        self.assertEqual(reponse.status_code, status.HTTP_201_CREATED)
        identifiant = reponse.data["id"]

        reponse = self.client.patch(
            reverse("admin-ads-detail", kwargs={"pk": identifiant}),
            {"actif": False},
            format="json",
        )
        self.assertEqual(reponse.status_code, status.HTTP_200_OK)

        reponse = self.client.delete(
            reverse("admin-ads-detail", kwargs={"pk": identifiant})
        )
        self.assertEqual(reponse.status_code, status.HTTP_403_FORBIDDEN)
