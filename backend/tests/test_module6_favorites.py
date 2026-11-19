"""Tests du module 6 : favoris prives, alertes de prix et de disponibilite."""
from decimal import Decimal

from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APITestCase

from modules.categories.models import Categorie
from modules.favorites.models import Favori
from modules.products.models import Inventaire, Produit, StatutProduit

User = get_user_model()
URL = "/api/v1/favorites/products/"


class BaseFavorisTests(APITestCase):
    def setUp(self):
        self.categorie = Categorie.objects.create(nom="Electronique")
        self.vendeur = User.objects.create_user(
            username="vendeur", password="MotDePasse2026"
        )
        self.acheteur = User.objects.create_user(
            username="acheteur", password="MotDePasse2026"
        )
        self.autre = User.objects.create_user(
            username="autre_acheteur", password="MotDePasse2026"
        )

        self.produit = self._creer("Telephone Samsung", "450000")
        self.brouillon = self._creer(
            "Brouillon", "1000", statut=StatutProduit.DRAFT
        )
        self.client.force_authenticate(self.acheteur)

    def _creer(self, titre, prix, quantite=5, statut=StatutProduit.ACTIVE, **extra):
        produit = Produit.objects.create(
            owner=self.vendeur, categorie=self.categorie, titre=titre,
            prix=Decimal(prix), status=statut, localisation="Mukaza", **extra,
        )
        Inventaire.objects.create(produit=produit, quantite_totale=quantite)
        return produit


class AjoutRetraitTests(BaseFavorisTests):
    def test_ajouter_aux_favoris(self):
        reponse = self.client.post(f"{URL}{self.produit.pk}/")
        self.assertEqual(reponse.status_code, status.HTTP_201_CREATED, reponse.data)
        self.assertTrue(reponse.data["cree"])

        favori = Favori.objects.get(utilisateur=self.acheteur, produit=self.produit)
        # Le prix du jour est conserve pour detecter les variations.
        self.assertEqual(favori.prix_a_l_ajout, Decimal("450000.00"))

    def test_pas_de_doublon(self):
        """Regle : on ne peut pas ajouter deux fois le meme produit."""
        self.client.post(f"{URL}{self.produit.pk}/")
        reponse = self.client.post(f"{URL}{self.produit.pk}/")
        self.assertEqual(reponse.status_code, status.HTTP_200_OK)
        self.assertFalse(reponse.data["cree"])
        self.assertEqual(Favori.objects.count(), 1)

    def test_retirer_des_favoris(self):
        self.client.post(f"{URL}{self.produit.pk}/")
        reponse = self.client.delete(f"{URL}{self.produit.pk}/")
        self.assertEqual(reponse.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(Favori.objects.exists())

    def test_retirer_un_non_favori(self):
        reponse = self.client.delete(f"{URL}{self.produit.pk}/")
        self.assertEqual(reponse.status_code, status.HTTP_404_NOT_FOUND)

    def test_produit_non_visible_refuse(self):
        reponse = self.client.post(f"{URL}{self.brouillon.pk}/")
        self.assertEqual(reponse.status_code, status.HTTP_404_NOT_FOUND)
        self.assertFalse(Favori.objects.exists())

    def test_produit_inexistant(self):
        reponse = self.client.post(f"{URL}999999/")
        self.assertEqual(reponse.status_code, status.HTTP_404_NOT_FOUND)

    def test_anonyme_refuse(self):
        self.client.force_authenticate(None)
        self.assertEqual(
            self.client.post(f"{URL}{self.produit.pk}/").status_code,
            status.HTTP_401_UNAUTHORIZED,
        )
        self.assertEqual(
            self.client.get(URL).status_code, status.HTTP_401_UNAUTHORIZED
        )


class ConfidentialiteTests(BaseFavorisTests):
    def test_favoris_prives(self):
        """Regle : les favoris sont prives."""
        Favori.objects.create(
            utilisateur=self.autre, produit=self.produit,
            prix_a_l_ajout=self.produit.prix,
        )
        reponse = self.client.get(URL)
        self.assertEqual(reponse.data["count"], 0)

        self.client.force_authenticate(self.autre)
        self.assertEqual(self.client.get(URL).data["count"], 1)

    def test_retirer_le_favori_d_autrui_impossible(self):
        Favori.objects.create(
            utilisateur=self.autre, produit=self.produit,
            prix_a_l_ajout=self.produit.prix,
        )
        reponse = self.client.delete(f"{URL}{self.produit.pk}/")
        self.assertEqual(reponse.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(Favori.objects.count(), 1)


class AlertesTests(BaseFavorisTests):
    def setUp(self):
        super().setUp()
        self.client.post(f"{URL}{self.produit.pk}/")

    def _ligne(self):
        reponse = self.client.get(URL)
        self.assertEqual(reponse.status_code, status.HTTP_200_OK)
        return reponse.data["results"][0]

    def test_aucune_alerte_quand_rien_ne_change(self):
        ligne = self._ligne()
        self.assertTrue(ligne["est_toujours_disponible"])
        self.assertFalse(ligne["est_retire"])
        self.assertFalse(ligne["prix_a_change"])
        self.assertIsNone(ligne["alerte"])

    def test_hausse_de_prix_signalee(self):
        self.produit.prix = Decimal("500000.00")
        self.produit.save(update_fields=["prix"])
        ligne = self._ligne()
        self.assertTrue(ligne["prix_a_change"])
        self.assertEqual(Decimal(ligne["variation_prix"]), Decimal("50000.00"))
        self.assertIn("augmente", ligne["alerte"])

    def test_baisse_de_prix_signalee(self):
        self.produit.prix = Decimal("400000.00")
        self.produit.save(update_fields=["prix"])
        ligne = self._ligne()
        self.assertEqual(Decimal(ligne["variation_prix"]), Decimal("-50000.00"))
        self.assertIn("baisse", ligne["alerte"])

    def test_rupture_de_stock_signalee(self):
        Inventaire.objects.filter(produit=self.produit).update(quantite_vendue=5)
        self.produit.status = StatutProduit.OUT_OF_STOCK
        self.produit.save(update_fields=["status"])
        ligne = self._ligne()
        self.assertFalse(ligne["est_toujours_disponible"])
        self.assertFalse(ligne["est_retire"])
        self.assertIn("rupture", ligne["alerte"])

    def test_annonce_retiree_signalee(self):
        """Regle : un produit supprime n'est plus propose comme disponible."""
        self.produit.status = StatutProduit.REMOVED
        self.produit.save(update_fields=["status"])
        ligne = self._ligne()
        self.assertTrue(ligne["est_retire"])
        self.assertFalse(ligne["est_toujours_disponible"])
        self.assertIn("retiree", ligne["alerte"])

    def test_vendeur_desactive_signale(self):
        self.vendeur.is_active = False
        self.vendeur.save(update_fields=["is_active"])
        ligne = self._ligne()
        self.assertTrue(ligne["est_retire"])

    def test_favori_conserve_apres_retrait_de_l_annonce(self):
        """Le favori reste visible, avec son alerte, au lieu de disparaitre."""
        self.produit.status = StatutProduit.ARCHIVED
        self.produit.save(update_fields=["status"])
        reponse = self.client.get(URL)
        self.assertEqual(reponse.data["count"], 1)


class FiltresFavorisTests(BaseFavorisTests):
    def setUp(self):
        super().setUp()
        self.disponible = self.produit
        self.epuise = self._creer("Casque audio", "60000", quantite=0)
        self.retire = self._creer("Clavier", "25000")

        for produit in (self.disponible, self.epuise, self.retire):
            Favori.objects.create(
                utilisateur=self.acheteur, produit=produit,
                prix_a_l_ajout=produit.prix,
            )

        self.retire.status = StatutProduit.REMOVED
        self.retire.save(update_fields=["status"])

    def test_filtre_disponible(self):
        reponse = self.client.get(URL, {"disponible": "true"})
        titres = [f["produit"]["titre"] for f in reponse.data["results"]]
        self.assertEqual(titres, ["Telephone Samsung"])

    def test_filtre_retire(self):
        reponse = self.client.get(URL, {"retire": "true"})
        titres = [f["produit"]["titre"] for f in reponse.data["results"]]
        self.assertEqual(titres, ["Clavier"])

    def test_filtre_prix_a_change(self):
        self.disponible.prix = Decimal("470000.00")
        self.disponible.save(update_fields=["prix"])
        reponse = self.client.get(URL, {"prix_a_change": "true"})
        titres = [f["produit"]["titre"] for f in reponse.data["results"]]
        self.assertEqual(titres, ["Telephone Samsung"])

    def test_filtre_prix_min_max(self):
        reponse = self.client.get(URL, {"prix_min": 50000, "prix_max": 100000})
        titres = [f["produit"]["titre"] for f in reponse.data["results"]]
        self.assertEqual(titres, ["Casque audio"])

    def test_filtre_localisation(self):
        reponse = self.client.get(URL, {"localisation": "mukaza"})
        self.assertEqual(reponse.data["count"], 3)

    def test_tri_par_prix(self):
        reponse = self.client.get(URL, {"ordering": "produit__prix"})
        prix = [Decimal(f["prix_actuel"]) for f in reponse.data["results"]]
        self.assertEqual(prix, sorted(prix))
