"""Tests du module 14 : audit, statistiques, signalements, configuration.

Deux exigences sont verifiees avec insistance :

- la regle de groupe du projet : un groupe ne fait QUE ce que ses
  permissions autorisent, y compris sur les routes d'administration ;
- le journal d'audit est en lecture seule et se remplit tout seul quand
  l'administration agit.
"""
from decimal import Decimal
from unittest import mock

from django.contrib.auth import get_user_model
from django.db import DatabaseError
from django.contrib.auth.models import Group, Permission
from rest_framework import status
from rest_framework.test import APITestCase

from modules.categories.models import Categorie
from modules.messaging.models import Conversation, SignalementConversation
from modules.moderation.models import (
    ActionAudit,
    JournalAudit,
    ParametrePlateforme,
    TypeValeurParametre,
)
from modules.notifications.models import Notification, TypeNotification
from modules.products.models import Inventaire, Produit, StatutProduit
from modules.reservations.services import ReservationService
from modules.reviews.models import Evaluation, StatutEvaluation
from modules.reviews.services import EvaluationService
from modules.sales.services import VenteService

User = get_user_model()
URL_AUDIT = "/api/v1/admin/audit-logs/"
URL_STATS = "/api/v1/admin/statistics/"
URL_REPORTS = "/api/v1/admin/reports/"
URL_SETTINGS = "/api/v1/admin/settings/"
URL_MOUVEMENTS = "/api/v1/admin/stock-movements/"
URL_VENTES_ADMIN = "/api/v1/admin/sales/"
URL_RESERVATIONS_ADMIN = "/api/v1/admin/reservations/"


def groupe_avec(nom, *codenames):
    groupe = Group.objects.create(name=nom)
    for codename in codenames:
        groupe.permissions.add(Permission.objects.get(codename=codename))
    return groupe


class BaseAdministrationTests(APITestCase):
    def setUp(self):
        self.categorie = Categorie.objects.create(nom="Electronique")
        self.vendeur = User.objects.create_user(
            username="vendeur", password="MotDePasse2026"
        )
        self.acheteur = User.objects.create_user(
            username="acheteur", password="MotDePasse2026"
        )
        self.produit = self._creer("Telephone", "450000", quantite=10)

        # Un administrateur complet.
        self.admin = User.objects.create_user(
            username="administrateur", password="MotDePasse2026"
        )
        # Ce groupe detient AUSSI les permissions d'ecriture sur le
        # journal, les ventes et les mouvements de stock. C'est volontaire :
        # les tests veulent prouver qu'aucune route d'ecriture n'existe
        # (405), et non se contenter d'un refus de permission (403) qui
        # masquerait l'absence de garde-fou cote API.
        self.admin.groups.add(
            groupe_avec(
                "Admin Test",
                "view_journalaudit",
                "add_journalaudit",
                "change_journalaudit",
                "delete_journalaudit",
                "consulter_statistiques",
                "view_parametreplateforme",
                "add_parametreplateforme",
                "change_parametreplateforme",
                "delete_parametreplateforme",
                "view_signalementconversation",
                "change_signalementconversation",
                "view_evaluation",
                "change_evaluation",
                "view_mouvementstock",
                "add_mouvementstock",
                "view_vente",
                "add_vente",
                "delete_vente",
                "view_reservation",
                "view_user",
                "change_user",
                "view_produit",
                "change_produit",
                "delete_produit",
                "view_categorie",
                "change_categorie",
            )
        )
        self.client.force_authenticate(self.admin)

    def _creer(self, titre, prix, quantite=10, statut=StatutProduit.ACTIVE, owner=None):
        produit = Produit.objects.create(
            owner=owner or self.vendeur, categorie=self.categorie, titre=titre,
            prix=Decimal(prix), status=statut, localisation="Rohero",
        )
        Inventaire.objects.create(produit=produit, quantite_totale=quantite)
        return produit

    def _vente_terminee(self, quantite=1, produit=None):
        vente = VenteService.enregistrer_vente_directe(
            produit or self.produit, self.vendeur, self.acheteur, quantite
        )
        VenteService.confirmer_paiement(vente, self.vendeur)
        VenteService.confirmer_reception(vente, self.acheteur)
        return vente


class JournalAuditTests(BaseAdministrationTests):
    def test_suspension_tracee_et_notifiee(self):
        reponse = self.client.post(
            f"/api/v1/admin/users/{self.vendeur.pk}/suspend/",
            {"motif": "Annonces frauduleuses"},
            format="json",
        )
        self.assertEqual(reponse.status_code, status.HTTP_200_OK, reponse.data)

        entree = JournalAudit.objects.get(action=ActionAudit.SUSPENSION_COMPTE)
        self.assertEqual(entree.acteur, self.admin)
        self.assertEqual(entree.acteur_username, "administrateur")
        self.assertEqual(entree.cible_type, "utilisateur")
        self.assertEqual(entree.cible_id, self.vendeur.pk)
        self.assertEqual(entree.motif, "Annonces frauduleuses")
        self.assertEqual(entree.donnees["apres"]["statut_compte"], "SUSPENDU")

        # Module 12 : l'interesse est prevenu.
        notification = Notification.objects.de(self.vendeur).get(
            type_notification=TypeNotification.COMPTE_SUSPENDU
        )
        self.assertIn("frauduleuses", notification.message)

    def test_reactivation_tracee(self):
        self.client.post(
            f"/api/v1/admin/users/{self.vendeur.pk}/suspend/",
            {"motif": "Erreur"},
            format="json",
        )
        self.client.post(
            f"/api/v1/admin/users/{self.vendeur.pk}/activate/", {}, format="json"
        )
        self.assertTrue(
            JournalAudit.objects.filter(
                action=ActionAudit.REACTIVATION_COMPTE
            ).exists()
        )
        self.assertTrue(
            Notification.objects.de(self.vendeur)
            .filter(type_notification=TypeNotification.COMPTE_REACTIVE)
            .exists()
        )

    def test_moderation_annonce_tracee_et_notifiee(self):
        reponse = self.client.post(
            f"/api/v1/admin/products/{self.produit.pk}/moderate/",
            {"status": "REMOVED", "motif": "Contrefacon"},
            format="json",
        )
        self.assertEqual(reponse.status_code, status.HTTP_200_OK, reponse.data)

        entree = JournalAudit.objects.get(action=ActionAudit.MODERATION_ANNONCE)
        self.assertEqual(entree.donnees["avant"]["status"], "ACTIVE")
        self.assertEqual(entree.donnees["apres"]["status"], "REMOVED")
        self.assertEqual(entree.cible_libelle, "Telephone")

        notification = Notification.objects.de(self.vendeur).get(
            type_notification=TypeNotification.ANNONCE_MODEREE
        )
        self.assertIn("Contrefacon", notification.message)

    def test_moderation_avis_tracee_et_notifiee(self):
        vente = self._vente_terminee()
        evaluation = EvaluationService.creer(
            vente, self.acheteur, note_produit=1, note_vendeur=1, commentaire="Insultes"
        )
        reponse = self.client.post(
            f"/api/v1/admin/reviews/{evaluation.pk}/moderate/",
            {"statut": "MASQUEE", "motif": "Propos insultants"},
            format="json",
        )
        self.assertEqual(reponse.status_code, status.HTTP_200_OK, reponse.data)

        entree = JournalAudit.objects.get(action=ActionAudit.MODERATION_AVIS)
        self.assertEqual(entree.donnees["avant"]["statut"], "VISIBLE")
        self.assertEqual(entree.donnees["apres"]["statut"], "MASQUEE")

        self.assertTrue(
            Notification.objects.de(self.acheteur)
            .filter(type_notification=TypeNotification.AVIS_MODERE)
            .exists()
        )

    def test_suppression_annonce_tracee(self):
        produit = self._creer("A supprimer", "1000")
        reponse = self.client.delete(f"/api/v1/admin/products/{produit.pk}/")
        self.assertIn(
            reponse.status_code,
            (status.HTTP_204_NO_CONTENT, status.HTTP_200_OK),
            reponse.data if hasattr(reponse, "data") else "",
        )
        entree = JournalAudit.objects.get(action=ActionAudit.SUPPRESSION_ANNONCE)
        self.assertEqual(entree.cible_libelle, "A supprimer")
        self.assertEqual(entree.donnees["avant"]["owner"], "vendeur")

    def test_modification_categorie_tracee(self):
        reponse = self.client.patch(
            f"/api/v1/admin/categories/{self.categorie.pk}/",
            {"nom": "Electronique et informatique"},
            format="json",
        )
        self.assertEqual(reponse.status_code, status.HTTP_200_OK, reponse.data)
        entree = JournalAudit.objects.get(action=ActionAudit.MODIFICATION_CATEGORIE)
        self.assertEqual(entree.donnees["avant"]["nom"], "Electronique")
        self.assertEqual(
            entree.donnees["apres"]["nom"], "Electronique et informatique"
        )

    def test_journal_consultable_et_filtrable(self):
        self.client.post(
            f"/api/v1/admin/users/{self.vendeur.pk}/suspend/",
            {"motif": "Test"},
            format="json",
        )
        self.client.post(
            f"/api/v1/admin/products/{self.produit.pk}/moderate/",
            {"status": "PAUSED", "motif": "Verification"},
            format="json",
        )

        reponse = self.client.get(URL_AUDIT)
        self.assertEqual(reponse.status_code, status.HTTP_200_OK)
        self.assertEqual(len(reponse.data["results"]), 2)

        reponse = self.client.get(f"{URL_AUDIT}?action=SUSPENSION_COMPTE")
        self.assertEqual(len(reponse.data["results"]), 1)

        reponse = self.client.get(f"{URL_AUDIT}?cible_type=produit")
        self.assertEqual(len(reponse.data["results"]), 1)

        reponse = self.client.get(f"{URL_AUDIT}?motif=verif")
        self.assertEqual(len(reponse.data["results"]), 1)

    def test_journal_en_lecture_seule(self):
        """Un journal que l'on peut retoucher ne vaut rien."""
        self.client.post(
            f"/api/v1/admin/users/{self.vendeur.pk}/suspend/",
            {"motif": "Test"},
            format="json",
        )
        entree = JournalAudit.objects.get()

        self.assertEqual(
            self.client.post(URL_AUDIT, {}, format="json").status_code,
            status.HTTP_405_METHOD_NOT_ALLOWED,
        )
        self.assertEqual(
            self.client.patch(
                f"{URL_AUDIT}{entree.pk}/", {"motif": "autre"}, format="json"
            ).status_code,
            status.HTTP_405_METHOD_NOT_ALLOWED,
        )
        self.assertEqual(
            self.client.delete(f"{URL_AUDIT}{entree.pk}/").status_code,
            status.HTTP_405_METHOD_NOT_ALLOWED,
        )
        entree.refresh_from_db()
        self.assertEqual(entree.motif, "Test")

    def test_un_type_de_cible_long_est_conserve_entier(self):
        """Non-regression : `cible_type` doit tenir les valeurs les plus longues.

        "signalement_conversation" fait 24 caracteres. Avec un champ de 20,
        PostgreSQL refusait l'insertion (SQLite, lui, tronquait en silence)
        et le classement d'un signalement echouait.
        """
        conversation = Conversation.objects.create(
            acheteur=self.acheteur, vendeur=self.vendeur, produit=self.produit,
            prix_initial=self.produit.prix,
        )
        signalement = SignalementConversation.objects.create(
            conversation=conversation, signale_par=self.acheteur, motif="ARNAQUE"
        )
        reponse = self.client.post(
            f"{URL_REPORTS}conversations/{signalement.pk}/resolve/", {}, format="json"
        )
        self.assertEqual(reponse.status_code, status.HTTP_200_OK, reponse.data)

        entree = JournalAudit.objects.get(action=ActionAudit.TRAITEMENT_SIGNALEMENT)
        self.assertEqual(entree.cible_type, "signalement_conversation")

    def test_une_panne_du_journal_ne_bloque_pas_l_action(self):
        """Contrat : une panne du journal ne doit pas annuler la decision.

        Attention a la portee de ce test : avec une exception simulee, il
        passe aussi SANS le point de sauvegarde de `AuditService`. La vraie
        panne, elle, vient du moteur : PostgreSQL marque sa transaction
        comme avortee et refuse toute requete suivante, ce que SQLite ne
        sait pas reproduire. C'est exactement ainsi que le defaut a ete
        trouve, par la suite complete sur PostgreSQL.

        Ce test verifie donc le contrat (la suspension aboutit, aucune
        ligne d'audit ne subsiste) ; la regression, elle, est gardee par
        l'execution sur le vrai moteur.
        """
        with mock.patch(
            "modules.moderation.models.JournalAudit.objects.create",
            side_effect=DatabaseError("journal indisponible"),
        ):
            reponse = self.client.post(
                f"/api/v1/admin/users/{self.vendeur.pk}/suspend/",
                {"motif": "Annonces frauduleuses"},
                format="json",
            )

        self.assertEqual(reponse.status_code, status.HTTP_200_OK, reponse.data)
        self.vendeur.refresh_from_db()
        self.assertEqual(self.vendeur.statut_compte, "SUSPENDU")
        self.assertEqual(JournalAudit.objects.count(), 0)

    def test_actions_possibles(self):
        reponse = self.client.get(f"{URL_AUDIT}actions/")
        self.assertEqual(reponse.status_code, status.HTTP_200_OK)
        valeurs = {ligne["valeur"] for ligne in reponse.data}
        self.assertIn("SUSPENSION_COMPTE", valeurs)
        self.assertIn("MODERATION_AVIS", valeurs)

    def test_sans_permission_refuse(self):
        self.client.force_authenticate(self.acheteur)
        self.assertEqual(
            self.client.get(URL_AUDIT).status_code, status.HTTP_403_FORBIDDEN
        )

    def test_anonyme_refuse(self):
        self.client.force_authenticate(None)
        self.assertEqual(
            self.client.get(URL_AUDIT).status_code, status.HTTP_401_UNAUTHORIZED
        )


class StatistiquesGlobalesTests(BaseAdministrationTests):
    def test_statistiques_completes(self):
        self._vente_terminee(quantite=2)
        ReservationService.demander(self.produit, self.acheteur, 1)
        Conversation.objects.create(
            acheteur=self.acheteur, vendeur=self.vendeur, produit=self.produit,
            prix_initial=self.produit.prix,
        )

        reponse = self.client.get(URL_STATS)
        self.assertEqual(reponse.status_code, status.HTTP_200_OK, reponse.data)
        donnees = reponse.data

        self.assertEqual(donnees["utilisateurs"]["total"], 3)
        self.assertEqual(donnees["utilisateurs"]["vendeurs"], 1)
        self.assertEqual(donnees["annonces"]["visibles"], 1)
        self.assertEqual(donnees["reservations"]["en_attente"], 1)
        self.assertEqual(donnees["ventes"]["chiffre_affaires"], "900000.00")
        self.assertEqual(donnees["ventes"]["quantite_vendue"], 2)
        self.assertEqual(donnees["messagerie"]["conversations"], 1)

    def test_le_revenu_global_ignore_les_reservations(self):
        """Meme regle qu'au module 10, a l'echelle de la plateforme."""
        ReservationService.accepter(
            ReservationService.demander(self.produit, self.acheteur, 5), self.vendeur
        )
        donnees = self.client.get(URL_STATS).data
        self.assertEqual(donnees["ventes"]["chiffre_affaires"], "0.00")
        self.assertEqual(donnees["reservations"]["acceptees"], 1)

    def test_vente_annulee_exclue(self):
        vente = self._vente_terminee(quantite=1)
        avant = self.client.get(URL_STATS).data
        self.assertEqual(avant["ventes"]["chiffre_affaires"], "450000.00")

        VenteService.annuler(vente, self.vendeur, "Erreur")
        apres = self.client.get(URL_STATS).data
        self.assertEqual(apres["ventes"]["chiffre_affaires"], "0.00")
        self.assertEqual(apres["ventes"]["statut_refunded"], 1)

    def test_comptes_suspendus_comptes(self):
        self.client.post(
            f"/api/v1/admin/users/{self.vendeur.pk}/suspend/",
            {"motif": "Test"},
            format="json",
        )
        donnees = self.client.get(URL_STATS).data
        self.assertEqual(donnees["utilisateurs"]["suspendus"], 1)

    def test_notes_moyennes_globales(self):
        vente = self._vente_terminee()
        EvaluationService.creer(
            vente, self.acheteur, note_produit=4, note_vendeur=5
        )
        donnees = self.client.get(URL_STATS).data
        self.assertEqual(donnees["evaluations"]["note_produit_moyenne"], 4.0)
        self.assertEqual(donnees["evaluations"]["note_vendeur_moyenne"], 5.0)

    def test_file_de_moderation(self):
        self._creer("En attente", "1000", statut=StatutProduit.PENDING)
        donnees = self.client.get(URL_STATS).data
        self.assertEqual(
            donnees["moderation"]["annonces_en_attente_de_moderation"], 1
        )

    def test_plateforme_vide(self):
        donnees = self.client.get(URL_STATS).data
        self.assertEqual(donnees["ventes"]["chiffre_affaires"], "0.00")
        self.assertIsNone(donnees["reservations"]["taux_de_transformation"])
        self.assertIsNone(donnees["evaluations"]["note_vendeur_moyenne"])

    def test_permission_dediee(self):
        """`consulter_statistiques` sans le reste suffit, et inversement."""
        observateur = User.objects.create_user(
            username="observateur", password="MotDePasse2026"
        )
        observateur.groups.add(
            groupe_avec("Stats Seules", "consulter_statistiques")
        )
        self.client.force_authenticate(observateur)
        self.assertEqual(
            self.client.get(URL_STATS).status_code, status.HTTP_200_OK
        )
        # Mais pas le journal d'audit.
        self.assertEqual(
            self.client.get(URL_AUDIT).status_code, status.HTTP_403_FORBIDDEN
        )

    def test_sans_permission_refuse(self):
        self.client.force_authenticate(self.acheteur)
        self.assertEqual(
            self.client.get(URL_STATS).status_code, status.HTTP_403_FORBIDDEN
        )


class SignalementsTests(BaseAdministrationTests):
    def setUp(self):
        super().setUp()
        self.conversation = Conversation.objects.create(
            acheteur=self.acheteur, vendeur=self.vendeur, produit=self.produit,
            prix_initial=self.produit.prix,
        )
        self.signalement_conversation = SignalementConversation.objects.create(
            conversation=self.conversation,
            signale_par=self.acheteur,
            motif="ARNAQUE",
            description="Demande de paiement a l'avance",
        )

        vente = self._vente_terminee()
        self.evaluation = EvaluationService.creer(
            vente, self.acheteur, note_produit=1, note_vendeur=1, commentaire="Insultes"
        )
        self.signalement_avis = EvaluationService.signaler(
            self.evaluation, self.vendeur, "INSULTE"
        )

    def test_resume(self):
        reponse = self.client.get(URL_REPORTS)
        self.assertEqual(reponse.status_code, status.HTTP_200_OK, reponse.data)
        self.assertEqual(reponse.data["conversations_en_attente"], 1)
        self.assertEqual(reponse.data["avis_en_attente"], 1)
        self.assertEqual(reponse.data["conversations_traitees"], 0)

    def test_liste_des_signalements_de_conversations(self):
        reponse = self.client.get(f"{URL_REPORTS}conversations/")
        self.assertEqual(reponse.status_code, status.HTTP_200_OK)
        self.assertEqual(len(reponse.data["results"]), 1)
        self.assertEqual(reponse.data["results"][0]["motif"], "ARNAQUE")

    def test_liste_des_signalements_d_avis(self):
        reponse = self.client.get(f"{URL_REPORTS}reviews/")
        self.assertEqual(len(reponse.data["results"]), 1)
        self.assertEqual(reponse.data["results"][0]["motif"], "INSULTE")

    def test_classer_un_signalement_de_conversation(self):
        reponse = self.client.post(
            f"{URL_REPORTS}conversations/{self.signalement_conversation.pk}/resolve/",
            {},
            format="json",
        )
        self.assertEqual(reponse.status_code, status.HTTP_200_OK, reponse.data)

        self.signalement_conversation.refresh_from_db()
        self.assertIsNotNone(self.signalement_conversation.traite_le)
        # La decision est inscrite au journal.
        self.assertTrue(
            JournalAudit.objects.filter(
                action=ActionAudit.TRAITEMENT_SIGNALEMENT
            ).exists()
        )
        # Il sort de la file.
        self.assertEqual(
            len(self.client.get(f"{URL_REPORTS}conversations/").data["results"]), 0
        )
        self.assertEqual(
            len(
                self.client.get(
                    f"{URL_REPORTS}conversations/?traites=true"
                ).data["results"]
            ),
            1,
        )

    def test_classer_un_signalement_d_avis(self):
        reponse = self.client.post(
            f"{URL_REPORTS}reviews/{self.signalement_avis.pk}/resolve/",
            {},
            format="json",
        )
        self.assertEqual(reponse.status_code, status.HTTP_200_OK, reponse.data)
        self.signalement_avis.refresh_from_db()
        self.assertIsNotNone(self.signalement_avis.traite_le)
        # L'avis lui-meme n'a pas ete touche : le signalement etait infonde.
        self.evaluation.refresh_from_db()
        self.assertEqual(self.evaluation.statut, StatutEvaluation.VISIBLE)

    def test_moderer_un_avis_classe_ses_signalements(self):
        self.client.post(
            f"/api/v1/admin/reviews/{self.evaluation.pk}/moderate/",
            {"statut": "MASQUEE", "motif": "Insultes"},
            format="json",
        )
        self.signalement_avis.refresh_from_db()
        self.assertIsNotNone(self.signalement_avis.traite_le)

    def test_lecture_seule_sans_permission_de_changement(self):
        """La regle de groupe du projet, sur la file de moderation."""
        lecteur = User.objects.create_user(
            username="lecteur", password="MotDePasse2026"
        )
        lecteur.groups.add(
            groupe_avec(
                "Lecture Signalements",
                "view_signalementconversation",
                "view_evaluation",
            )
        )
        self.client.force_authenticate(lecteur)

        self.assertEqual(
            self.client.get(f"{URL_REPORTS}conversations/").status_code,
            status.HTTP_200_OK,
        )
        reponse = self.client.post(
            f"{URL_REPORTS}conversations/{self.signalement_conversation.pk}/resolve/",
            {},
            format="json",
        )
        self.assertEqual(reponse.status_code, status.HTTP_403_FORBIDDEN)
        self.signalement_conversation.refresh_from_db()
        self.assertIsNone(self.signalement_conversation.traite_le)

    def test_sans_permission_refuse(self):
        self.client.force_authenticate(self.acheteur)
        self.assertEqual(
            self.client.get(URL_REPORTS).status_code, status.HTTP_403_FORBIDDEN
        )


class ConfigurationTests(BaseAdministrationTests):
    def test_definir_un_parametre(self):
        reponse = self.client.post(
            URL_SETTINGS,
            {
                "cle": "RESERVATION_DUREE_HEURES",
                "valeur": "24",
                "type_valeur": "ENTIER",
                "description": "Une journee",
            },
            format="json",
        )
        self.assertEqual(reponse.status_code, status.HTTP_201_CREATED, reponse.data)

        parametre = ParametrePlateforme.objects.get()
        self.assertEqual(parametre.valeur_typee, 24)
        self.assertEqual(parametre.modifie_par, self.admin)
        # La modification est tracee.
        self.assertTrue(
            JournalAudit.objects.filter(
                action=ActionAudit.MODIFICATION_PARAMETRE
            ).exists()
        )

    def test_un_parametre_prend_effet_immediatement(self):
        """Le vrai test de la "configuration de la plateforme"."""
        ParametrePlateforme.objects.create(
            cle="RESERVATION_DUREE_HEURES",
            valeur="1",
            type_valeur=TypeValeurParametre.ENTIER,
        )
        duree = ReservationService.duree_de_validite()
        self.assertEqual(duree.total_seconds(), 3600)

    def test_le_seuil_de_stock_est_configurable(self):
        from modules.notifications.services import NotificationService

        self.assertEqual(NotificationService.seuil_de_stock_faible(), 3)
        ParametrePlateforme.objects.create(
            cle="STOCK_SEUIL_ALERTE",
            valeur="7",
            type_valeur=TypeValeurParametre.ENTIER,
        )
        self.assertEqual(NotificationService.seuil_de_stock_faible(), 7)

    def test_le_delai_des_avis_est_configurable(self):
        self.assertEqual(EvaluationService.delai_de_modification(), 48)
        ParametrePlateforme.objects.create(
            cle="EVALUATION_DELAI_MODIFICATION_HEURES",
            valeur="2",
            type_valeur=TypeValeurParametre.ENTIER,
        )
        self.assertEqual(EvaluationService.delai_de_modification(), 2)

    def test_table_vide_le_env_fait_foi(self):
        """Une plateforme neuve se comporte comme avant le module 14."""
        self.assertFalse(ParametrePlateforme.objects.exists())
        self.assertEqual(
            ReservationService.duree_de_validite().total_seconds(), 72 * 3600
        )

    def test_valeur_incompatible_refusee(self):
        reponse = self.client.post(
            URL_SETTINGS,
            {"cle": "STOCK_SEUIL_ALERTE", "valeur": "beaucoup", "type_valeur": "ENTIER"},
            format="json",
        )
        self.assertEqual(reponse.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("valeur", reponse.data["errors"])
        self.assertFalse(ParametrePlateforme.objects.exists())

    def test_modifier_un_parametre_est_trace(self):
        parametre = ParametrePlateforme.objects.create(
            cle="STOCK_SEUIL_ALERTE",
            valeur="3",
            type_valeur=TypeValeurParametre.ENTIER,
        )
        reponse = self.client.patch(
            f"{URL_SETTINGS}{parametre.pk}/", {"valeur": "10"}, format="json"
        )
        self.assertEqual(reponse.status_code, status.HTTP_200_OK, reponse.data)
        entree = JournalAudit.objects.get(action=ActionAudit.MODIFICATION_PARAMETRE)
        self.assertEqual(entree.donnees["avant"]["valeur"], "3")
        self.assertEqual(entree.donnees["apres"]["valeur"], "10")

    def test_supprimer_un_parametre_rend_le_defaut(self):
        parametre = ParametrePlateforme.objects.create(
            cle="STOCK_SEUIL_ALERTE",
            valeur="9",
            type_valeur=TypeValeurParametre.ENTIER,
        )
        from modules.notifications.services import NotificationService

        self.assertEqual(NotificationService.seuil_de_stock_faible(), 9)

        self.client.delete(f"{URL_SETTINGS}{parametre.pk}/")
        self.assertEqual(NotificationService.seuil_de_stock_faible(), 3)

    def test_cles_connues(self):
        reponse = self.client.get(f"{URL_SETTINGS}known-keys/")
        self.assertEqual(reponse.status_code, status.HTTP_200_OK)
        cles = {ligne["cle"]: ligne for ligne in reponse.data}
        self.assertIn("RESERVATION_DUREE_HEURES", cles)
        self.assertFalse(cles["RESERVATION_DUREE_HEURES"]["definie_en_base"])
        self.assertEqual(cles["RESERVATION_DUREE_HEURES"]["valeur_active"], "72")

    def test_lecture_seule_sans_permission_d_ecriture(self):
        lecteur = User.objects.create_user(
            username="lecteur_config", password="MotDePasse2026"
        )
        lecteur.groups.add(
            groupe_avec("Lecture Config", "view_parametreplateforme")
        )
        self.client.force_authenticate(lecteur)

        self.assertEqual(
            self.client.get(URL_SETTINGS).status_code, status.HTTP_200_OK
        )
        reponse = self.client.post(
            URL_SETTINGS,
            {"cle": "X", "valeur": "1", "type_valeur": "TEXTE"},
            format="json",
        )
        self.assertEqual(reponse.status_code, status.HTTP_403_FORBIDDEN)

    def test_sans_permission_refuse(self):
        self.client.force_authenticate(self.acheteur)
        self.assertEqual(
            self.client.get(URL_SETTINGS).status_code, status.HTTP_403_FORBIDDEN
        )


class LitigesTests(BaseAdministrationTests):
    def test_historique_du_stock(self):
        reservation = ReservationService.accepter(
            ReservationService.demander(self.produit, self.acheteur, 3), self.vendeur
        )
        ReservationService.annuler(reservation, self.vendeur, "Client absent")

        reponse = self.client.get(URL_MOUVEMENTS)
        self.assertEqual(reponse.status_code, status.HTTP_200_OK, reponse.data)
        types = [ligne["type_mouvement"] for ligne in reponse.data["results"]]
        self.assertIn("RESERVATION", types)
        self.assertIn("LIBERATION", types)

        # La photographie du stock permet de relire l'histoire sans calcul.
        ligne = next(
            l for l in reponse.data["results"] if l["type_mouvement"] == "LIBERATION"
        )
        self.assertEqual(ligne["quantite_reservee_apres"], 0)
        self.assertEqual(ligne["quantite_disponible_apres"], 10)
        self.assertEqual(ligne["vendeur_username"], "vendeur")

    def test_filtres_de_l_historique(self):
        self._vente_terminee(quantite=1)
        reponse = self.client.get(f"{URL_MOUVEMENTS}?type_mouvement=VENTE")
        self.assertEqual(len(reponse.data["results"]), 1)

        reponse = self.client.get(f"{URL_MOUVEMENTS}?owner_username=vendeur")
        self.assertEqual(len(reponse.data["results"]), 1)

        reponse = self.client.get(f"{URL_MOUVEMENTS}?titre=telephone")
        self.assertEqual(len(reponse.data["results"]), 1)

    def test_toutes_les_ventes(self):
        vente = self._vente_terminee()
        reponse = self.client.get(URL_VENTES_ADMIN)
        identifiants = [ligne["id"] for ligne in reponse.data["results"]]
        self.assertEqual(identifiants, [vente.pk])

    def test_toutes_les_reservations(self):
        reservation = ReservationService.demander(self.produit, self.acheteur, 2)
        reponse = self.client.get(URL_RESERVATIONS_ADMIN)
        identifiants = [ligne["id"] for ligne in reponse.data["results"]]
        self.assertEqual(identifiants, [reservation.pk])

    def test_aucune_ecriture_possible(self):
        """L'administration constate, elle ne modifie pas une vente."""
        vente = self._vente_terminee()
        for methode, url in (
            (self.client.post, URL_VENTES_ADMIN),
            (self.client.delete, f"{URL_VENTES_ADMIN}{vente.pk}/"),
            (self.client.post, URL_MOUVEMENTS),
        ):
            reponse = methode(url) if methode is self.client.delete else methode(
                url, {}, format="json"
            )
            self.assertEqual(
                reponse.status_code, status.HTTP_405_METHOD_NOT_ALLOWED, url
            )

    def test_permissions_independantes(self):
        """Voir le stock n'ouvre pas les ventes, et inversement."""
        stockiste = User.objects.create_user(
            username="stockiste", password="MotDePasse2026"
        )
        stockiste.groups.add(groupe_avec("Stock Seul", "view_mouvementstock"))
        self.client.force_authenticate(stockiste)

        self.assertEqual(
            self.client.get(URL_MOUVEMENTS).status_code, status.HTTP_200_OK
        )
        self.assertEqual(
            self.client.get(URL_VENTES_ADMIN).status_code, status.HTTP_403_FORBIDDEN
        )
        self.assertEqual(
            self.client.get(URL_RESERVATIONS_ADMIN).status_code,
            status.HTTP_403_FORBIDDEN,
        )

    def test_sans_permission_refuse(self):
        self.client.force_authenticate(self.acheteur)
        for url in (URL_MOUVEMENTS, URL_VENTES_ADMIN, URL_RESERVATIONS_ADMIN):
            self.assertEqual(
                self.client.get(url).status_code, status.HTTP_403_FORBIDDEN, url
            )
