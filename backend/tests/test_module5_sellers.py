"""Tests du module 5 : vitrine vendeur et abonnements."""
from decimal import Decimal

from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APITestCase

from modules.categories.models import Categorie
from modules.products.models import Inventaire, Produit, StatutProduit
from modules.sellers.models import AbonnementVendeur

User = get_user_model()
URL_PUBLIC = "/api/v1/public/sellers/"
URL_SUIVIS = "/api/v1/following/sellers/"
URL_PRODUITS_SUIVIS = "/api/v1/following/products/"


def creer_produit(owner, categorie, titre, prix="100000", quantite=3,
                  statut=StatutProduit.ACTIVE, **extra):
    produit = Produit.objects.create(
        owner=owner, categorie=categorie, titre=titre, prix=Decimal(prix),
        status=statut, **extra,
    )
    Inventaire.objects.create(produit=produit, quantite_totale=quantite)
    return produit


class BaseVendeurTests(APITestCase):
    def setUp(self):
        self.categorie = Categorie.objects.create(nom="Instruments de musique")

        self.vendeur = User.objects.create_user(
            username="boutique_taba", password="MotDePasse2026",
            nom_commercial="Boutique Taba", nom_complet="Jean Vendeur",
            description="Vente d'instruments de musique.",
            localisation="Taba, Mukaza, Bujumbura Mairie",
            telephone="79000000",
        )
        self.autre_vendeur = User.objects.create_user(
            username="boutique_gitega", password="MotDePasse2026",
            nom_commercial="Boutique Gitega", localisation="Gitega centre",
        )
        self.acheteur = User.objects.create_user(
            username="acheteur", password="MotDePasse2026"
        )

        creer_produit(self.vendeur, self.categorie, "Guitare Yamaha")
        creer_produit(self.vendeur, self.categorie, "Clavier Casio")
        creer_produit(
            self.vendeur, self.categorie, "Batterie en rupture",
            statut=StatutProduit.OUT_OF_STOCK,
        )
        creer_produit(
            self.vendeur, self.categorie, "Brouillon", statut=StatutProduit.DRAFT
        )
        creer_produit(self.autre_vendeur, self.categorie, "Tam-tam")


class VitrinePubliqueTests(BaseVendeurTests):
    def test_visiteur_voit_le_profil_public(self):
        reponse = self.client.get(f"{URL_PUBLIC}{self.vendeur.pk}/")
        self.assertEqual(reponse.status_code, status.HTTP_200_OK)
        self.assertEqual(reponse.data["nom_commercial"], "Boutique Taba")
        self.assertEqual(reponse.data["localisation"], "Taba, Mukaza, Bujumbura Mairie")
        self.assertEqual(reponse.data["nombre_produits_actifs"], 2)
        self.assertEqual(reponse.data["nombre_produits_publies"], 3)
        self.assertEqual(reponse.data["nombre_produits_en_rupture"], 1)
        self.assertEqual(reponse.data["nombre_abonnes"], 0)
        self.assertFalse(reponse.data["est_suivi"])

    def test_email_jamais_expose(self):
        self.vendeur.email = "prive@example.com"
        self.vendeur.save(update_fields=["email"])
        reponse = self.client.get(f"{URL_PUBLIC}{self.vendeur.pk}/")
        self.assertNotIn("email", reponse.data)

    def test_telephone_selon_confidentialite(self):
        reponse = self.client.get(f"{URL_PUBLIC}{self.vendeur.pk}/")
        self.assertIsNone(reponse.data["telephone"])

        self.vendeur.telephone_public = True
        self.vendeur.save(update_fields=["telephone_public"])
        reponse = self.client.get(f"{URL_PUBLIC}{self.vendeur.pk}/")
        self.assertEqual(reponse.data["telephone"], "79000000")

    def test_note_moyenne_en_attente_du_module_11(self):
        reponse = self.client.get(f"{URL_PUBLIC}{self.vendeur.pk}/")
        self.assertIsNone(reponse.data["note_moyenne"])
        self.assertEqual(reponse.data["nombre_evaluations"], 0)

    def test_liste_des_vendeurs(self):
        reponse = self.client.get(URL_PUBLIC)
        self.assertEqual(reponse.status_code, status.HTTP_200_OK)
        noms = sorted(v["username"] for v in reponse.data["results"])
        # L'acheteur, sans annonce visible, n'apparait pas.
        self.assertEqual(noms, ["boutique_gitega", "boutique_taba"])

    def test_liste_filtre_localisation(self):
        reponse = self.client.get(URL_PUBLIC, {"localisation": "taba"})
        noms = [v["username"] for v in reponse.data["results"]]
        self.assertEqual(noms, ["boutique_taba"])

    def test_liste_filtre_produits_min(self):
        reponse = self.client.get(URL_PUBLIC, {"produits_min": 2})
        noms = [v["username"] for v in reponse.data["results"]]
        self.assertEqual(noms, ["boutique_taba"])

    def test_annonces_du_vendeur(self):
        reponse = self.client.get(f"{URL_PUBLIC}{self.vendeur.pk}/products/")
        self.assertEqual(reponse.status_code, status.HTTP_200_OK)
        titres = sorted(p["titre"] for p in reponse.data["results"])
        # Le brouillon n'est jamais expose.
        self.assertEqual(
            titres, ["Batterie en rupture", "Clavier Casio", "Guitare Yamaha"]
        )

    def test_vendeur_desactive_introuvable(self):
        self.vendeur.is_active = False
        self.vendeur.save(update_fields=["is_active"])
        reponse = self.client.get(f"{URL_PUBLIC}{self.vendeur.pk}/")
        self.assertEqual(reponse.status_code, status.HTTP_404_NOT_FOUND)

    def test_evaluations_d_un_vendeur_sans_avis(self):
        """Depuis le module 11, cette route renvoie une vraie reputation.

        Sans aucun avis, la liste est vide et les moyennes valent `null` ;
        le detail des cas (avis masques, repartition par etoile) est teste
        dans `test_module11_reviews.py`.
        """
        reponse = self.client.get(f"{URL_PUBLIC}{self.vendeur.pk}/reviews/")
        self.assertEqual(reponse.status_code, status.HTTP_200_OK)
        self.assertEqual(reponse.data["count"], 0)
        self.assertEqual(reponse.data["results"], [])
        self.assertIsNone(reponse.data["reputation"]["note_vendeur"])
        self.assertEqual(reponse.data["reputation"]["nombre_evaluations"], 0)

    def test_note_moyenne_nulle_sans_avis(self):
        reponse = self.client.get(f"{URL_PUBLIC}{self.vendeur.pk}/")
        self.assertIsNone(reponse.data["note_moyenne"])
        self.assertEqual(reponse.data["nombre_evaluations"], 0)

    def test_ecriture_interdite(self):
        reponse = self.client.post(URL_PUBLIC, {"username": "pirate"}, format="json")
        self.assertEqual(reponse.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)


class AbonnementTests(BaseVendeurTests):
    def setUp(self):
        super().setUp()
        self.client.force_authenticate(self.acheteur)

    def test_suivre_un_vendeur(self):
        reponse = self.client.post(f"{URL_SUIVIS}{self.vendeur.pk}/")
        self.assertEqual(reponse.status_code, status.HTTP_201_CREATED, reponse.data)
        self.assertTrue(reponse.data["cree"])
        self.assertEqual(reponse.data["vendeur"]["nombre_abonnes"], 1)
        self.assertTrue(
            AbonnementVendeur.objects.filter(
                abonne=self.acheteur, vendeur=self.vendeur
            ).exists()
        )

    def test_suivre_deux_fois_sans_doublon(self):
        self.client.post(f"{URL_SUIVIS}{self.vendeur.pk}/")
        reponse = self.client.post(f"{URL_SUIVIS}{self.vendeur.pk}/")
        self.assertEqual(reponse.status_code, status.HTTP_200_OK)
        self.assertFalse(reponse.data["cree"])
        self.assertEqual(
            AbonnementVendeur.objects.filter(
                abonne=self.acheteur, vendeur=self.vendeur
            ).count(),
            1,
        )

    def test_se_suivre_soi_meme_refuse(self):
        reponse = self.client.post(f"{URL_SUIVIS}{self.acheteur.pk}/")
        self.assertEqual(reponse.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(AbonnementVendeur.objects.exists())

    def test_ne_plus_suivre(self):
        self.client.post(f"{URL_SUIVIS}{self.vendeur.pk}/")
        reponse = self.client.delete(f"{URL_SUIVIS}{self.vendeur.pk}/")
        self.assertEqual(reponse.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(AbonnementVendeur.objects.exists())

    def test_ne_plus_suivre_sans_abonnement(self):
        reponse = self.client.delete(f"{URL_SUIVIS}{self.vendeur.pk}/")
        self.assertEqual(reponse.status_code, status.HTTP_404_NOT_FOUND)

    def test_mes_vendeurs_suivis(self):
        self.client.post(f"{URL_SUIVIS}{self.vendeur.pk}/")
        reponse = self.client.get(URL_SUIVIS)
        self.assertEqual(reponse.status_code, status.HTTP_200_OK)
        self.assertEqual(reponse.data["count"], 1)
        ligne = reponse.data["results"][0]
        self.assertEqual(ligne["vendeur"]["username"], "boutique_taba")
        self.assertTrue(ligne["vendeur"]["est_suivi"])
        # Les statistiques du vendeur imbrique doivent etre reelles, pas 0.
        self.assertEqual(ligne["vendeur"]["nombre_produits_actifs"], 2)
        self.assertEqual(ligne["vendeur"]["nombre_abonnes"], 1)

    def test_abonnements_prives(self):
        """Chacun ne voit que ses propres abonnements."""
        AbonnementVendeur.objects.create(
            abonne=self.autre_vendeur, vendeur=self.vendeur
        )
        reponse = self.client.get(URL_SUIVIS)
        self.assertEqual(reponse.data["count"], 0)

    def test_anonyme_refuse(self):
        self.client.force_authenticate(None)
        self.assertEqual(
            self.client.post(f"{URL_SUIVIS}{self.vendeur.pk}/").status_code,
            status.HTTP_401_UNAUTHORIZED,
        )
        self.assertEqual(
            self.client.get(URL_SUIVIS).status_code, status.HTTP_401_UNAUTHORIZED
        )

    def test_compte_suspendu_ne_peut_pas_suivre(self):
        self.acheteur.suspendre("Comportement abusif")
        self.client.force_authenticate(self.acheteur)
        reponse = self.client.post(f"{URL_SUIVIS}{self.vendeur.pk}/")
        self.assertEqual(reponse.status_code, status.HTTP_403_FORBIDDEN)

    def test_est_suivi_sur_le_profil_public(self):
        self.client.post(f"{URL_SUIVIS}{self.vendeur.pk}/")
        reponse = self.client.get(f"{URL_PUBLIC}{self.vendeur.pk}/")
        self.assertTrue(reponse.data["est_suivi"])
        self.assertEqual(reponse.data["nombre_abonnes"], 1)

        autre = self.client.get(f"{URL_PUBLIC}{self.autre_vendeur.pk}/")
        self.assertFalse(autre.data["est_suivi"])


class ProduitsDesVendeursSuivisTests(BaseVendeurTests):
    """Section "Mes vendeurs preferes"."""

    def setUp(self):
        super().setUp()
        self.client.force_authenticate(self.acheteur)

    def test_vide_sans_abonnement(self):
        reponse = self.client.get(URL_PRODUITS_SUIVIS)
        self.assertEqual(reponse.status_code, status.HTTP_200_OK)
        self.assertEqual(reponse.data["count"], 0)

    def test_annonces_des_vendeurs_suivis(self):
        self.client.post(f"{URL_SUIVIS}{self.vendeur.pk}/")
        reponse = self.client.get(URL_PRODUITS_SUIVIS)
        titres = sorted(p["titre"] for p in reponse.data["results"])
        self.assertEqual(
            titres, ["Batterie en rupture", "Clavier Casio", "Guitare Yamaha"]
        )
        # Les annonces des vendeurs non suivis n'y sont pas.
        self.assertNotIn("Tam-tam", titres)

    def test_le_catalogue_general_reste_complet(self):
        """Suivre un vendeur ne retire rien du catalogue general."""
        self.client.post(f"{URL_SUIVIS}{self.vendeur.pk}/")
        catalogue = self.client.get("/api/v1/public/products/")
        titres = [p["titre"] for p in catalogue.data["results"]]
        self.assertIn("Tam-tam", titres)
        self.assertEqual(catalogue.data["count"], 4)

    def test_anonyme_refuse(self):
        self.client.force_authenticate(None)
        reponse = self.client.get(URL_PRODUITS_SUIVIS)
        self.assertEqual(reponse.status_code, status.HTTP_401_UNAUTHORIZED)
