"""Tests du module 3 : propriete, stock, cycle de vie, moderation."""
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from rest_framework import status
from rest_framework.test import APITestCase

from modules.categories.models import Categorie
from modules.products.models import Inventaire, Produit, StatutProduit

User = get_user_model()
URL = "/api/v1/products/"


def creer_produit(owner, categorie, titre="Guitare acoustique Yamaha", prix="250000",
                  quantite=5, statut=StatutProduit.ACTIVE, **extra):
    produit = Produit.objects.create(
        owner=owner, categorie=categorie, titre=titre,
        prix=Decimal(prix), status=statut, **extra,
    )
    Inventaire.objects.create(produit=produit, quantite_totale=quantite)
    return produit


class BaseProduitTests(APITestCase):
    def setUp(self):
        self.categorie = Categorie.objects.create(nom="Instruments de musique")
        self.sous_categorie = Categorie.objects.create(
            nom="Guitares", parent=self.categorie
        )
        self.vendeur = User.objects.create_user(
            username="vendeur", password="MotDePasse2026",
            localisation="Mukaza, Bujumbura Mairie",
        )
        self.autre = User.objects.create_user(
            username="autre_vendeur", password="MotDePasse2026"
        )
        self.client.force_authenticate(self.vendeur)


class CreationProduitTests(BaseProduitTests):
    def test_creation_en_brouillon_avec_stock(self):
        reponse = self.client.post(
            URL,
            {
                "titre": "Guitare acoustique Yamaha",
                "description": "Tres bon etat, cordes neuves.",
                "categorie": self.sous_categorie.pk,
                "prix": "250000.00",
                "etat": "OCCASION",
                "localisation": "Taba, Mukaza, Bujumbura Mairie",
                "inventaire": {"quantite_totale": 5},
            },
            format="json",
        )
        self.assertEqual(reponse.status_code, status.HTTP_201_CREATED, reponse.data)
        self.assertEqual(reponse.data["status"], StatutProduit.DRAFT)
        self.assertEqual(reponse.data["quantite_disponible"], 5)
        self.assertEqual(reponse.data["owner"], self.vendeur.pk)

        produit = Produit.objects.get(pk=reponse.data["id"])
        self.assertEqual(produit.owner, self.vendeur)
        self.assertEqual(produit.inventaire.quantite_totale, 5)
        self.assertEqual(produit.inventaire.quantite_reservee, 0)
        self.assertEqual(produit.inventaire.quantite_vendue, 0)

    def test_owner_impose_par_le_serveur(self):
        """Un vendeur ne peut pas creer une annonce au nom d'un autre."""
        reponse = self.client.post(
            URL,
            {
                "titre": "Tentative",
                "categorie": self.categorie.pk,
                "prix": "1000",
                "owner": self.autre.pk,
                "inventaire": {"quantite_totale": 1},
            },
            format="json",
        )
        self.assertEqual(reponse.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Produit.objects.get(pk=reponse.data["id"]).owner, self.vendeur)

    def test_prix_negatif_refuse(self):
        reponse = self.client.post(
            URL,
            {"titre": "X", "categorie": self.categorie.pk, "prix": "-5"},
            format="json",
        )
        self.assertEqual(reponse.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("prix", reponse.data["errors"])

    def test_categorie_inactive_refusee(self):
        inactive = Categorie.objects.create(nom="Interdite", is_active=False)
        reponse = self.client.post(
            URL,
            {"titre": "X", "categorie": inactive.pk, "prix": "1000"},
            format="json",
        )
        self.assertEqual(reponse.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("categorie", reponse.data["errors"])

    def test_coordonnees_incompletes_refusees(self):
        reponse = self.client.post(
            URL,
            {
                "titre": "X", "categorie": self.categorie.pk, "prix": "1000",
                "latitude": "-3.383",
            },
            format="json",
        )
        self.assertEqual(reponse.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("latitude", reponse.data["errors"])

    def test_anonyme_refuse(self):
        self.client.force_authenticate(None)
        reponse = self.client.post(
            URL, {"titre": "X", "categorie": self.categorie.pk, "prix": "1"},
            format="json",
        )
        self.assertEqual(reponse.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_compte_suspendu_ne_peut_pas_publier(self):
        self.vendeur.suspendre("Annonces frauduleuses")
        self.client.force_authenticate(self.vendeur)
        reponse = self.client.post(
            URL, {"titre": "X", "categorie": self.categorie.pk, "prix": "1"},
            format="json",
        )
        self.assertEqual(reponse.status_code, status.HTTP_403_FORBIDDEN)


class ProprieteProduitTests(BaseProduitTests):
    """Scenario 9 du cahier des charges : isolation entre vendeurs."""

    def setUp(self):
        super().setUp()
        self.produit_autre = creer_produit(self.autre, self.categorie, titre="Moto Honda")

    def test_mes_annonces_ne_montrent_que_les_miennes(self):
        creer_produit(self.vendeur, self.categorie, titre="Ma guitare")
        reponse = self.client.get(f"{URL}my-products/")
        self.assertEqual(reponse.status_code, status.HTTP_200_OK)
        titres = [p["titre"] for p in reponse.data["results"]]
        self.assertEqual(titres, ["Ma guitare"])

    def test_lecture_annonce_d_autrui_refusee(self):
        reponse = self.client.get(f"{URL}{self.produit_autre.pk}/")
        self.assertEqual(reponse.status_code, status.HTTP_404_NOT_FOUND)

    def test_modification_annonce_d_autrui_refusee(self):
        reponse = self.client.patch(
            f"{URL}{self.produit_autre.pk}/", {"prix": "1"}, format="json"
        )
        self.assertEqual(reponse.status_code, status.HTTP_404_NOT_FOUND)
        self.produit_autre.refresh_from_db()
        self.assertEqual(self.produit_autre.prix, Decimal("250000"))

    def test_stock_d_autrui_inaccessible(self):
        reponse = self.client.patch(
            f"{URL}{self.produit_autre.pk}/stock/",
            {"quantite_totale": 99}, format="json",
        )
        self.assertEqual(reponse.status_code, status.HTTP_404_NOT_FOUND)


class StockProduitTests(BaseProduitTests):
    def setUp(self):
        super().setUp()
        self.produit = creer_produit(self.vendeur, self.categorie, quantite=5)

    def test_quantite_vendue_non_modifiable_par_le_vendeur(self):
        """Regle 3 : le vendeur ne touche jamais aux quantites vendues."""
        reponse = self.client.patch(
            f"{URL}{self.produit.pk}/stock/",
            {"quantite_totale": 10, "quantite_vendue": 7, "quantite_reservee": 3},
            format="json",
        )
        self.assertEqual(reponse.status_code, status.HTTP_200_OK, reponse.data)
        inventaire = Inventaire.objects.get(produit=self.produit)
        self.assertEqual(inventaire.quantite_totale, 10)
        self.assertEqual(inventaire.quantite_vendue, 0)
        self.assertEqual(inventaire.quantite_reservee, 0)

    def test_stock_total_sous_les_engagements_refuse(self):
        Inventaire.objects.filter(produit=self.produit).update(
            quantite_reservee=2, quantite_vendue=1
        )
        reponse = self.client.patch(
            f"{URL}{self.produit.pk}/stock/", {"quantite_totale": 2}, format="json"
        )
        self.assertEqual(reponse.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("quantite_totale", reponse.data["errors"])

    def test_quantite_disponible_calculee(self):
        """Exemple du cahier des charges : 5 - 2 reserves - 1 vendu = 2."""
        Inventaire.objects.filter(produit=self.produit).update(
            quantite_reservee=2, quantite_vendue=1
        )
        reponse = self.client.get(f"{URL}{self.produit.pk}/stock/")
        self.assertEqual(reponse.data["quantite_disponible"], 2)

    def test_rupture_de_stock_automatique(self):
        """Regle 6 : plus rien de disponible -> OUT_OF_STOCK."""
        Inventaire.objects.filter(produit=self.produit).update(quantite_vendue=5)
        reponse = self.client.patch(
            f"{URL}{self.produit.pk}/stock/", {"quantite_totale": 5}, format="json"
        )
        self.assertEqual(reponse.status_code, status.HTTP_200_OK, reponse.data)
        self.produit.refresh_from_db()
        self.assertEqual(self.produit.status, StatutProduit.OUT_OF_STOCK)

    def test_reapprovisionnement_remet_en_ligne(self):
        self.produit.status = StatutProduit.OUT_OF_STOCK
        self.produit.save(update_fields=["status"])
        Inventaire.objects.filter(produit=self.produit).update(
            quantite_totale=5, quantite_vendue=5
        )
        reponse = self.client.patch(
            f"{URL}{self.produit.pk}/stock/", {"quantite_totale": 8}, format="json"
        )
        self.assertEqual(reponse.status_code, status.HTTP_200_OK, reponse.data)
        self.produit.refresh_from_db()
        self.assertEqual(self.produit.status, StatutProduit.ACTIVE)
        self.assertEqual(self.produit.quantite_disponible, 3)


class CycleDeVieProduitTests(BaseProduitTests):
    def test_publication_et_pause(self):
        produit = creer_produit(
            self.vendeur, self.categorie, statut=StatutProduit.DRAFT, quantite=3
        )
        publication = self.client.post(f"{URL}{produit.pk}/publish/")
        self.assertEqual(publication.status_code, status.HTTP_200_OK, publication.data)
        produit.refresh_from_db()
        self.assertEqual(produit.status, StatutProduit.ACTIVE)
        self.assertIsNotNone(produit.publie_le)

        pause = self.client.post(f"{URL}{produit.pk}/pause/")
        self.assertEqual(pause.status_code, status.HTTP_200_OK)
        produit.refresh_from_db()
        self.assertEqual(produit.status, StatutProduit.PAUSED)

    def test_publication_sans_stock_donne_rupture(self):
        produit = creer_produit(
            self.vendeur, self.categorie, statut=StatutProduit.DRAFT, quantite=0
        )
        self.client.post(f"{URL}{produit.pk}/publish/")
        produit.refresh_from_db()
        self.assertEqual(produit.status, StatutProduit.OUT_OF_STOCK)

    def test_suppression_archive_sans_effacer(self):
        produit = creer_produit(self.vendeur, self.categorie)
        reponse = self.client.delete(f"{URL}{produit.pk}/")
        self.assertEqual(reponse.status_code, status.HTTP_204_NO_CONTENT)
        produit.refresh_from_db()
        self.assertEqual(produit.status, StatutProduit.ARCHIVED)

    def test_annonce_retiree_par_admin_non_republiable(self):
        produit = creer_produit(
            self.vendeur, self.categorie, statut=StatutProduit.REMOVED
        )
        reponse = self.client.post(f"{URL}{produit.pk}/publish/")
        self.assertEqual(reponse.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("status", reponse.data["errors"])

    def test_statut_non_modifiable_directement(self):
        produit = creer_produit(
            self.vendeur, self.categorie, statut=StatutProduit.DRAFT
        )
        self.client.patch(
            f"{URL}{produit.pk}/", {"status": StatutProduit.ACTIVE}, format="json"
        )
        produit.refresh_from_db()
        self.assertEqual(produit.status, StatutProduit.DRAFT)

    def test_prix_modifiable_sans_toucher_au_stock(self):
        produit = creer_produit(self.vendeur, self.categorie, quantite=4)
        reponse = self.client.patch(
            f"{URL}{produit.pk}/", {"prix": "300000.00"}, format="json"
        )
        self.assertEqual(reponse.status_code, status.HTTP_200_OK, reponse.data)
        produit.refresh_from_db()
        self.assertEqual(produit.prix, Decimal("300000.00"))
        self.assertEqual(produit.inventaire.quantite_totale, 4)


class ModerationProduitTests(APITestCase):
    """Les permissions de groupe pilotent /admin/products/."""

    url = "/api/v1/admin/products/"

    def setUp(self):
        self.categorie = Categorie.objects.create(nom="Vehicules")
        self.vendeur = User.objects.create_user(
            username="vendeur", password="MotDePasse2026"
        )
        self.produit = creer_produit(self.vendeur, self.categorie, titre="Moto Honda")
        self.agent = User.objects.create_user(
            username="agent", password="MotDePasse2026"
        )
        self.client.force_authenticate(self.agent)

    def _donner(self, *codenames):
        groupe = Group.objects.create(name="G-" + "-".join(codenames))
        for codename in codenames:
            groupe.permissions.add(
                Permission.objects.get(
                    content_type__app_label="products", codename=codename
                )
            )
        self.agent.groups.add(groupe)
        self.agent = User.objects.get(pk=self.agent.pk)
        self.client.force_authenticate(self.agent)

    def test_sans_permission_refuse(self):
        self.assertEqual(
            self.client.get(self.url).status_code, status.HTTP_403_FORBIDDEN
        )

    def test_view_produit_autorise_seulement_la_lecture(self):
        self._donner("view_produit")
        liste = self.client.get(self.url)
        self.assertEqual(liste.status_code, status.HTTP_200_OK)
        self.assertEqual(liste.data["count"], 1)

        self.assertEqual(
            self.client.patch(
                f"{self.url}{self.produit.pk}/", {"prix": "1"}, format="json"
            ).status_code,
            status.HTTP_403_FORBIDDEN,
        )
        self.assertEqual(
            self.client.post(
                f"{self.url}{self.produit.pk}/moderate/",
                {"status": "REMOVED", "motif": "Interdit"}, format="json",
            ).status_code,
            status.HTTP_403_FORBIDDEN,
        )
        self.assertEqual(
            self.client.delete(f"{self.url}{self.produit.pk}/").status_code,
            status.HTTP_403_FORBIDDEN,
        )

    def test_change_produit_autorise_la_moderation(self):
        self._donner("view_produit", "change_produit")
        reponse = self.client.post(
            f"{self.url}{self.produit.pk}/moderate/",
            {"status": "REMOVED", "motif": "Produit interdit a la vente"},
            format="json",
        )
        self.assertEqual(reponse.status_code, status.HTTP_200_OK, reponse.data)
        self.produit.refresh_from_db()
        self.assertEqual(self.produit.status, StatutProduit.REMOVED)
        self.assertEqual(self.produit.motif_moderation, "Produit interdit a la vente")

        self.assertEqual(
            self.client.delete(f"{self.url}{self.produit.pk}/").status_code,
            status.HTTP_403_FORBIDDEN,
        )

    def test_retrait_sans_motif_refuse(self):
        self._donner("view_produit", "change_produit")
        reponse = self.client.post(
            f"{self.url}{self.produit.pk}/moderate/",
            {"status": "REMOVED"}, format="json",
        )
        self.assertEqual(reponse.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("motif", reponse.data["errors"])

    def test_moderateur_voit_les_annonces_de_tous(self):
        autre = User.objects.create_user(username="autre", password="MotDePasse2026")
        creer_produit(autre, self.categorie, titre="Velo")
        self._donner("view_produit")
        self.assertEqual(self.client.get(self.url).data["count"], 2)

    def test_remise_en_ligne_sans_stock_donne_rupture(self):
        Inventaire.objects.filter(produit=self.produit).update(quantite_vendue=5)
        self._donner("view_produit", "change_produit")
        reponse = self.client.post(
            f"{self.url}{self.produit.pk}/moderate/",
            {"status": "ACTIVE"}, format="json",
        )
        self.assertEqual(reponse.status_code, status.HTTP_200_OK, reponse.data)
        self.produit.refresh_from_db()
        self.assertEqual(self.produit.status, StatutProduit.OUT_OF_STOCK)
