"""Tests du module 8 : reservations, quantites et protection du stock.

Les assertions portent surtout sur l'INVENTAIRE : une reservation n'est
correcte que si les trois quantites (totale, reservee, vendue) restent
coherentes a chaque etape.
"""
from datetime import timedelta
from decimal import Decimal
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.utils import timezone
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

User = get_user_model()
URL = "/api/v1/reservations/"


class BaseReservationTests(APITestCase):
    def setUp(self):
        self.categorie = Categorie.objects.create(nom="Telephonie")
        self.vendeur = User.objects.create_user(
            username="vendeur", password="MotDePasse2026"
        )
        self.acheteur = User.objects.create_user(
            username="acheteur", password="MotDePasse2026"
        )
        self.autre_acheteur = User.objects.create_user(
            username="autre_acheteur", password="MotDePasse2026"
        )
        self.tiers = User.objects.create_user(
            username="tiers", password="MotDePasse2026"
        )

        # L'exemple du cahier des charges : 10 telephones.
        self.produit = self._creer("Telephone Samsung", "450000", quantite=10)
        self.client.force_authenticate(self.acheteur)

    def _creer(self, titre, prix, quantite=10, statut=StatutProduit.ACTIVE, owner=None):
        produit = Produit.objects.create(
            owner=owner or self.vendeur, categorie=self.categorie, titre=titre,
            prix=Decimal(prix), status=statut, localisation="Mukaza, Bujumbura",
        )
        Inventaire.objects.create(produit=produit, quantite_totale=quantite)
        return produit

    def _demander(self, quantite=3, produit=None, acheteur=None):
        """Raccourci : cree une demande via le service."""
        return ReservationService.demander(
            produit or self.produit, acheteur or self.acheteur, quantite
        )

    def _accepter(self, reservation, quantite=None):
        return ReservationService.accepter(reservation, self.vendeur, quantite)

    def _stock(self, produit=None):
        inventaire = Inventaire.objects.get(produit=produit or self.produit)
        return (
            inventaire.quantite_totale,
            inventaire.quantite_reservee,
            inventaire.quantite_vendue,
            inventaire.quantite_disponible,
        )


class DemandeTests(BaseReservationTests):
    def test_demander_une_reservation(self):
        reponse = self.client.post(
            URL,
            {"produit": self.produit.pk, "quantite_demandee": 3, "message": "Je passe demain"},
            format="json",
        )
        self.assertEqual(reponse.status_code, status.HTTP_201_CREATED, reponse.data)

        reservation = Reservation.objects.get()
        self.assertEqual(reservation.statut, StatutReservation.PENDING)
        self.assertEqual(reservation.quantite_demandee, 3)
        # Le vendeur n'est jamais saisi par le client : il vient de l'annonce.
        self.assertEqual(reservation.vendeur, self.vendeur)
        self.assertEqual(reservation.acheteur, self.acheteur)

    def test_une_demande_n_immobilise_pas_encore_le_stock(self):
        """Regle du CD : c'est l'ACCEPTATION qui met la quantite de cote."""
        self._demander(3)
        self.assertEqual(self._stock(), (10, 0, 0, 10))

    def test_quantite_zero_refusee(self):
        reponse = self.client.post(
            URL, {"produit": self.produit.pk, "quantite_demandee": 0}, format="json"
        )
        self.assertEqual(reponse.status_code, status.HTTP_400_BAD_REQUEST)

    def test_quantite_superieure_au_disponible_refusee(self):
        reponse = self.client.post(
            URL, {"produit": self.produit.pk, "quantite_demandee": 11}, format="json"
        )
        self.assertEqual(reponse.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("quantite_demandee", reponse.data["errors"])

    def test_pas_de_reservation_sur_sa_propre_annonce(self):
        self.client.force_authenticate(self.vendeur)
        reponse = self.client.post(
            URL, {"produit": self.produit.pk, "quantite_demandee": 1}, format="json"
        )
        self.assertEqual(reponse.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(Reservation.objects.exists())

    def test_annonce_non_active_refusee(self):
        brouillon = self._creer("Brouillon", "1000", statut=StatutProduit.DRAFT)
        reponse = self.client.post(
            URL, {"produit": brouillon.pk, "quantite_demandee": 1}, format="json"
        )
        self.assertEqual(reponse.status_code, status.HTTP_400_BAD_REQUEST)

    def test_produit_sans_stock_refuse(self):
        """Regle 5 du CD : pas de nouvelle reservation sans stock disponible."""
        epuise = self._creer("Epuise", "1000", quantite=0)
        reponse = self.client.post(
            URL, {"produit": epuise.pk, "quantite_demandee": 1}, format="json"
        )
        self.assertEqual(reponse.status_code, status.HTTP_400_BAD_REQUEST)

    def test_une_seule_reservation_active_par_produit(self):
        self._demander(2)
        reponse = self.client.post(
            URL, {"produit": self.produit.pk, "quantite_demandee": 1}, format="json"
        )
        self.assertEqual(reponse.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(Reservation.objects.count(), 1)

    def test_nouvelle_demande_possible_apres_annulation(self):
        reservation = self._demander(2)
        ReservationService.annuler(reservation, self.acheteur)
        reponse = self.client.post(
            URL, {"produit": self.produit.pk, "quantite_demandee": 1}, format="json"
        )
        self.assertEqual(reponse.status_code, status.HTTP_201_CREATED, reponse.data)

    def test_anonyme_refuse(self):
        self.client.force_authenticate(None)
        reponse = self.client.post(
            URL, {"produit": self.produit.pk, "quantite_demandee": 1}, format="json"
        )
        self.assertEqual(reponse.status_code, status.HTTP_401_UNAUTHORIZED)


class AcceptationTests(BaseReservationTests):
    def test_acceptation_immobilise_le_stock(self):
        """Exemple du CD : 10 en stock, 3 acceptes -> 7 disponibles."""
        reservation = self._demander(3)
        self.client.force_authenticate(self.vendeur)
        reponse = self.client.post(f"{URL}{reservation.pk}/accept/", {}, format="json")
        self.assertEqual(reponse.status_code, status.HTTP_200_OK, reponse.data)

        reservation.refresh_from_db()
        self.assertEqual(reservation.statut, StatutReservation.CONFIRMED)
        self.assertEqual(reservation.quantite_confirmee, 3)
        self.assertEqual(self._stock(), (10, 3, 0, 7))

    def test_le_second_acheteur_est_limite_au_disponible(self):
        """Exemple du CD : apres 3 acceptes, le suivant ne peut en avoir que 7."""
        self._accepter(self._demander(3))

        self.client.force_authenticate(self.autre_acheteur)
        refus = self.client.post(
            URL, {"produit": self.produit.pk, "quantite_demandee": 8}, format="json"
        )
        self.assertEqual(refus.status_code, status.HTTP_400_BAD_REQUEST)

        accepte = self.client.post(
            URL, {"produit": self.produit.pk, "quantite_demandee": 7}, format="json"
        )
        self.assertEqual(accepte.status_code, status.HTTP_201_CREATED, accepte.data)

    def test_acceptation_partielle(self):
        """Le vendeur peut accepter moins que demande."""
        reservation = self._demander(5)
        self.client.force_authenticate(self.vendeur)
        reponse = self.client.post(
            f"{URL}{reservation.pk}/accept/", {"quantite": 2}, format="json"
        )
        self.assertEqual(reponse.status_code, status.HTTP_200_OK, reponse.data)

        reservation.refresh_from_db()
        self.assertEqual(reservation.quantite_demandee, 5)
        self.assertEqual(reservation.quantite_confirmee, 2)
        self.assertEqual(self._stock(), (10, 2, 0, 8))

    def test_impossible_d_accepter_plus_que_demande(self):
        reservation = self._demander(2)
        self.client.force_authenticate(self.vendeur)
        reponse = self.client.post(
            f"{URL}{reservation.pk}/accept/", {"quantite": 5}, format="json"
        )
        self.assertEqual(reponse.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(self._stock(), (10, 0, 0, 10))

    def test_acceptation_refusee_si_stock_pris_entre_temps(self):
        """Coeur du paragraphe 8.1 : le stock est reverifie a l'acceptation."""
        produit = self._creer("Derniere unite", "1000", quantite=2)
        premiere = ReservationService.demander(produit, self.acheteur, 2)
        seconde = ReservationService.demander(produit, self.autre_acheteur, 2)

        ReservationService.accepter(premiere, self.vendeur)

        self.client.force_authenticate(self.vendeur)
        reponse = self.client.post(f"{URL}{seconde.pk}/accept/", {}, format="json")
        self.assertEqual(reponse.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Stock insuffisant", str(reponse.data["errors"]))

        # Le stock n'a jamais depasse la quantite physique.
        self.assertEqual(self._stock(produit), (2, 2, 0, 0))

    def test_seul_le_vendeur_accepte(self):
        reservation = self._demander(3)
        reponse = self.client.post(f"{URL}{reservation.pk}/accept/", {}, format="json")
        self.assertEqual(reponse.status_code, status.HTTP_403_FORBIDDEN)

    def test_tiers_ne_voit_pas_la_reservation(self):
        reservation = self._demander(3)
        self.client.force_authenticate(self.tiers)
        self.assertEqual(
            self.client.get(f"{URL}{reservation.pk}/").status_code,
            status.HTTP_404_NOT_FOUND,
        )
        self.assertEqual(
            self.client.post(f"{URL}{reservation.pk}/accept/", {}, format="json").status_code,
            status.HTTP_404_NOT_FOUND,
        )

    def test_double_acceptation_refusee(self):
        reservation = self._accepter(self._demander(3))
        self.client.force_authenticate(self.vendeur)
        reponse = self.client.post(f"{URL}{reservation.pk}/accept/", {}, format="json")
        self.assertEqual(reponse.status_code, status.HTTP_400_BAD_REQUEST)
        # Le stock n'a pas ete immobilise deux fois.
        self.assertEqual(self._stock(), (10, 3, 0, 7))

    def test_annonce_passe_en_rupture_quand_tout_est_reserve(self):
        reservation = self._demander(10)
        self._accepter(reservation)
        self.produit.refresh_from_db()
        self.assertEqual(self.produit.status, StatutProduit.OUT_OF_STOCK)
        self.assertEqual(self._stock(), (10, 10, 0, 0))


class RefusEtAnnulationTests(BaseReservationTests):
    def test_refus_par_le_vendeur(self):
        reservation = self._demander(3)
        self.client.force_authenticate(self.vendeur)
        reponse = self.client.post(
            f"{URL}{reservation.pk}/reject/", {"motif": "Plus en stock"}, format="json"
        )
        self.assertEqual(reponse.status_code, status.HTTP_200_OK, reponse.data)

        reservation.refresh_from_db()
        self.assertEqual(reservation.statut, StatutReservation.CANCELLED)
        self.assertEqual(reservation.cloturee_par, "VENDEUR")
        self.assertEqual(reservation.motif, "Plus en stock")
        # Un refus ne libere rien : rien n'avait ete immobilise.
        self.assertEqual(self._stock(), (10, 0, 0, 10))

    def test_acheteur_ne_peut_pas_refuser(self):
        reservation = self._demander(3)
        reponse = self.client.post(f"{URL}{reservation.pk}/reject/", {}, format="json")
        self.assertEqual(reponse.status_code, status.HTTP_403_FORBIDDEN)

    def test_annulation_libere_le_stock(self):
        """Exemple du CD : le client ne vient pas, les 3 unites reviennent."""
        reservation = self._accepter(self._demander(3))
        self.assertEqual(self._stock(), (10, 3, 0, 7))

        self.client.force_authenticate(self.vendeur)
        reponse = self.client.post(
            f"{URL}{reservation.pk}/cancel/", {"motif": "Client absent"}, format="json"
        )
        self.assertEqual(reponse.status_code, status.HTTP_200_OK, reponse.data)

        reservation.refresh_from_db()
        self.assertEqual(reservation.statut, StatutReservation.CANCELLED)
        self.assertEqual(self._stock(), (10, 0, 0, 10))
        # Une annulation ne doit JAMAIS diminuer le stock vendu.
        self.assertEqual(reservation.quantite_livree, 0)

    def test_annulation_par_l_acheteur(self):
        reservation = self._accepter(self._demander(4))
        reponse = self.client.post(f"{URL}{reservation.pk}/cancel/", {}, format="json")
        self.assertEqual(reponse.status_code, status.HTTP_200_OK, reponse.data)
        reservation.refresh_from_db()
        self.assertEqual(reservation.cloturee_par, "ACHETEUR")
        self.assertEqual(self._stock(), (10, 0, 0, 10))

    def test_annulation_reactive_l_annonce_en_rupture(self):
        reservation = self._accepter(self._demander(10))
        self.produit.refresh_from_db()
        self.assertEqual(self.produit.status, StatutProduit.OUT_OF_STOCK)

        ReservationService.annuler(reservation, self.vendeur)
        self.produit.refresh_from_db()
        self.assertEqual(self.produit.status, StatutProduit.ACTIVE)

    def test_pas_de_double_annulation(self):
        reservation = self._accepter(self._demander(3))
        ReservationService.annuler(reservation, self.acheteur)
        reponse = self.client.post(f"{URL}{reservation.pk}/cancel/", {}, format="json")
        self.assertEqual(reponse.status_code, status.HTTP_400_BAD_REQUEST)
        # Le stock n'a pas ete libere deux fois.
        self.assertEqual(self._stock(), (10, 0, 0, 10))


class ModificationQuantiteTests(BaseReservationTests):
    def test_acheteur_modifie_sa_demande_en_attente(self):
        reservation = self._demander(3)
        reponse = self.client.post(
            f"{URL}{reservation.pk}/quantity/", {"quantite": 5}, format="json"
        )
        self.assertEqual(reponse.status_code, status.HTTP_200_OK, reponse.data)
        reservation.refresh_from_db()
        self.assertEqual(reservation.quantite_demandee, 5)

    def test_vendeur_ne_modifie_pas_une_demande_en_attente(self):
        reservation = self._demander(3)
        self.client.force_authenticate(self.vendeur)
        reponse = self.client.post(
            f"{URL}{reservation.pk}/quantity/", {"quantite": 2}, format="json"
        )
        self.assertEqual(reponse.status_code, status.HTTP_403_FORBIDDEN)

    def test_vendeur_augmente_la_quantite_confirmee(self):
        reservation = self._accepter(self._demander(3))
        self.client.force_authenticate(self.vendeur)
        reponse = self.client.post(
            f"{URL}{reservation.pk}/quantity/", {"quantite": 5}, format="json"
        )
        self.assertEqual(reponse.status_code, status.HTTP_200_OK, reponse.data)
        reservation.refresh_from_db()
        self.assertEqual(reservation.quantite_confirmee, 5)
        self.assertEqual(self._stock(), (10, 5, 0, 5))

    def test_vendeur_reduit_la_quantite_confirmee(self):
        reservation = self._accepter(self._demander(5))
        self.client.force_authenticate(self.vendeur)
        self.client.post(
            f"{URL}{reservation.pk}/quantity/", {"quantite": 2}, format="json"
        )
        reservation.refresh_from_db()
        self.assertEqual(reservation.quantite_confirmee, 2)
        self.assertEqual(self._stock(), (10, 2, 0, 8))

    def test_augmentation_limitee_par_le_stock(self):
        reservation = self._accepter(self._demander(5))
        self.client.force_authenticate(self.vendeur)
        reponse = self.client.post(
            f"{URL}{reservation.pk}/quantity/", {"quantite": 11}, format="json"
        )
        self.assertEqual(reponse.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(self._stock(), (10, 5, 0, 5))

    def test_quantite_obligatoire(self):
        reservation = self._demander(3)
        reponse = self.client.post(f"{URL}{reservation.pk}/quantity/", {}, format="json")
        self.assertEqual(reponse.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("quantite", reponse.data["errors"])


class ExpirationTests(BaseReservationTests):
    def _perimer(self, reservation):
        """Fait passer la date limite dans le passe, sans toucher au reste."""
        Reservation.objects.filter(pk=reservation.pk).update(
            expire_le=timezone.now() - timedelta(hours=1)
        )
        reservation.refresh_from_db()
        return reservation

    def test_expiration_libere_le_stock(self):
        reservation = self._perimer(self._accepter(self._demander(4)))
        self.assertEqual(self._stock(), (10, 4, 0, 6))

        traitees = ReservationService.expirer_les_depassees()
        self.assertEqual(traitees, 1)

        reservation.refresh_from_db()
        self.assertEqual(reservation.statut, StatutReservation.EXPIRED)
        self.assertEqual(reservation.cloturee_par, "SYSTEME")
        self.assertEqual(self._stock(), (10, 0, 0, 10))
        # Une expiration ne doit jamais diminuer le stock vendu.
        self.assertEqual(reservation.quantite_livree, 0)

    def test_demande_expiree_ne_peut_plus_etre_acceptee(self):
        reservation = self._perimer(self._demander(3))
        self.client.force_authenticate(self.vendeur)
        reponse = self.client.post(f"{URL}{reservation.pk}/accept/", {}, format="json")
        self.assertEqual(reponse.status_code, status.HTTP_400_BAD_REQUEST)
        reservation.refresh_from_db()
        self.assertEqual(reservation.statut, StatutReservation.EXPIRED)

    def test_duree_configurable(self):
        """Le CD demande une date d'expiration configurable."""
        with self.settings(RESERVATION_DUREE_HEURES=1):
            reservation = self._demander(1)
        ecart = reservation.expire_le - timezone.now()
        self.assertLess(ecart, timedelta(hours=1, minutes=1))
        self.assertGreater(ecart, timedelta(minutes=50))

    def test_commande_expirer_reservations(self):
        reservation = self._perimer(self._accepter(self._demander(3)))
        call_command("expirer_reservations", "--simulation", stdout=StringIO())
        reservation.refresh_from_db()
        # La simulation ne modifie rien.
        self.assertEqual(reservation.statut, StatutReservation.CONFIRMED)

        call_command("expirer_reservations", stdout=StringIO())
        reservation.refresh_from_db()
        self.assertEqual(reservation.statut, StatutReservation.EXPIRED)
        self.assertEqual(self._stock(), (10, 0, 0, 10))

    def test_la_liste_expire_les_reservations_depassees(self):
        """Une plateforme sans ordonnanceur ne doit pas bloquer du stock."""
        self._perimer(self._accepter(self._demander(4)))
        self.client.get(f"{URL}my-requests/")
        self.assertEqual(self._stock(), (10, 0, 0, 10))


class ListesEtFiltresTests(BaseReservationTests):
    def setUp(self):
        super().setUp()
        self.ma_demande = self._demander(3)
        # Une reservation ou je suis vendeur.
        self.mon_produit = self._creer(
            "Velo", "80000", quantite=4, owner=self.acheteur
        )
        self.reservation_recue = ReservationService.demander(
            self.mon_produit, self.autre_acheteur, 2
        )

    def test_mes_demandes(self):
        reponse = self.client.get(f"{URL}my-requests/")
        self.assertEqual(reponse.status_code, status.HTTP_200_OK)
        identifiants = [ligne["id"] for ligne in reponse.data["results"]]
        self.assertEqual(identifiants, [self.ma_demande.pk])

    def test_mes_reservations_recues(self):
        reponse = self.client.get(f"{URL}my-sales/")
        identifiants = [ligne["id"] for ligne in reponse.data["results"]]
        self.assertEqual(identifiants, [self.reservation_recue.pk])

    def test_liste_globale_contient_les_deux_roles(self):
        reponse = self.client.get(URL)
        identifiants = {ligne["id"] for ligne in reponse.data["results"]}
        self.assertEqual(
            identifiants, {self.ma_demande.pk, self.reservation_recue.pk}
        )

    def test_mon_role_est_indique(self):
        reponse = self.client.get(f"{URL}{self.ma_demande.pk}/")
        self.assertEqual(reponse.data["mon_role"], "ACHETEUR")
        reponse = self.client.get(f"{URL}{self.reservation_recue.pk}/")
        self.assertEqual(reponse.data["mon_role"], "VENDEUR")

    def test_filtre_statut(self):
        self._accepter(self.ma_demande)
        reponse = self.client.get(f"{URL}?statut=CONFIRMED")
        self.assertEqual(len(reponse.data["results"]), 1)
        self.assertEqual(reponse.data["results"][0]["id"], self.ma_demande.pk)

    def test_filtre_plusieurs_statuts(self):
        reponse = self.client.get(f"{URL}?statut_in=PENDING,CONFIRMED")
        self.assertEqual(len(reponse.data["results"]), 2)

    def test_filtre_localisation_icontains(self):
        """Regle demandee : la localisation se cherche par mot contenu."""
        reponse = self.client.get(f"{URL}?localisation=mukaza")
        self.assertEqual(len(reponse.data["results"]), 2)
        reponse = self.client.get(f"{URL}?localisation=gitega")
        self.assertEqual(len(reponse.data["results"]), 0)

    def test_filtre_quantite(self):
        reponse = self.client.get(f"{URL}?quantite_demandee__gte=3")
        self.assertEqual(len(reponse.data["results"]), 1)

    def test_filtre_titre(self):
        reponse = self.client.get(f"{URL}?titre=velo")
        self.assertEqual(len(reponse.data["results"]), 1)
        self.assertEqual(reponse.data["results"][0]["id"], self.reservation_recue.pk)

    def test_resume(self):
        self._accepter(self.ma_demande)
        reponse = self.client.get(f"{URL}summary/")
        self.assertEqual(reponse.status_code, status.HTTP_200_OK)
        self.assertEqual(reponse.data["demandes_acceptees"], 1)
        self.assertEqual(reponse.data["a_traiter"], 1)
        self.assertEqual(reponse.data["demandes_en_attente"], 0)


class HistoriqueStockTests(BaseReservationTests):
    def test_chaque_mouvement_est_trace(self):
        """Le CD exige un historique des mouvements de stock."""
        reservation = self._accepter(self._demander(3))
        ReservationService.annuler(reservation, self.vendeur, "Client absent")

        mouvements = list(
            MouvementStock.objects.filter(produit=self.produit).order_by("id")
        )
        self.assertEqual(
            [m.type_mouvement for m in mouvements],
            [TypeMouvementStock.RESERVATION, TypeMouvementStock.LIBERATION],
        )
        # Chaque ligne porte la photographie du stock resultant.
        self.assertEqual(mouvements[0].quantite_reservee_apres, 3)
        self.assertEqual(mouvements[0].quantite_disponible_apres, 7)
        self.assertEqual(mouvements[1].quantite_reservee_apres, 0)
        self.assertEqual(mouvements[1].quantite_disponible_apres, 10)
        # On sait qui a agi et sur quelle reservation.
        self.assertEqual(mouvements[1].effectue_par, self.vendeur)
        self.assertEqual(mouvements[1].reference_id, reservation.pk)
