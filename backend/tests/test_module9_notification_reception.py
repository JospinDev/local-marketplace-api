"""L'acheteur doit etre prevenu quand c'est a lui d'agir.

Manque corrige : `confirmer_paiement` ne notifiait personne. L'acheteur
n'apprenait donc jamais que la vente attendait SA confirmation de
reception — le geste qui termine la vente et ouvre seul le droit a un
avis. Il n'avait aucun signal, et aucune raison d'aller regarder.
"""
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase

from modules.categories.models import Categorie
from modules.notifications.models import Notification, TypeNotification
from modules.products.models import Inventaire, Produit, StatutProduit
from modules.sales.models import StatutVente
from modules.sales.services import VenteService

User = get_user_model()


class NotificationDeReception(TestCase):
    def setUp(self):
        self.categorie = Categorie.objects.create(nom="Vetements")
        self.vendeur = User.objects.create_user(
            username="vendeur", password="MotDePasse2026"
        )
        self.acheteur = User.objects.create_user(
            username="acheteur", password="MotDePasse2026"
        )

        self.produit = Produit.objects.create(
            owner=self.vendeur,
            categorie=self.categorie,
            titre="Pantalon",
            prix=Decimal("35000"),
            status=StatutProduit.ACTIVE,
            localisation="Kinindo, Bujumbura",
        )
        Inventaire.objects.create(produit=self.produit, quantite_totale=10)

        self.vente = VenteService.enregistrer_vente_directe(
            self.produit, self.vendeur, self.acheteur, 2
        )
        Notification.objects.all().delete()

    def test_l_acheteur_est_prevenu_de_la_confirmation_du_paiement(self):
        VenteService.confirmer_paiement(self.vente, self.vendeur)

        notification = Notification.objects.filter(
            destinataire=self.acheteur,
            type_notification=TypeNotification.VENTE_A_CONFIRMER,
        ).first()

        self.assertIsNotNone(
            notification,
            "Sans cette notification, l'acheteur ignore que la vente "
            "attend sa confirmation de reception.",
        )
        self.assertEqual(notification.reference_type, "vente")
        self.assertEqual(notification.reference_id, self.vente.pk)
        # Le message doit dire quoi faire, pas seulement ce qui s'est passe.
        self.assertIn("reception", notification.message.lower())

    def test_le_vendeur_n_est_pas_notifie_de_sa_propre_action(self):
        VenteService.confirmer_paiement(self.vente, self.vendeur)

        self.assertFalse(
            Notification.objects.filter(
                destinataire=self.vendeur,
                type_notification=TypeNotification.VENTE_A_CONFIRMER,
            ).exists()
        )

    def test_le_vendeur_est_prevenu_quand_l_acheteur_confirme(self):
        """L'autre moitie du double accuse, deja en place."""
        VenteService.confirmer_paiement(self.vente, self.vendeur)
        Notification.objects.all().delete()

        VenteService.confirmer_reception(self.vente, self.acheteur)
        self.vente.refresh_from_db()

        self.assertEqual(self.vente.statut, StatutVente.COMPLETED)
        self.assertTrue(
            Notification.objects.filter(
                destinataire=self.vendeur,
                type_notification=TypeNotification.ACHAT_CONFIRME,
            ).exists()
        )
