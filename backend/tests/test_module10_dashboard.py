"""Tests du module 10 : tableau de bord vendeur.

Le test central est `test_le_revenu_ne_compte_pas_les_reservations` : il
reproduit chiffre pour chiffre le tableau du paragraphe E du cahier des
charges (5 reservations a 250 000, 3 ventes confirmees a 150 000, revenu
declare = 150 000).
"""
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from modules.categories.models import Categorie
from modules.messaging.models import Conversation
from modules.products.models import Inventaire, Produit, StatutProduit
from modules.reservations.models import Reservation, StatutReservation
from modules.reservations.services import ReservationService
from modules.reviews.services import EvaluationService
from modules.sales.models import Vente
from modules.sales.services import VenteService

User = get_user_model()
URL = "/api/v1/seller-dashboard/"


class BaseTableauDeBordTests(APITestCase):
    def setUp(self):
        self.categorie = Categorie.objects.create(nom="Electronique")
        self.autre_categorie = Categorie.objects.create(nom="Mobilier")
        self.vendeur = User.objects.create_user(
            username="vendeur", password="MotDePasse2026"
        )
        self.acheteur = User.objects.create_user(
            username="acheteur", password="MotDePasse2026"
        )
        self.tiers = User.objects.create_user(
            username="tiers", password="MotDePasse2026"
        )
        self.client.force_authenticate(self.vendeur)

    def _creer(
        self, titre, prix, quantite=10, statut=StatutProduit.ACTIVE,
        categorie=None, owner=None, vues=0,
    ):
        produit = Produit.objects.create(
            owner=owner or self.vendeur,
            categorie=categorie or self.categorie,
            titre=titre, prix=Decimal(prix), status=statut,
            localisation="Kinindo", nombre_vues=vues,
        )
        Inventaire.objects.create(produit=produit, quantite_totale=quantite)
        return produit

    def _vente_payee(self, produit, acheteur=None, quantite=1, prix=None):
        vente = VenteService.enregistrer_vente_directe(
            produit, self.vendeur, acheteur or self.acheteur, quantite,
            prix_unitaire=prix,
        )
        return VenteService.confirmer_paiement(vente, self.vendeur)

    def _reservation_confirmee(self, produit, acheteur=None, quantite=1):
        demande = ReservationService.demander(
            produit, acheteur or self.acheteur, quantite
        )
        return ReservationService.accepter(demande, self.vendeur)


class VueGeneraleTests(BaseTableauDeBordTests):
    def test_comptages_de_la_vue_generale(self):
        actif = self._creer("Telephone", "450000", quantite=5)
        self._creer("Brouillon", "1000", statut=StatutProduit.DRAFT)
        epuise = self._creer("Epuise", "2000", quantite=1)
        VenteService.enregistrer_vente_directe(
            epuise, self.vendeur, self.tiers, 1
        )
        epuise.refresh_from_db()
        self.assertEqual(epuise.status, StatutProduit.OUT_OF_STOCK)

        self._reservation_confirmee(actif, quantite=2)
        ReservationService.demander(actif, self.tiers, 1)
        self._vente_payee(actif, quantite=1)
        Conversation.objects.create(
            acheteur=self.acheteur, vendeur=self.vendeur, produit=actif,
            prix_initial=actif.prix,
        )

        reponse = self.client.get(f"{URL}overview/")
        self.assertEqual(reponse.status_code, status.HTTP_200_OK, reponse.data)
        donnees = reponse.data

        self.assertEqual(donnees["produits_publies"], 2)  # actif + epuise
        self.assertEqual(donnees["produits_disponibles"], 1)
        self.assertEqual(donnees["produits_en_rupture"], 1)
        self.assertEqual(donnees["produits_total"], 3)  # brouillon compris
        self.assertEqual(donnees["demandes_de_reservation_en_attente"], 1)
        self.assertEqual(donnees["reservations_en_cours"], 1)
        self.assertEqual(donnees["ventes_confirmees"], 1)
        self.assertEqual(donnees["nombre_clients"], 1)
        self.assertEqual(donnees["nombre_conversations"], 1)

    def test_la_note_moyenne_vient_du_module_11(self):
        produit = self._creer("Enceinte", "80000")
        vente = self._vente_payee(produit)
        VenteService.confirmer_reception(vente, self.acheteur)
        EvaluationService.creer(
            vente, self.acheteur, note_produit=5, note_vendeur=4
        )

        reponse = self.client.get(f"{URL}overview/")
        self.assertEqual(reponse.data["note_moyenne_vendeur"], 4.0)
        self.assertEqual(reponse.data["nombre_evaluations"], 1)

    def test_chaque_vendeur_ne_voit_que_ses_chiffres(self):
        self._creer("A moi", "1000")
        self._creer("A lui", "1000", owner=self.tiers)

        reponse = self.client.get(f"{URL}overview/")
        self.assertEqual(reponse.data["produits_total"], 1)

        self.client.force_authenticate(self.tiers)
        reponse = self.client.get(f"{URL}overview/")
        self.assertEqual(reponse.data["produits_total"], 1)

    def test_vendeur_sans_activite(self):
        reponse = self.client.get(f"{URL}overview/")
        self.assertEqual(reponse.status_code, status.HTTP_200_OK)
        self.assertEqual(reponse.data["produits_publies"], 0)
        self.assertEqual(reponse.data["ventes_confirmees"], 0)
        self.assertIsNone(reponse.data["note_moyenne_vendeur"])

    def test_anonyme_refuse(self):
        self.client.force_authenticate(None)
        for chemin in ("overview", "revenue", "inventory", "reservations", "sales"):
            self.assertEqual(
                self.client.get(f"{URL}{chemin}/").status_code,
                status.HTTP_401_UNAUTHORIZED,
                chemin,
            )


class RevenusTests(BaseTableauDeBordTests):
    def test_le_revenu_ne_compte_pas_les_reservations(self):
        """Le tableau du paragraphe E du cahier des charges, a l'identique.

        5 unites reservees a 50 000 = 250 000 de valeur immobilisee.
        3 unites vendues et confirmees  = 150 000 de revenu declare.
        Le tableau de bord doit afficher 150 000, et non 250 000.
        """
        produit = self._creer("Chaise", "50000", quantite=10)
        self._reservation_confirmee(produit, acheteur=self.acheteur, quantite=5)
        self._vente_payee(produit, acheteur=self.tiers, quantite=3)

        reponse = self.client.get(f"{URL}revenue/")
        self.assertEqual(reponse.status_code, status.HTTP_200_OK, reponse.data)

        self.assertEqual(reponse.data["chiffre_affaires_total"], "150000.00")
        self.assertEqual(reponse.data["quantite_vendue"], 3)
        # La valeur des reservations est exposee a part, jamais additionnee.
        self.assertEqual(reponse.data["valeur_reservations_en_cours"], "250000.00")

    def test_vente_non_confirmee_exclue(self):
        produit = self._creer("Table", "100000")
        VenteService.enregistrer_vente_directe(
            produit, self.vendeur, self.acheteur, 1
        )
        reponse = self.client.get(f"{URL}revenue/")
        self.assertEqual(reponse.data["chiffre_affaires_total"], "0.00")
        self.assertEqual(reponse.data["ventes_en_attente_de_confirmation"], 1)

    def test_vente_annulee_exclue(self):
        produit = self._creer("Lampe", "20000")
        vente = self._vente_payee(produit, quantite=2)
        avant = self.client.get(f"{URL}revenue/").data
        self.assertEqual(avant["chiffre_affaires_total"], "40000.00")

        VenteService.annuler(vente, self.vendeur, "Produit defectueux")
        apres = self.client.get(f"{URL}revenue/").data
        self.assertEqual(apres["chiffre_affaires_total"], "0.00")

    def test_revenus_par_periode(self):
        produit = self._creer("Radio", "30000", quantite=20)
        recente = self._vente_payee(produit, quantite=1)
        ancienne = self._vente_payee(produit, acheteur=self.tiers, quantite=2)

        # L'ancienne vente a ete encaissee il y a deux mois.
        Vente.objects.filter(pk=ancienne.pk).update(
            confirmee_le=timezone.now() - timedelta(days=60)
        )

        donnees = self.client.get(f"{URL}revenue/").data
        self.assertEqual(donnees["chiffre_affaires_total"], "90000.00")
        self.assertEqual(donnees["revenus_du_jour"], "30000.00")
        self.assertEqual(donnees["revenus_de_la_semaine"], "30000.00")
        self.assertEqual(donnees["revenus_du_mois"], "30000.00")
        self.assertEqual(recente.montant_total, Decimal("30000.00"))

    def test_revenus_par_produit_et_par_categorie(self):
        telephone = self._creer("Telephone", "400000", quantite=5)
        chaise = self._creer(
            "Chaise", "50000", quantite=10, categorie=self.autre_categorie
        )
        self._vente_payee(telephone, quantite=1)
        self._vente_payee(chaise, acheteur=self.tiers, quantite=4)

        donnees = self.client.get(f"{URL}revenue/").data

        par_produit = {ligne["titre"]: ligne for ligne in donnees["par_produit"]}
        self.assertEqual(par_produit["Telephone"]["revenu"], "400000.00")
        self.assertEqual(par_produit["Chaise"]["quantite_vendue"], 4)
        self.assertEqual(par_produit["Chaise"]["revenu"], "200000.00")
        # Trie par revenu decroissant.
        self.assertEqual(donnees["par_produit"][0]["titre"], "Telephone")

        par_categorie = {ligne["nom"]: ligne for ligne in donnees["par_categorie"]}
        self.assertEqual(par_categorie["Electronique"]["revenu"], "400000.00")
        self.assertEqual(par_categorie["Mobilier"]["revenu"], "200000.00")

    def test_le_prix_fige_est_respecte(self):
        """Changer le prix de l'annonce ne reecrit pas le revenu passe."""
        produit = self._creer("Ventilateur", "60000", quantite=5)
        self._vente_payee(produit, quantite=2)

        produit.prix = Decimal("999000.00")
        produit.save(update_fields=["prix"])

        donnees = self.client.get(f"{URL}revenue/").data
        self.assertEqual(donnees["chiffre_affaires_total"], "120000.00")

    def test_prix_negocie_pris_en_compte(self):
        produit = self._creer("Casque", "40000", quantite=5)
        self._vente_payee(produit, quantite=2, prix=Decimal("35000.00"))
        donnees = self.client.get(f"{URL}revenue/").data
        self.assertEqual(donnees["chiffre_affaires_total"], "70000.00")

    def test_vendeur_sans_vente(self):
        donnees = self.client.get(f"{URL}revenue/").data
        self.assertEqual(donnees["chiffre_affaires_total"], "0.00")
        self.assertEqual(donnees["quantite_vendue"], 0)
        self.assertEqual(donnees["par_produit"], [])


class StocksTests(BaseTableauDeBordTests):
    def test_les_quatre_quantites(self):
        """Section C : stock total 100, vendu 25, reserve 15, disponible 60."""
        produit = self._creer("Sac de ciment", "25000", quantite=100)
        self._vente_payee(produit, quantite=25)
        self._reservation_confirmee(produit, acheteur=self.tiers, quantite=15)

        donnees = self.client.get(f"{URL}inventory/").data
        self.assertEqual(donnees["stock_total"], 100)
        self.assertEqual(donnees["quantite_vendue"], 25)
        self.assertEqual(donnees["quantite_reservee"], 15)
        self.assertEqual(donnees["quantite_disponible"], 60)

        # Valeur du stock encore vendable : 60 x 25 000.
        self.assertEqual(donnees["valeur_stock_disponible"], "1500000.00")
        self.assertEqual(donnees["valeur_reservations_en_cours"], "375000.00")

    def test_detail_par_produit(self):
        premier = self._creer("Ampoule", "2000", quantite=50)
        self._creer("Bougie", "500", quantite=30)
        self._vente_payee(premier, quantite=10)

        donnees = self.client.get(f"{URL}inventory/").data
        lignes = {ligne["titre"]: ligne for ligne in donnees["par_produit"]}
        self.assertEqual(lignes["Ampoule"]["quantite_vendue"], 10)
        self.assertEqual(lignes["Ampoule"]["quantite_disponible"], 40)
        self.assertEqual(lignes["Bougie"]["quantite_disponible"], 30)

    def test_le_total_reste_coherent(self):
        produit = self._creer("Brique", "300", quantite=1000)
        self._vente_payee(produit, quantite=200)
        self._reservation_confirmee(produit, acheteur=self.tiers, quantite=300)

        donnees = self.client.get(f"{URL}inventory/").data
        self.assertEqual(
            donnees["stock_total"],
            donnees["quantite_vendue"]
            + donnees["quantite_reservee"]
            + donnees["quantite_disponible"],
        )

    def test_vendeur_sans_stock(self):
        donnees = self.client.get(f"{URL}inventory/").data
        self.assertEqual(donnees["stock_total"], 0)
        self.assertEqual(donnees["quantite_disponible"], 0)
        self.assertEqual(donnees["valeur_stock_disponible"], "0.00")


class ReservationsTests(BaseTableauDeBordTests):
    def setUp(self):
        super().setUp()
        self.produit = self._creer("Velo", "150000", quantite=50)

    def test_compteurs_par_issue(self):
        ReservationService.demander(self.produit, self.acheteur, 1)
        acceptee = self._reservation_confirmee(
            self.produit, acheteur=self.tiers, quantite=2
        )
        self.assertEqual(acceptee.statut, StatutReservation.CONFIRMED)

        annulee_source = ReservationService.demander(
            self.produit,
            User.objects.create_user(username="c3", password="MotDePasse2026"),
            1,
        )
        ReservationService.annuler(annulee_source, self.vendeur, "Indisponible")

        donnees = self.client.get(f"{URL}reservations/").data
        self.assertEqual(donnees["en_attente"], 1)
        self.assertEqual(donnees["acceptees"], 1)
        self.assertEqual(donnees["annulees"], 1)
        self.assertEqual(donnees["expirees"], 0)
        self.assertEqual(donnees["quantite_immobilisee"], 2)

    def test_taux_de_transformation(self):
        # Une reservation transformee en vente...
        vendue = self._reservation_confirmee(
            self.produit, acheteur=self.acheteur, quantite=2
        )
        VenteService.enregistrer_depuis_reservation(vendue, self.vendeur)
        # ... et une annulee.
        perdue = self._reservation_confirmee(
            self.produit, acheteur=self.tiers, quantite=1
        )
        ReservationService.annuler(perdue, self.tiers, "Je ne viens plus")

        donnees = self.client.get(f"{URL}reservations/").data
        self.assertEqual(donnees["transformees_en_vente"], 1)
        self.assertEqual(donnees["taux_de_transformation"], 50.0)

    def test_taux_nul_sans_reservation_jugee(self):
        ReservationService.demander(self.produit, self.acheteur, 1)
        donnees = self.client.get(f"{URL}reservations/").data
        self.assertIsNone(donnees["taux_de_transformation"])

    def test_les_reservations_perimees_sont_liberees_avant_le_comptage(self):
        """Un tableau de bord ne doit pas afficher du stock bloque a tort."""
        reservation = self._reservation_confirmee(
            self.produit, acheteur=self.acheteur, quantite=4
        )
        Reservation.objects.filter(pk=reservation.pk).update(
            expire_le=timezone.now() - timedelta(hours=1)
        )

        donnees = self.client.get(f"{URL}reservations/").data
        self.assertEqual(donnees["expirees"], 1)
        self.assertEqual(donnees["acceptees"], 0)
        self.assertEqual(donnees["quantite_immobilisee"], 0)

        stock = self.client.get(f"{URL}inventory/").data
        self.assertEqual(stock["quantite_reservee"], 0)
        self.assertEqual(stock["quantite_disponible"], 50)

    def test_liste_des_reservations(self):
        demande = ReservationService.demander(self.produit, self.acheteur, 1)
        reponse = self.client.get(f"{URL}reservations/?liste=true")
        self.assertEqual(reponse.status_code, status.HTTP_200_OK)
        identifiants = [ligne["id"] for ligne in reponse.data["results"]]
        self.assertEqual(identifiants, [demande.pk])

    def test_liste_filtrable(self):
        ReservationService.demander(self.produit, self.acheteur, 1)
        acceptee = self._reservation_confirmee(
            self.produit, acheteur=self.tiers, quantite=1
        )
        reponse = self.client.get(f"{URL}reservations/?liste=true&statut=CONFIRMED")
        identifiants = [ligne["id"] for ligne in reponse.data["results"]]
        self.assertEqual(identifiants, [acceptee.pk])


class HistoriqueVentesTests(BaseTableauDeBordTests):
    def test_historique_des_ventes(self):
        produit = self._creer("Montre", "70000", quantite=10)
        payee = self._vente_payee(produit, quantite=1)
        en_attente = VenteService.enregistrer_vente_directe(
            produit, self.vendeur, self.tiers, 1
        )

        reponse = self.client.get(f"{URL}sales/")
        self.assertEqual(reponse.status_code, status.HTTP_200_OK)
        identifiants = {ligne["id"] for ligne in reponse.data["results"]}
        self.assertEqual(identifiants, {payee.pk, en_attente.pk})

    def test_historique_filtrable(self):
        produit = self._creer("Montre", "70000", quantite=10)
        payee = self._vente_payee(produit, quantite=1)
        VenteService.enregistrer_vente_directe(
            produit, self.vendeur, self.tiers, 1
        )

        reponse = self.client.get(f"{URL}sales/?comptabilisables=true")
        identifiants = [ligne["id"] for ligne in reponse.data["results"]]
        self.assertEqual(identifiants, [payee.pk])

    def test_les_achats_ne_sont_pas_dans_mes_ventes(self):
        produit_tiers = self._creer("Chez un autre", "5000", owner=self.tiers)
        vente = VenteService.enregistrer_vente_directe(
            produit_tiers, self.tiers, self.vendeur, 1
        )
        reponse = self.client.get(f"{URL}sales/")
        identifiants = [ligne["id"] for ligne in reponse.data["results"]]
        self.assertNotIn(vente.pk, identifiants)


class ProduitsPopulairesTests(BaseTableauDeBordTests):
    def test_les_plus_vendus(self):
        peu = self._creer("Peu vendu", "10000", quantite=50)
        beaucoup = self._creer("Tres vendu", "5000", quantite=50)
        self._vente_payee(peu, quantite=2)
        self._vente_payee(beaucoup, acheteur=self.tiers, quantite=20)

        donnees = self.client.get(f"{URL}top-products/").data
        plus_vendus = donnees["les_plus_vendus"]
        self.assertEqual(plus_vendus[0]["titre"], "Tres vendu")
        self.assertEqual(plus_vendus[0]["quantite_vendue"], 20)
        self.assertEqual(plus_vendus[0]["revenu"], "100000.00")
        self.assertEqual(plus_vendus[1]["titre"], "Peu vendu")

    def test_une_vente_annulee_sort_du_palmares(self):
        produit = self._creer("Ephemere", "10000", quantite=10)
        vente = self._vente_payee(produit, quantite=5)
        VenteService.annuler(vente, self.vendeur, "Erreur de saisie")

        donnees = self.client.get(f"{URL}top-products/").data
        self.assertEqual(donnees["les_plus_vendus"], [])

    def test_les_plus_consultes(self):
        self._creer("Vu souvent", "1000", vues=500)
        self._creer("Vu rarement", "1000", vues=3)
        self._creer("Brouillon vu", "1000", vues=9999, statut=StatutProduit.DRAFT)

        consultes = self.client.get(f"{URL}top-products/").data["les_plus_consultes"]
        titres = [ligne["titre"] for ligne in consultes]
        # Un brouillon n'est pas une annonce publiee : il n'y figure pas.
        self.assertEqual(titres, ["Vu souvent", "Vu rarement"])
        self.assertEqual(consultes[0]["nombre_vues"], 500)

    def test_note_du_produit_dans_le_palmares(self):
        produit = self._creer("Note", "10000", quantite=5, vues=10)
        vente = self._vente_payee(produit, quantite=1)
        VenteService.confirmer_reception(vente, self.acheteur)
        EvaluationService.creer(
            vente, self.acheteur, note_produit=4, note_vendeur=5
        )

        consultes = self.client.get(f"{URL}top-products/").data["les_plus_consultes"]
        self.assertEqual(consultes[0]["note_moyenne"], 4.0)

    def test_limite_configurable(self):
        for index in range(5):
            self._creer(f"Produit {index}", "1000", vues=index)
        donnees = self.client.get(f"{URL}top-products/?limite=2").data
        self.assertEqual(len(donnees["les_plus_consultes"]), 2)

    def test_limite_invalide_ignoree(self):
        self._creer("Unique", "1000", vues=1)
        for valeur in ("abc", "-5", "0", "9999"):
            reponse = self.client.get(f"{URL}top-products/?limite={valeur}")
            self.assertEqual(reponse.status_code, status.HTTP_200_OK, valeur)
            self.assertEqual(len(reponse.data["les_plus_consultes"]), 1)
