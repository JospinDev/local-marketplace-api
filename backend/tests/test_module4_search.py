"""Tests du module 4 : catalogue public, filtres, tris, proximite.

Les scenarios 1 et 2 du cahier des charges sont couverts ici :
publication visible par un visiteur, puis recherche filtree par prix et
localisation.
"""
from decimal import Decimal

from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APITestCase

from modules.categories.models import Categorie
from modules.products.models import Inventaire, Produit, StatutProduit

User = get_user_model()
URL = "/api/v1/public/products/"


class CataloguePublicTests(APITestCase):
    def setUp(self):
        self.musique = Categorie.objects.create(nom="Instruments de musique")
        self.guitares = Categorie.objects.create(nom="Guitares", parent=self.musique)
        self.vehicules = Categorie.objects.create(nom="Vehicules")

        self.vendeur = User.objects.create_user(
            username="vendeur_buja", password="MotDePasse2026",
            localisation="Mukaza, Bujumbura Mairie", telephone="79000000",
        )
        self.vendeur_gitega = User.objects.create_user(
            username="vendeur_gitega", password="MotDePasse2026",
            localisation="Gitega",
        )

        self.guitare = self._creer(
            "Guitare acoustique Yamaha", self.guitares, "250000", 5,
            owner=self.vendeur,
            localisation="Taba, Mukaza, Bujumbura Mairie",
            latitude=Decimal("-3.383000"), longitude=Decimal("29.361700"),
        )
        self.telephone = self._creer(
            "Telephone Samsung A15", self.vehicules, "450000", 2,
            owner=self.vendeur,
            localisation="Ntahangwa, Bujumbura Mairie",
            nombre_vues=50,
        )
        self.vehicule = self._creer(
            "Voiture Toyota", self.vehicules, "8000000", 1,
            owner=self.vendeur_gitega, localisation="Gitega centre",
            latitude=Decimal("-3.427500"), longitude=Decimal("29.925000"),
        )
        # Annonces qui ne doivent JAMAIS apparaitre publiquement.
        self.brouillon = self._creer(
            "Brouillon cache", self.guitares, "1000", 1,
            owner=self.vendeur, statut=StatutProduit.DRAFT,
            localisation="Mukaza",
        )
        self.retiree = self._creer(
            "Annonce retiree", self.guitares, "1000", 1,
            owner=self.vendeur, statut=StatutProduit.REMOVED,
            localisation="Mukaza",
        )
        self.en_pause = self._creer(
            "Annonce en pause", self.guitares, "1000", 1,
            owner=self.vendeur, statut=StatutProduit.PAUSED,
            localisation="Mukaza",
        )

    def _creer(self, titre, categorie, prix, quantite, owner,
               statut=StatutProduit.ACTIVE, **extra):
        produit = Produit.objects.create(
            owner=owner, categorie=categorie, titre=titre,
            prix=Decimal(prix), status=statut, **extra,
        )
        Inventaire.objects.create(produit=produit, quantite_totale=quantite)
        return produit

    # --------------------------------------------------------------- acces
    def test_visiteur_non_connecte_voit_les_annonces_actives(self):
        """Scenario 1 : un visiteur voit l'annonce publiee."""
        reponse = self.client.get(URL)
        self.assertEqual(reponse.status_code, status.HTTP_200_OK)
        titres = [p["titre"] for p in reponse.data["results"]]
        self.assertIn("Guitare acoustique Yamaha", titres)
        self.assertNotIn("Brouillon cache", titres)
        self.assertNotIn("Annonce retiree", titres)
        self.assertNotIn("Annonce en pause", titres)
        self.assertEqual(reponse.data["count"], 3)

    def test_annonces_d_un_compte_desactive_masquees(self):
        self.vendeur_gitega.is_active = False
        self.vendeur_gitega.save(update_fields=["is_active"])
        reponse = self.client.get(URL)
        titres = [p["titre"] for p in reponse.data["results"]]
        self.assertNotIn("Voiture Toyota", titres)

    def test_statut_non_contournable_par_url(self):
        """Un parametre `status=DRAFT` ne doit pas exposer les brouillons."""
        reponse = self.client.get(URL, {"status": "DRAFT"})
        self.assertEqual(reponse.status_code, status.HTTP_200_OK)
        titres = [p["titre"] for p in reponse.data["results"]]
        self.assertNotIn("Brouillon cache", titres)
        self.assertEqual(reponse.data["count"], 3)

    def test_ecriture_interdite(self):
        reponse = self.client.post(URL, {"titre": "Pirate"}, format="json")
        self.assertEqual(reponse.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

    def test_detail_incremente_les_vues(self):
        avant = self.guitare.nombre_vues
        reponse = self.client.get(f"{URL}{self.guitare.pk}/")
        self.assertEqual(reponse.status_code, status.HTTP_200_OK)
        self.assertEqual(reponse.data["nombre_vues"], avant + 1)
        self.guitare.refresh_from_db()
        self.assertEqual(self.guitare.nombre_vues, avant + 1)

    def test_detail_masque_le_telephone_non_public(self):
        reponse = self.client.get(f"{URL}{self.guitare.pk}/")
        self.assertIsNone(reponse.data["vendeur"]["telephone"])

        self.vendeur.telephone_public = True
        self.vendeur.save(update_fields=["telephone_public"])
        reponse = self.client.get(f"{URL}{self.guitare.pk}/")
        self.assertEqual(reponse.data["vendeur"]["telephone"], "79000000")

    def test_detail_brouillon_introuvable(self):
        reponse = self.client.get(f"{URL}{self.brouillon.pk}/")
        self.assertEqual(reponse.status_code, status.HTTP_404_NOT_FOUND)

    # -------------------------------------------------------------- filtres
    def test_recherche_par_mots_cles(self):
        reponse = self.client.get(f"{URL}search/", {"q": "guitare"})
        titres = [p["titre"] for p in reponse.data["results"]]
        self.assertEqual(titres, ["Guitare acoustique Yamaha"])

    def test_recherche_par_mot_cle_de_categorie(self):
        reponse = self.client.get(f"{URL}search/", {"q": "vehicul"})
        titres = sorted(p["titre"] for p in reponse.data["results"])
        self.assertEqual(titres, ["Telephone Samsung A15", "Voiture Toyota"])

    def test_filtre_prix_min_max(self):
        """Tous les produits entre 200 000 et 500 000 BIF."""
        reponse = self.client.get(URL, {"prix_min": 200000, "prix_max": 500000})
        titres = sorted(p["titre"] for p in reponse.data["results"])
        self.assertEqual(
            titres, ["Guitare acoustique Yamaha", "Telephone Samsung A15"]
        )

    def test_filtre_prix_lookups_explicites(self):
        reponse = self.client.get(URL, {"prix__lte": 450000})
        self.assertEqual(reponse.data["count"], 2)

    def test_filtre_localisation_icontains(self):
        """Scenario 2 : les guitares disponibles a Bujumbura."""
        reponse = self.client.get(
            URL, {"localisation": "bujumbura", "q": "guitare"}
        )
        titres = [p["titre"] for p in reponse.data["results"]]
        self.assertEqual(titres, ["Guitare acoustique Yamaha"])

    def test_filtre_localisation_quartier(self):
        """Le client tape le nom du quartier : seul ce produit sort."""
        reponse = self.client.get(URL, {"localisation": "taba"})
        titres = [p["titre"] for p in reponse.data["results"]]
        self.assertEqual(titres, ["Guitare acoustique Yamaha"])

    def test_filtre_localisation_toutes_casses(self):
        for fragment in ("Taba", "taba", "TABA", "TaBa"):
            reponse = self.client.get(URL, {"localisation": fragment})
            titres = [p["titre"] for p in reponse.data["results"]]
            self.assertEqual(
                titres, ["Guitare acoustique Yamaha"], f"fragment={fragment}"
            )

    def test_filtre_localisation_ville(self):
        reponse = self.client.get(URL, {"localisation": "gitega"})
        titres = [p["titre"] for p in reponse.data["results"]]
        self.assertEqual(titres, ["Voiture Toyota"])

    def test_filtre_categorie_et_arbre(self):
        directe = self.client.get(URL, {"categorie": self.guitares.pk})
        self.assertEqual(directe.data["count"], 1)

        # La categorie parente ne contient aucun produit en direct...
        parente = self.client.get(URL, {"categorie": self.musique.pk})
        self.assertEqual(parente.data["count"], 0)

        # ... mais l'arbre remonte les sous-categories.
        arbre = self.client.get(URL, {"categorie_arbre": self.musique.pk})
        self.assertEqual(arbre.data["count"], 1)

    def test_filtre_etat(self):
        self.guitare.etat = "OCCASION"
        self.guitare.save(update_fields=["etat"])
        reponse = self.client.get(URL, {"etat": "OCCASION"})
        titres = [p["titre"] for p in reponse.data["results"]]
        self.assertEqual(titres, ["Guitare acoustique Yamaha"])

    def test_filtre_disponibilite(self):
        Inventaire.objects.filter(produit=self.telephone).update(quantite_vendue=2)
        disponibles = self.client.get(URL, {"disponible": "true"})
        titres = sorted(p["titre"] for p in disponibles.data["results"])
        self.assertEqual(titres, ["Guitare acoustique Yamaha", "Voiture Toyota"])

        epuises = self.client.get(URL, {"disponible": "false"})
        titres = [p["titre"] for p in epuises.data["results"]]
        self.assertEqual(titres, ["Telephone Samsung A15"])

    def test_filtre_quantite_minimale(self):
        reponse = self.client.get(URL, {"quantite_min": 3})
        titres = [p["titre"] for p in reponse.data["results"]]
        self.assertEqual(titres, ["Guitare acoustique Yamaha"])

    def test_filtre_vendeur(self):
        reponse = self.client.get(URL, {"owner_username": "vendeur_gitega"})
        titres = [p["titre"] for p in reponse.data["results"]]
        self.assertEqual(titres, ["Voiture Toyota"])

    def test_filtres_combinables(self):
        reponse = self.client.get(
            URL,
            {
                "localisation": "bujumbura",
                "prix_min": 100000,
                "prix_max": 300000,
                "disponible": "true",
                "etat": "NEUF",
            },
        )
        titres = [p["titre"] for p in reponse.data["results"]]
        self.assertEqual(titres, ["Guitare acoustique Yamaha"])

    # ----------------------------------------------------------------- tris
    def test_tri_prix_croissant_et_decroissant(self):
        croissant = self.client.get(URL, {"ordering": "prix"})
        prix = [Decimal(p["prix"]) for p in croissant.data["results"]]
        self.assertEqual(prix, sorted(prix))

        decroissant = self.client.get(URL, {"ordering": "-prix"})
        prix = [Decimal(p["prix"]) for p in decroissant.data["results"]]
        self.assertEqual(prix, sorted(prix, reverse=True))

    def test_tri_popularite(self):
        reponse = self.client.get(f"{URL}popular/")
        titres = [p["titre"] for p in reponse.data["results"]]
        self.assertEqual(titres[0], "Telephone Samsung A15")

    def test_dernieres_annonces(self):
        reponse = self.client.get(f"{URL}latest/")
        self.assertEqual(reponse.status_code, status.HTTP_200_OK)
        self.assertEqual(reponse.data["count"], 3)

    def test_mises_en_avant(self):
        vide = self.client.get(f"{URL}featured/")
        self.assertEqual(vide.data["count"], 0)

        self.guitare.est_mis_en_avant = True
        self.guitare.save(update_fields=["est_mis_en_avant"])
        reponse = self.client.get(f"{URL}featured/")
        titres = [p["titre"] for p in reponse.data["results"]]
        self.assertEqual(titres, ["Guitare acoustique Yamaha"])

    def test_pagination(self):
        reponse = self.client.get(URL, {"page_size": 2})
        self.assertEqual(len(reponse.data["results"]), 2)
        self.assertEqual(reponse.data["count"], 3)
        self.assertIsNotNone(reponse.data["next"])

    # ----------------------------------------------------------- proximite
    def test_distance_nulle_sans_coordonnees_client(self):
        reponse = self.client.get(URL)
        for produit in reponse.data["results"]:
            self.assertIsNone(produit["distance_km"])

    def test_distance_calculee_et_tri_par_proximite(self):
        # Point de reference : centre de Bujumbura.
        parametres = {
            "latitude": "-3.3830", "longitude": "29.3617", "ordering": "distance_km",
        }
        reponse = self.client.get(URL, parametres)
        self.assertEqual(reponse.status_code, status.HTTP_200_OK, reponse.data)

        avec_coords = [
            p for p in reponse.data["results"] if p["distance_km"] is not None
        ]
        self.assertEqual(len(avec_coords), 2)
        # La guitare est au point de reference, la voiture est a Gitega.
        self.assertEqual(avec_coords[0]["titre"], "Guitare acoustique Yamaha")
        self.assertLess(avec_coords[0]["distance_km"], 1)
        self.assertGreater(avec_coords[1]["distance_km"], 50)

    def test_filtre_rayon_km(self):
        reponse = self.client.get(
            URL,
            {"latitude": "-3.3830", "longitude": "29.3617", "rayon_km": "10"},
        )
        titres = [p["titre"] for p in reponse.data["results"]]
        self.assertEqual(titres, ["Guitare acoustique Yamaha"])

    def test_coordonnees_invalides_rejetees(self):
        """Une coordonnee malformee ou hors bornes donne une erreur claire."""
        malformee = self.client.get(URL, {"latitude": "abc", "longitude": "29.36"})
        self.assertEqual(malformee.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("latitude", malformee.data["errors"])

        hors_bornes = self.client.get(URL, {"latitude": "-3.38", "longitude": "999"})
        self.assertEqual(hors_bornes.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("longitude", hors_bornes.data["errors"])

    def test_latitude_seule_sans_effet(self):
        """Sans les deux coordonnees, le tri par proximite reste inoffensif."""
        reponse = self.client.get(
            URL, {"latitude": "-3.3830", "ordering": "distance_km"}
        )
        self.assertEqual(reponse.status_code, status.HTTP_200_OK, reponse.data)
        self.assertEqual(reponse.data["count"], 3)
        for produit in reponse.data["results"]:
            self.assertIsNone(produit["distance_km"])

    def test_rayon_sans_coordonnees_ignore(self):
        reponse = self.client.get(URL, {"rayon_km": "5"})
        self.assertEqual(reponse.status_code, status.HTTP_200_OK)
        self.assertEqual(reponse.data["count"], 3)
