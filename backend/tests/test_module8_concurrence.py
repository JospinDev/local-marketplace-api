"""Tests de concurrence du module 8 (paragraphe 8.1 et scenario 10 du CD).

    "Deux clients essaient simultanement de reserver les 2 dernieres unites.
     Le backend doit utiliser une transaction PostgreSQL et un verrouillage
     approprie (SELECT FOR UPDATE) pour eviter que les deux reservations
     soient acceptees."

Ces tests lancent de VRAIS threads qui ouvrent chacun leur propre connexion
a la base. Ils ne sont donc executes que sur PostgreSQL : SQLite en memoire
donne une base distincte par connexion, le scenario n'y a aucun sens.

Pour les lancer :

    python manage.py test tests.test_module8_concurrence

(avec la configuration de developpement, donc PostgreSQL)
"""
import threading
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import connection, connections
from django.test import TransactionTestCase, tag
from django.utils import timezone

from modules.categories.models import Categorie
from modules.products.models import Inventaire, Produit, StatutProduit
from modules.reservations.models import Reservation, StatutReservation
from modules.reservations.services import ReservationService
from modules.sales.models import Vente
from modules.sales.services import VenteService

User = get_user_model()

POSTGRESQL_REQUIS = (
    "Test de concurrence : necessite PostgreSQL (verrous de ligne reels)."
)


@tag("concurrence")
class BaseConcurrenceTests(TransactionTestCase):
    """Outillage commun : execution de plusieurs appels en parallele."""

    def setUp(self):
        if connection.vendor != "postgresql":
            self.skipTest(POSTGRESQL_REQUIS)

        self.categorie = Categorie.objects.create(nom="Telephonie")
        self.vendeur = User.objects.create_user(
            username="vendeur_conc", password="MotDePasse2026"
        )
        self.acheteurs = [
            User.objects.create_user(
                username=f"acheteur_conc_{index}", password="MotDePasse2026"
            )
            for index in range(4)
        ]

    def _creer_produit(self, quantite):
        produit = Produit.objects.create(
            owner=self.vendeur, categorie=self.categorie, titre="Telephone",
            prix=Decimal("450000.00"), status=StatutProduit.ACTIVE,
            localisation="Mukaza",
        )
        Inventaire.objects.create(produit=produit, quantite_totale=quantite)
        return produit

    def _en_parallele(self, operations):
        """Lance chaque operation dans son propre thread, au meme instant.

        La barriere garantit que tous les threads entrent dans la section
        critique ensemble : sans verrou cote base, les lectures de stock se
        chevauchent et le test echoue.
        """
        barriere = threading.Barrier(len(operations))
        resultats = [None] * len(operations)

        def executer(index, operation):
            try:
                barriere.wait(timeout=10)
                resultats[index] = ("ok", operation())
            except Exception as exc:  # noqa: BLE001 - on inspecte le type ensuite
                resultats[index] = ("erreur", exc)
            finally:
                # Chaque thread a sa propre connexion : il doit la fermer.
                connections.close_all()

        threads = [
            threading.Thread(target=executer, args=(index, operation))
            for index, operation in enumerate(operations)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)

        self.assertFalse(
            any(thread.is_alive() for thread in threads),
            "Un thread est reste bloque : verrou non relache (interblocage ?).",
        )
        return resultats

    def _stock(self, produit):
        inventaire = Inventaire.objects.get(produit=produit)
        return (
            inventaire.quantite_totale,
            inventaire.quantite_reservee,
            inventaire.quantite_vendue,
            inventaire.quantite_disponible,
        )

    def _compter(self, resultats):
        succes = [valeur for etat, valeur in resultats if etat == "ok"]
        erreurs = [valeur for etat, valeur in resultats if etat == "erreur"]
        return succes, erreurs


class AcceptationsConcurrentesTests(BaseConcurrenceTests):
    def test_deux_acceptations_des_deux_dernieres_unites(self):
        """Le scenario exact du paragraphe 8.1 : une seule doit passer."""
        produit = self._creer_produit(2)
        premiere = ReservationService.demander(produit, self.acheteurs[0], 2)
        seconde = ReservationService.demander(produit, self.acheteurs[1], 2)

        resultats = self._en_parallele(
            [
                lambda: ReservationService.accepter(premiere, self.vendeur),
                lambda: ReservationService.accepter(seconde, self.vendeur),
            ]
        )
        succes, erreurs = self._compter(resultats)

        self.assertEqual(len(succes), 1, f"Resultats : {resultats}")
        self.assertEqual(len(erreurs), 1, f"Resultats : {resultats}")
        self.assertIn("Stock insuffisant", str(erreurs[0]))

        # Le stock n'a jamais ete survendu.
        self.assertEqual(self._stock(produit), (2, 2, 0, 0))
        self.assertEqual(
            Reservation.objects.filter(statut=StatutReservation.CONFIRMED).count(), 1
        )

    def test_quatre_acheteurs_pour_cinq_unites(self):
        """3 unites chacun, 5 en stock : exactement une acceptation passe."""
        produit = self._creer_produit(5)
        reservations = [
            ReservationService.demander(produit, acheteur, 3)
            for acheteur in self.acheteurs
        ]

        resultats = self._en_parallele(
            [
                (lambda r=reservation: ReservationService.accepter(r, self.vendeur))
                for reservation in reservations
            ]
        )
        succes, erreurs = self._compter(resultats)

        self.assertEqual(len(succes), 1, f"Resultats : {resultats}")
        self.assertEqual(len(erreurs), 3)
        # 3 reservees sur 5 : jamais plus que le stock physique.
        self.assertEqual(self._stock(produit), (5, 3, 0, 2))

    def test_la_somme_des_quantites_ne_depasse_jamais_le_stock(self):
        """Quatre acheteurs, 1 unite chacun, 3 en stock : 3 passent, 1 echoue."""
        produit = self._creer_produit(3)
        reservations = [
            ReservationService.demander(produit, acheteur, 1)
            for acheteur in self.acheteurs
        ]

        resultats = self._en_parallele(
            [
                (lambda r=reservation: ReservationService.accepter(r, self.vendeur))
                for reservation in reservations
            ]
        )
        succes, erreurs = self._compter(resultats)

        self.assertEqual(len(succes), 3, f"Resultats : {resultats}")
        self.assertEqual(len(erreurs), 1)
        self.assertEqual(self._stock(produit), (3, 3, 0, 0))

        # L'annonce est automatiquement passee en rupture.
        produit.refresh_from_db()
        self.assertEqual(produit.status, StatutProduit.OUT_OF_STOCK)

    def test_double_acceptation_de_la_meme_reservation(self):
        """Deux onglets du vendeur acceptent la meme demande en meme temps."""
        produit = self._creer_produit(10)
        reservation = ReservationService.demander(produit, self.acheteurs[0], 4)

        resultats = self._en_parallele(
            [
                lambda: ReservationService.accepter(reservation, self.vendeur),
                lambda: ReservationService.accepter(reservation, self.vendeur),
            ]
        )
        succes, erreurs = self._compter(resultats)

        self.assertEqual(len(succes), 1, f"Resultats : {resultats}")
        # Le stock n'a pas ete immobilise deux fois.
        self.assertEqual(self._stock(produit), (10, 4, 0, 6))


class VentesConcurrentesTests(BaseConcurrenceTests):
    def test_deux_ventes_directes_sur_la_derniere_unite(self):
        produit = self._creer_produit(1)

        resultats = self._en_parallele(
            [
                (
                    lambda acheteur=acheteur: VenteService.enregistrer_vente_directe(
                        produit, self.vendeur, acheteur, 1
                    )
                )
                for acheteur in self.acheteurs[:2]
            ]
        )
        succes, erreurs = self._compter(resultats)

        self.assertEqual(len(succes), 1, f"Resultats : {resultats}")
        self.assertIn("Stock insuffisant", str(erreurs[0]))
        self.assertEqual(self._stock(produit), (1, 0, 1, 0))
        self.assertEqual(Vente.objects.count(), 1)

    def test_double_transformation_de_la_meme_reservation(self):
        """Deux clics sur "vendre" ne doivent pas creer deux ventes."""
        produit = self._creer_produit(5)
        reservation = ReservationService.accepter(
            ReservationService.demander(produit, self.acheteurs[0], 3), self.vendeur
        )

        resultats = self._en_parallele(
            [
                lambda: VenteService.enregistrer_depuis_reservation(
                    reservation, self.vendeur, quantite=3
                ),
                lambda: VenteService.enregistrer_depuis_reservation(
                    reservation, self.vendeur, quantite=3
                ),
            ]
        )
        succes, erreurs = self._compter(resultats)

        self.assertEqual(len(succes), 1, f"Resultats : {resultats}")
        self.assertEqual(Vente.objects.count(), 1)
        # 3 vendues, plus rien d'immobilise.
        self.assertEqual(self._stock(produit), (5, 0, 3, 2))

    def test_vente_directe_et_acceptation_simultanees(self):
        """Le vendeur vend sur place pendant qu'il accepte une reservation."""
        produit = self._creer_produit(2)
        reservation = ReservationService.demander(produit, self.acheteurs[0], 2)

        resultats = self._en_parallele(
            [
                lambda: ReservationService.accepter(reservation, self.vendeur),
                lambda: VenteService.enregistrer_vente_directe(
                    produit, self.vendeur, self.acheteurs[1], 2
                ),
            ]
        )
        succes, erreurs = self._compter(resultats)

        self.assertEqual(len(succes), 1, f"Resultats : {resultats}")
        self.assertEqual(len(erreurs), 1)

        total, reservee, vendue, disponible = self._stock(produit)
        self.assertEqual(total, 2)
        self.assertEqual(disponible, 0)
        # Soit 2 reservees, soit 2 vendues : jamais les deux.
        self.assertEqual(reservee + vendue, 2)


class AnnulationsConcurrentesTests(BaseConcurrenceTests):
    def test_double_annulation_ne_libere_quune_fois(self):
        """Acheteur et vendeur annulent au meme instant."""
        produit = self._creer_produit(10)
        reservation = ReservationService.accepter(
            ReservationService.demander(produit, self.acheteurs[0], 4), self.vendeur
        )

        resultats = self._en_parallele(
            [
                lambda: ReservationService.annuler(
                    reservation, self.acheteurs[0], "Je ne viens plus"
                ),
                lambda: ReservationService.annuler(
                    reservation, self.vendeur, "Client injoignable"
                ),
            ]
        )
        succes, _ = self._compter(resultats)

        self.assertEqual(len(succes), 1, f"Resultats : {resultats}")
        # Les 4 unites sont liberees une seule fois, pas huit.
        self.assertEqual(self._stock(produit), (10, 0, 0, 10))

    def test_expiration_et_vente_simultanees(self):
        """La tache d'expiration tourne pendant que le vendeur encaisse."""
        produit = self._creer_produit(5)
        reservation = ReservationService.accepter(
            ReservationService.demander(produit, self.acheteurs[0], 3), self.vendeur
        )
        # La reservation vient juste d'arriver a echeance.
        Reservation.objects.filter(pk=reservation.pk).update(
            expire_le=timezone.now() - timedelta(seconds=1)
        )

        self._en_parallele(
            [
                lambda: ReservationService.expirer_les_depassees(),
                lambda: VenteService.enregistrer_depuis_reservation(
                    reservation, self.vendeur, quantite=3
                ),
            ]
        )

        reservation.refresh_from_db()
        total, reservee, vendue, disponible = self._stock(produit)
        self.assertEqual(total, 5)
        # Quel que soit l'ordre, rien ne reste immobilise a tort et le
        # vendu correspond exactement a l'etat final de la reservation.
        self.assertEqual(reservee, 0)
        self.assertEqual(
            vendue, 3 if reservation.statut == StatutReservation.FULFILLED else 0
        )
        self.assertEqual(disponible, total - vendue)
