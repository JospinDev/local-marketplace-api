"""Tests du module 9 : ventes, ventes partielles, revenus et annulations.

Le scenario le plus important est la vente partielle du cahier des charges :
3 pantalons reserves, 2 achetes, le troisieme libere.
"""
from decimal import Decimal

from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APITestCase

from modules.categories.models import Categorie
from modules.products.models import (
    Inventaire,
    MouvementStock,
    Produit,
    StatutProduit,
    TypeMouvementStock,
)
from modules.reservations.models import Reservation, StatutReservation
from modules.reservations.services import ReservationService
from modules.sales.models import StatutPaiement, StatutVente, Vente
from modules.sales.services import VenteService

User = get_user_model()
URL = "/api/v1/sales/"
URL_RESERVATIONS = "/api/v1/reservations/"


class BaseVenteTests(APITestCase):
    def setUp(self):
        self.categorie = Categorie.objects.create(nom="Vetements")
        self.vendeur = User.objects.create_user(
            username="vendeur", password="MotDePasse2026"
        )
        self.acheteur = User.objects.create_user(
            username="acheteur", password="MotDePasse2026"
        )
        self.tiers = User.objects.create_user(
            username="tiers", password="MotDePasse2026"
        )

        # L'exemple du cahier des charges : des pantalons a 35 000 BIF.
        self.produit = self._creer("Pantalon", "35000", quantite=10)
        self.client.force_authenticate(self.vendeur)

    def _creer(self, titre, prix, quantite=10, owner=None):
        produit = Produit.objects.create(
            owner=owner or self.vendeur, categorie=self.categorie, titre=titre,
            prix=Decimal(prix), status=StatutProduit.ACTIVE,
            localisation="Kinindo, Bujumbura",
        )
        Inventaire.objects.create(produit=produit, quantite_totale=quantite)
        return produit

    def _reservation_confirmee(self, quantite=3, produit=None, acheteur=None):
        reservation = ReservationService.demander(
            produit or self.produit, acheteur or self.acheteur, quantite
        )
        return ReservationService.accepter(reservation, self.vendeur)

    def _stock(self, produit=None):
        inventaire = Inventaire.objects.get(produit=produit or self.produit)
        return (
            inventaire.quantite_totale,
            inventaire.quantite_reservee,
            inventaire.quantite_vendue,
            inventaire.quantite_disponible,
        )


class VenteDepuisReservationTests(BaseVenteTests):
    def test_vente_complete(self):
        reservation = self._reservation_confirmee(3)
        self.assertEqual(self._stock(), (10, 3, 0, 7))

        reponse = self.client.post(
            f"{URL_RESERVATIONS}{reservation.pk}/complete/",
            {"moyen_paiement": "LUMICASH"},
            format="json",
        )
        self.assertEqual(reponse.status_code, status.HTTP_201_CREATED, reponse.data)

        vente = Vente.objects.get()
        self.assertEqual(vente.montant_total, Decimal("105000.00"))
        self.assertEqual(vente.moyen_paiement, "LUMICASH")
        self.assertEqual(vente.acheteur, self.acheteur)
        self.assertEqual(vente.vendeur, self.vendeur)

        reservation.refresh_from_db()
        self.assertEqual(reservation.statut, StatutReservation.FULFILLED)
        self.assertEqual(reservation.quantite_livree, 3)
        # 3 reservees deviennent 3 vendues : rien ne reste immobilise.
        self.assertEqual(self._stock(), (10, 0, 3, 7))

    def test_vente_partielle(self):
        """Scenario central du CD : 3 reserves, 2 achetes, 1 libere."""
        reservation = self._reservation_confirmee(3)

        reponse = self.client.post(
            f"{URL_RESERVATIONS}{reservation.pk}/complete/",
            {"quantite": 2},
            format="json",
        )
        self.assertEqual(reponse.status_code, status.HTTP_201_CREATED, reponse.data)

        vente = Vente.objects.get()
        ligne = vente.lignes.get()
        self.assertEqual(ligne.quantite, 2)
        self.assertEqual(ligne.prix_unitaire, Decimal("35000.00"))
        # Montant reellement encaisse : 2 x 35 000 = 70 000.
        self.assertEqual(vente.montant_total, Decimal("70000.00"))

        reservation.refresh_from_db()
        self.assertEqual(reservation.statut, StatutReservation.FULFILLED)
        self.assertEqual(reservation.quantite_confirmee, 3)
        self.assertEqual(reservation.quantite_livree, 2)
        self.assertEqual(reservation.quantite_non_achetee, 1)

        # 2 vendues, 0 reservee : la 3e unite est redevenue disponible.
        self.assertEqual(self._stock(), (10, 0, 2, 8))

    def test_vente_partielle_tracee_dans_l_historique(self):
        reservation = self._reservation_confirmee(3)
        VenteService.enregistrer_depuis_reservation(
            reservation, self.vendeur, quantite=2
        )
        mouvements = list(
            MouvementStock.objects.filter(produit=self.produit).order_by("id")
        )
        self.assertEqual(
            [m.type_mouvement for m in mouvements],
            [
                TypeMouvementStock.RESERVATION,
                TypeMouvementStock.LIBERATION,
                TypeMouvementStock.VENTE,
            ],
        )
        self.assertEqual(mouvements[-1].quantite_vendue_apres, 2)
        self.assertEqual(mouvements[-1].quantite_disponible_apres, 8)

    def test_prix_convenu_different_du_prix_affiche(self):
        """Le prix negocie est fige dans la ligne de vente."""
        reservation = self._reservation_confirmee(2)
        self.client.post(
            f"{URL_RESERVATIONS}{reservation.pk}/complete/",
            {"prix_unitaire": "30000.00"},
            format="json",
        )
        vente = Vente.objects.get()
        self.assertEqual(vente.montant_total, Decimal("60000.00"))

        # Le vendeur change ensuite le prix de son annonce : le revenu passe
        # ne doit pas bouger.
        self.produit.prix = Decimal("99000.00")
        self.produit.save(update_fields=["prix"])
        vente.refresh_from_db()
        self.assertEqual(vente.lignes.get().prix_unitaire, Decimal("30000.00"))
        self.assertEqual(vente.montant_total, Decimal("60000.00"))

    def test_quantite_superieure_a_la_reservation_refusee(self):
        reservation = self._reservation_confirmee(2)
        reponse = self.client.post(
            f"{URL_RESERVATIONS}{reservation.pk}/complete/",
            {"quantite": 5},
            format="json",
        )
        self.assertEqual(reponse.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(Vente.objects.exists())
        self.assertEqual(self._stock(), (10, 2, 0, 8))

    def test_reservation_en_attente_non_vendable(self):
        reservation = ReservationService.demander(self.produit, self.acheteur, 2)
        reponse = self.client.post(
            f"{URL_RESERVATIONS}{reservation.pk}/complete/", {}, format="json"
        )
        self.assertEqual(reponse.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(Vente.objects.exists())

    def test_seul_le_vendeur_declare_la_vente(self):
        reservation = self._reservation_confirmee(2)
        self.client.force_authenticate(self.acheteur)
        reponse = self.client.post(
            f"{URL_RESERVATIONS}{reservation.pk}/complete/", {}, format="json"
        )
        self.assertEqual(reponse.status_code, status.HTTP_403_FORBIDDEN)
        self.assertFalse(Vente.objects.exists())

    def test_vente_via_endpoint_sales(self):
        """`POST /sales/` accepte aussi une reservation."""
        reservation = self._reservation_confirmee(3)
        reponse = self.client.post(
            URL, {"reservation": reservation.pk, "quantite": 1}, format="json"
        )
        self.assertEqual(reponse.status_code, status.HTTP_201_CREATED, reponse.data)
        self.assertEqual(self._stock(), (10, 0, 1, 9))

    def test_tout_vendre_met_l_annonce_en_rupture(self):
        reservation = self._reservation_confirmee(10)
        VenteService.enregistrer_depuis_reservation(reservation, self.vendeur)
        self.produit.refresh_from_db()
        self.assertEqual(self.produit.status, StatutProduit.OUT_OF_STOCK)
        self.assertEqual(self._stock(), (10, 0, 10, 0))


class VenteDirecteTests(BaseVenteTests):
    def test_vente_directe(self):
        reponse = self.client.post(
            URL,
            {
                "produit": self.produit.pk,
                "acheteur": self.acheteur.pk,
                "quantite": 2,
                "moyen_paiement": "CASH",
            },
            format="json",
        )
        self.assertEqual(reponse.status_code, status.HTTP_201_CREATED, reponse.data)
        vente = Vente.objects.get()
        self.assertIsNone(vente.reservation)
        self.assertEqual(vente.montant_total, Decimal("70000.00"))
        self.assertEqual(self._stock(), (10, 0, 2, 8))

    def test_vente_directe_limitee_au_disponible(self):
        """Les quantites reservees par d'autres ne sont pas vendables."""
        self._reservation_confirmee(8)
        reponse = self.client.post(
            URL,
            {"produit": self.produit.pk, "acheteur": self.tiers.pk, "quantite": 3},
            format="json",
        )
        self.assertEqual(reponse.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Stock insuffisant", str(reponse.data["errors"]))
        self.assertEqual(self._stock(), (10, 8, 0, 2))

    def test_vente_sur_annonce_d_autrui_refusee(self):
        produit_tiers = self._creer("Chaussures", "20000", owner=self.tiers)
        reponse = self.client.post(
            URL,
            {
                "produit": produit_tiers.pk,
                "acheteur": self.acheteur.pk,
                "quantite": 1,
            },
            format="json",
        )
        self.assertEqual(reponse.status_code, status.HTTP_403_FORBIDDEN)
        self.assertFalse(Vente.objects.exists())

    def test_pas_de_vente_a_soi_meme(self):
        reponse = self.client.post(
            URL,
            {"produit": self.produit.pk, "acheteur": self.vendeur.pk, "quantite": 1},
            format="json",
        )
        self.assertEqual(reponse.status_code, status.HTTP_400_BAD_REQUEST)

    def test_acheteur_inconnu(self):
        reponse = self.client.post(
            URL,
            {"produit": self.produit.pk, "acheteur": 999999, "quantite": 1},
            format="json",
        )
        self.assertEqual(reponse.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("acheteur", reponse.data["errors"])

    def test_vente_directe_sans_acheteur_refusee(self):
        reponse = self.client.post(
            URL, {"produit": self.produit.pk, "quantite": 1}, format="json"
        )
        self.assertEqual(reponse.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("acheteur", reponse.data["errors"])

    def test_ni_reservation_ni_produit_refuse(self):
        reponse = self.client.post(URL, {"quantite": 1}, format="json")
        self.assertEqual(reponse.status_code, status.HTTP_400_BAD_REQUEST)

    def test_reservation_et_produit_ensemble_refuses(self):
        reservation = self._reservation_confirmee(2)
        reponse = self.client.post(
            URL,
            {
                "reservation": reservation.pk,
                "produit": self.produit.pk,
                "quantite": 1,
            },
            format="json",
        )
        self.assertEqual(reponse.status_code, status.HTTP_400_BAD_REQUEST)


class ConfirmationTests(BaseVenteTests):
    def setUp(self):
        super().setUp()
        self.vente = VenteService.enregistrer_vente_directe(
            self.produit, self.vendeur, self.acheteur, 2
        )

    def test_vente_creee_en_attente_de_confirmation(self):
        self.assertEqual(self.vente.statut, StatutVente.INITIATED)
        self.assertEqual(self.vente.statut_paiement, StatutPaiement.EN_ATTENTE)
        self.assertFalse(self.vente.est_comptabilisable)

    def test_confirmation_du_paiement_par_le_vendeur(self):
        reponse = self.client.post(f"{URL}{self.vente.pk}/confirm/", {}, format="json")
        self.assertEqual(reponse.status_code, status.HTTP_200_OK, reponse.data)

        self.vente.refresh_from_db()
        self.assertEqual(self.vente.statut, StatutVente.PAID)
        self.assertEqual(self.vente.statut_paiement, StatutPaiement.RECU)
        self.assertIsNotNone(self.vente.confirmee_le)
        self.assertTrue(self.vente.est_comptabilisable)

    def test_acheteur_ne_confirme_pas_le_paiement(self):
        self.client.force_authenticate(self.acheteur)
        reponse = self.client.post(f"{URL}{self.vente.pk}/confirm/", {}, format="json")
        self.assertEqual(reponse.status_code, status.HTTP_403_FORBIDDEN)

    def test_confirmation_reception_par_l_acheteur(self):
        VenteService.confirmer_paiement(self.vente, self.vendeur)

        self.client.force_authenticate(self.acheteur)
        reponse = self.client.post(
            f"{URL}{self.vente.pk}/buyer-confirmation/", {}, format="json"
        )
        self.assertEqual(reponse.status_code, status.HTTP_200_OK, reponse.data)

        self.vente.refresh_from_db()
        self.assertEqual(self.vente.statut, StatutVente.COMPLETED)
        self.assertIsNotNone(self.vente.confirmee_par_acheteur_le)

    def test_reception_impossible_avant_le_paiement(self):
        self.client.force_authenticate(self.acheteur)
        reponse = self.client.post(
            f"{URL}{self.vente.pk}/buyer-confirmation/", {}, format="json"
        )
        self.assertEqual(reponse.status_code, status.HTTP_400_BAD_REQUEST)

    def test_vendeur_ne_confirme_pas_la_reception(self):
        VenteService.confirmer_paiement(self.vente, self.vendeur)
        reponse = self.client.post(
            f"{URL}{self.vente.pk}/buyer-confirmation/", {}, format="json"
        )
        self.assertEqual(reponse.status_code, status.HTTP_403_FORBIDDEN)

    def test_double_confirmation_refusee(self):
        VenteService.confirmer_paiement(self.vente, self.vendeur)
        reponse = self.client.post(f"{URL}{self.vente.pk}/confirm/", {}, format="json")
        self.assertEqual(reponse.status_code, status.HTTP_400_BAD_REQUEST)


class AnnulationVenteTests(BaseVenteTests):
    def setUp(self):
        super().setUp()
        self.vente = VenteService.enregistrer_vente_directe(
            self.produit, self.vendeur, self.acheteur, 3
        )

    def test_annulation_remet_le_stock_en_disponible(self):
        self.assertEqual(self._stock(), (10, 0, 3, 7))

        reponse = self.client.post(
            f"{URL}{self.vente.pk}/cancel/",
            {"motif": "Erreur de saisie"},
            format="json",
        )
        self.assertEqual(reponse.status_code, status.HTTP_200_OK, reponse.data)

        self.vente.refresh_from_db()
        self.assertEqual(self.vente.statut, StatutVente.CANCELLED)
        self.assertEqual(self.vente.motif_annulation, "Erreur de saisie")
        self.assertEqual(self._stock(), (10, 0, 0, 10))

    def test_motif_obligatoire(self):
        """Le CD interdit de modifier silencieusement une vente."""
        reponse = self.client.post(f"{URL}{self.vente.pk}/cancel/", {}, format="json")
        self.assertEqual(reponse.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("motif", reponse.data["errors"])
        self.assertEqual(self._stock(), (10, 0, 3, 7))

    def test_vente_payee_part_en_rembourse(self):
        VenteService.confirmer_paiement(self.vente, self.vendeur)
        self.client.post(
            f"{URL}{self.vente.pk}/cancel/", {"motif": "Produit defectueux"},
            format="json",
        )
        self.vente.refresh_from_db()
        self.assertEqual(self.vente.statut, StatutVente.REFUNDED)
        self.assertEqual(self.vente.statut_paiement, StatutPaiement.REMBOURSE)

    def test_les_lignes_et_prix_sont_conserves(self):
        """Toute correction laisse une trace d'audit, sans reecrire le passe."""
        VenteService.annuler(self.vente, self.vendeur, "Erreur")
        ligne = self.vente.lignes.get()
        self.assertEqual(ligne.quantite, 3)
        self.assertEqual(ligne.prix_unitaire, Decimal("35000.00"))
        self.assertEqual(self.vente.montant_total, Decimal("105000.00"))

        trace = MouvementStock.objects.filter(
            type_mouvement=TypeMouvementStock.ANNULATION_VENTE
        ).get()
        self.assertEqual(trace.quantite, 3)
        self.assertIn("Erreur", trace.commentaire)
        self.assertEqual(trace.effectue_par, self.vendeur)

    def test_acheteur_ne_peut_pas_annuler(self):
        self.client.force_authenticate(self.acheteur)
        reponse = self.client.post(
            f"{URL}{self.vente.pk}/cancel/", {"motif": "Je ne veux plus"},
            format="json",
        )
        self.assertEqual(reponse.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(self._stock(), (10, 0, 3, 7))

    def test_pas_de_double_annulation(self):
        VenteService.annuler(self.vente, self.vendeur, "Erreur")
        reponse = self.client.post(
            f"{URL}{self.vente.pk}/cancel/", {"motif": "Encore"}, format="json"
        )
        self.assertEqual(reponse.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(self._stock(), (10, 0, 0, 10))

    def test_annulation_reactive_l_annonce_en_rupture(self):
        VenteService.enregistrer_vente_directe(
            self.produit, self.vendeur, self.tiers, 7
        )
        self.produit.refresh_from_db()
        self.assertEqual(self.produit.status, StatutProduit.OUT_OF_STOCK)

        VenteService.annuler(self.vente, self.vendeur, "Erreur")
        self.produit.refresh_from_db()
        self.assertEqual(self.produit.status, StatutProduit.ACTIVE)


class ListesEtRevenusTests(BaseVenteTests):
    def setUp(self):
        super().setUp()
        self.vente_payee = VenteService.enregistrer_vente_directe(
            self.produit, self.vendeur, self.acheteur, 2
        )
        VenteService.confirmer_paiement(self.vente_payee, self.vendeur)
        self.vente_en_attente = VenteService.enregistrer_vente_directe(
            self.produit, self.vendeur, self.tiers, 1
        )

    def test_mes_ventes(self):
        reponse = self.client.get(f"{URL}my-sales/")
        self.assertEqual(reponse.status_code, status.HTTP_200_OK)
        self.assertEqual(len(reponse.data["results"]), 2)

    def test_mes_achats(self):
        self.client.force_authenticate(self.acheteur)
        reponse = self.client.get(f"{URL}my-purchases/")
        identifiants = [ligne["id"] for ligne in reponse.data["results"]]
        self.assertEqual(identifiants, [self.vente_payee.pk])
        self.assertEqual(reponse.data["results"][0]["mon_role"], "ACHETEUR")

    def test_une_vente_d_autrui_est_invisible(self):
        autre_vendeur = User.objects.create_user(
            username="autre_vendeur", password="MotDePasse2026"
        )
        self.client.force_authenticate(autre_vendeur)
        self.assertEqual(
            self.client.get(f"{URL}{self.vente_payee.pk}/").status_code,
            status.HTTP_404_NOT_FOUND,
        )
        self.assertEqual(len(self.client.get(URL).data["results"]), 0)

    def test_revenus_ne_comptent_que_les_ventes_confirmees(self):
        """Regle du CD : jamais de revenu calcule sur les reservations."""
        # Une reservation acceptee, donc une valeur immobilisee...
        self._reservation_confirmee(4)

        reponse = self.client.get(f"{URL}summary/")
        self.assertEqual(reponse.status_code, status.HTTP_200_OK)
        # ... qui n'entre pas dans le chiffre d'affaires : seules les
        # 2 unites payees comptent (2 x 35 000).
        self.assertEqual(reponse.data["chiffre_affaires"], "70000.00")
        self.assertEqual(reponse.data["ventes_confirmees"], 1)
        self.assertEqual(reponse.data["quantite_vendue"], 2)
        self.assertEqual(reponse.data["ventes_en_attente_de_confirmation"], 1)
        self.assertEqual(reponse.data["nombre_clients"], 1)

    def test_revenus_excluent_les_ventes_annulees(self):
        VenteService.annuler(self.vente_payee, self.vendeur, "Erreur")
        reponse = self.client.get(f"{URL}summary/")
        self.assertEqual(reponse.data["chiffre_affaires"], "0.00")
        self.assertEqual(reponse.data["ventes_annulees"], 1)

    def test_revenus_sur_une_periode(self):
        """Les filtres de la liste s'appliquent aussi au resume."""
        reponse = self.client.get(f"{URL}summary/?created_at_gte=2030-01-01T00:00:00Z")
        self.assertEqual(reponse.data["chiffre_affaires"], "0.00")

    def test_filtre_comptabilisables(self):
        reponse = self.client.get(f"{URL}?comptabilisables=true")
        identifiants = [ligne["id"] for ligne in reponse.data["results"]]
        self.assertEqual(identifiants, [self.vente_payee.pk])

    def test_filtre_localisation_icontains(self):
        reponse = self.client.get(f"{URL}?localisation=kinindo")
        self.assertEqual(len(reponse.data["results"]), 2)
        reponse = self.client.get(f"{URL}?localisation=ngozi")
        self.assertEqual(len(reponse.data["results"]), 0)

    def test_filtre_montant(self):
        reponse = self.client.get(f"{URL}?montant_min=50000")
        identifiants = [ligne["id"] for ligne in reponse.data["results"]]
        self.assertEqual(identifiants, [self.vente_payee.pk])

    def test_filtre_ventes_directes(self):
        reponse = self.client.get(f"{URL}?reservation__isnull=true")
        self.assertEqual(len(reponse.data["results"]), 2)

    def test_anonyme_refuse(self):
        self.client.force_authenticate(None)
        self.assertEqual(
            self.client.get(URL).status_code, status.HTTP_401_UNAUTHORIZED
        )


class CoherenceStockTests(BaseVenteTests):
    def test_le_stock_reste_coherent_sur_un_parcours_complet(self):
        """Parcours du scenario 4 du CD, de la demande a la vente partielle."""
        # 10 en stock.
        self.assertEqual(self._stock(), (10, 0, 0, 10))

        # Un acheteur reserve 3, un autre 2.
        premiere = self._reservation_confirmee(3)
        seconde = self._reservation_confirmee(2, acheteur=self.tiers)
        self.assertEqual(self._stock(), (10, 5, 0, 5))

        # Le premier vient en chercher 2 : 1 est libere.
        VenteService.enregistrer_depuis_reservation(premiere, self.vendeur, quantite=2)
        self.assertEqual(self._stock(), (10, 2, 2, 6))

        # Le second ne vient pas : annulation, ses 2 unites reviennent.
        ReservationService.annuler(seconde, self.vendeur, "Client absent")
        self.assertEqual(self._stock(), (10, 0, 2, 8))

        # Total physique inchange, et la somme reste exacte.
        inventaire = Inventaire.objects.get(produit=self.produit)
        self.assertEqual(
            inventaire.quantite_totale,
            inventaire.quantite_reservee
            + inventaire.quantite_vendue
            + inventaire.quantite_disponible,
        )
        # Une seule vente, de 2 unites.
        self.assertEqual(Vente.objects.count(), 1)
        self.assertEqual(Reservation.objects.filter(statut="FULFILLED").count(), 1)
