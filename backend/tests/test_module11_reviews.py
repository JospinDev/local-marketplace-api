"""Tests du module 11 : evaluations, reputation et moderation.

La regle la plus importante est celle qui relie l'avis a une vente TERMINEE :
sans elle, n'importe qui pourrait noter n'importe qui.
"""
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import Group, Permission
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from modules.categories.models import Categorie
from modules.products.models import Inventaire, Produit, StatutProduit
from modules.reviews.models import (
    Evaluation,
    SignalementEvaluation,
    StatutEvaluation,
)
from modules.reviews.services import EvaluationService
from modules.sales.models import Vente
from modules.sales.services import VenteService

User = get_user_model()
URL = "/api/v1/reviews/"
URL_ADMIN = "/api/v1/admin/reviews/"


class BaseEvaluationTests(APITestCase):
    def setUp(self):
        self.categorie = Categorie.objects.create(nom="Instruments")
        self.vendeur = User.objects.create_user(
            username="vendeur", password="MotDePasse2026"
        )
        self.acheteur = User.objects.create_user(
            username="acheteur", password="MotDePasse2026"
        )
        self.tiers = User.objects.create_user(
            username="tiers", password="MotDePasse2026"
        )

        self.produit = self._creer("Guitare Yamaha", "250000")
        self.vente = self._vente_terminee(self.acheteur, quantite=1)
        self.client.force_authenticate(self.acheteur)

    def _creer(self, titre, prix, quantite=10, owner=None):
        produit = Produit.objects.create(
            owner=owner or self.vendeur, categorie=self.categorie, titre=titre,
            prix=Decimal(prix), status=StatutProduit.ACTIVE,
            localisation="Rohero, Bujumbura",
        )
        Inventaire.objects.create(produit=produit, quantite_totale=quantite)
        return produit

    def _vente_terminee(self, acheteur, quantite=1, produit=None):
        """Parcours complet du module 9 : declaree, payee, recue."""
        vente = VenteService.enregistrer_vente_directe(
            produit or self.produit, self.vendeur, acheteur, quantite
        )
        VenteService.confirmer_paiement(vente, self.vendeur)
        VenteService.confirmer_reception(vente, acheteur)
        return vente

    def _avis(self, vente=None, auteur=None, produit=4, vendeur=5, commentaire=""):
        return EvaluationService.creer(
            vente or self.vente,
            auteur or self.acheteur,
            note_produit=produit,
            note_vendeur=vendeur,
            commentaire=commentaire,
        )


class DepotAvisTests(BaseEvaluationTests):
    def test_deposer_un_avis(self):
        reponse = self.client.post(
            URL,
            {
                "vente": self.vente.pk,
                "note_produit": 5,
                "note_vendeur": 4,
                "commentaire": "Guitare conforme, vendeur ponctuel.",
            },
            format="json",
        )
        self.assertEqual(reponse.status_code, status.HTTP_201_CREATED, reponse.data)

        evaluation = Evaluation.objects.get()
        # Produit et vendeur sont deduits de la vente, jamais saisis.
        self.assertEqual(evaluation.produit, self.produit)
        self.assertEqual(evaluation.vendeur, self.vendeur)
        self.assertEqual(evaluation.auteur, self.acheteur)
        self.assertEqual(evaluation.statut, StatutEvaluation.VISIBLE)
        self.assertEqual(evaluation.note_globale, 4.5)

    def test_vente_non_terminee_refusee(self):
        """Regle : une evaluation doit porter sur une vente terminee."""
        vente = VenteService.enregistrer_vente_directe(
            self.produit, self.vendeur, self.acheteur, 1
        )
        reponse = self.client.post(
            URL,
            {"vente": vente.pk, "note_produit": 5, "note_vendeur": 5},
            format="json",
        )
        self.assertEqual(reponse.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("buyer-confirmation", str(reponse.data["errors"]))
        self.assertFalse(Evaluation.objects.exists())

    def test_vente_payee_mais_non_confirmee_par_l_acheteur_refusee(self):
        """Le double accuse du module 9 prend tout son sens ici."""
        vente = VenteService.enregistrer_vente_directe(
            self.produit, self.vendeur, self.acheteur, 1
        )
        VenteService.confirmer_paiement(vente, self.vendeur)

        reponse = self.client.post(
            URL,
            {"vente": vente.pk, "note_produit": 5, "note_vendeur": 5},
            format="json",
        )
        self.assertEqual(reponse.status_code, status.HTTP_400_BAD_REQUEST)

    def test_le_vendeur_ne_peut_pas_evaluer_sa_propre_vente(self):
        """Regle : un utilisateur ne peut pas evaluer son propre produit."""
        self.client.force_authenticate(self.vendeur)
        reponse = self.client.post(
            URL,
            {"vente": self.vente.pk, "note_produit": 5, "note_vendeur": 5},
            format="json",
        )
        self.assertEqual(reponse.status_code, status.HTTP_403_FORBIDDEN)
        self.assertFalse(Evaluation.objects.exists())

    def test_un_tiers_ne_peut_pas_evaluer(self):
        self.client.force_authenticate(self.tiers)
        reponse = self.client.post(
            URL,
            {"vente": self.vente.pk, "note_produit": 5, "note_vendeur": 5},
            format="json",
        )
        self.assertEqual(reponse.status_code, status.HTTP_403_FORBIDDEN)

    def test_pas_deux_avis_sur_la_meme_vente(self):
        self._avis()
        reponse = self.client.post(
            URL,
            {"vente": self.vente.pk, "note_produit": 1, "note_vendeur": 1},
            format="json",
        )
        self.assertEqual(reponse.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(Evaluation.objects.count(), 1)

    def test_deux_ventes_donnent_droit_a_deux_avis(self):
        autre_vente = self._vente_terminee(self.acheteur, quantite=1)
        self._avis()
        reponse = self.client.post(
            URL,
            {"vente": autre_vente.pk, "note_produit": 3, "note_vendeur": 3},
            format="json",
        )
        self.assertEqual(reponse.status_code, status.HTTP_201_CREATED, reponse.data)
        self.assertEqual(Evaluation.objects.count(), 2)

    def test_note_hors_echelle_refusee(self):
        """Echelle de 1 a 5 etoiles."""
        for note in (0, 6, -1):
            reponse = self.client.post(
                URL,
                {"vente": self.vente.pk, "note_produit": note, "note_vendeur": 3},
                format="json",
            )
            self.assertEqual(
                reponse.status_code, status.HTTP_400_BAD_REQUEST, f"note={note}"
            )
        self.assertFalse(Evaluation.objects.exists())

    def test_commentaire_facultatif(self):
        reponse = self.client.post(
            URL,
            {"vente": self.vente.pk, "note_produit": 4, "note_vendeur": 4},
            format="json",
        )
        self.assertEqual(reponse.status_code, status.HTTP_201_CREATED, reponse.data)
        self.assertEqual(Evaluation.objects.get().commentaire, "")

    def test_anonyme_refuse(self):
        self.client.force_authenticate(None)
        reponse = self.client.post(
            URL,
            {"vente": self.vente.pk, "note_produit": 4, "note_vendeur": 4},
            format="json",
        )
        self.assertEqual(reponse.status_code, status.HTTP_401_UNAUTHORIZED)


class ModificationRetraitTests(BaseEvaluationTests):
    def setUp(self):
        super().setUp()
        self.evaluation = self._avis(produit=2, vendeur=2, commentaire="Decu")

    def test_modifier_son_avis(self):
        reponse = self.client.patch(
            f"{URL}{self.evaluation.pk}/",
            {"note_produit": 5, "commentaire": "Le vendeur a tout arrange"},
            format="json",
        )
        self.assertEqual(reponse.status_code, status.HTTP_200_OK, reponse.data)

        self.evaluation.refresh_from_db()
        self.assertEqual(self.evaluation.note_produit, 5)
        self.assertEqual(self.evaluation.note_vendeur, 2)  # inchangee
        self.assertIsNotNone(self.evaluation.modifiee_le)

    def test_modification_vide_refusee(self):
        reponse = self.client.patch(
            f"{URL}{self.evaluation.pk}/", {}, format="json"
        )
        self.assertEqual(reponse.status_code, status.HTTP_400_BAD_REQUEST)

    def test_le_vendeur_ne_modifie_pas_l_avis_recu(self):
        self.client.force_authenticate(self.vendeur)
        reponse = self.client.patch(
            f"{URL}{self.evaluation.pk}/", {"note_vendeur": 5}, format="json"
        )
        self.assertEqual(reponse.status_code, status.HTTP_403_FORBIDDEN)
        self.evaluation.refresh_from_db()
        self.assertEqual(self.evaluation.note_vendeur, 2)

    def test_delai_de_modification_depasse(self):
        Evaluation.objects.filter(pk=self.evaluation.pk).update(
            created_at=timezone.now() - timedelta(hours=49)
        )
        reponse = self.client.patch(
            f"{URL}{self.evaluation.pk}/", {"note_vendeur": 5}, format="json"
        )
        self.assertEqual(reponse.status_code, status.HTTP_400_BAD_REQUEST)
        # Erreur generale (clef `detail`) : le gestionnaire d'exceptions du
        # projet la remonte dans `message`, pas dans `errors`.
        self.assertIn("delai", reponse.data["message"].lower())

    def test_delai_configurable(self):
        Evaluation.objects.filter(pk=self.evaluation.pk).update(
            created_at=timezone.now() - timedelta(hours=3)
        )
        with self.settings(EVALUATION_DELAI_MODIFICATION_HEURES=2):
            reponse = self.client.patch(
                f"{URL}{self.evaluation.pk}/", {"note_vendeur": 5}, format="json"
            )
        self.assertEqual(reponse.status_code, status.HTTP_400_BAD_REQUEST)

        with self.settings(EVALUATION_DELAI_MODIFICATION_HEURES=72):
            reponse = self.client.patch(
                f"{URL}{self.evaluation.pk}/", {"note_vendeur": 5}, format="json"
            )
        self.assertEqual(reponse.status_code, status.HTTP_200_OK, reponse.data)

    def test_retrait_est_une_suppression_douce(self):
        reponse = self.client.delete(f"{URL}{self.evaluation.pk}/")
        self.assertEqual(reponse.status_code, status.HTTP_200_OK, reponse.data)

        self.evaluation.refresh_from_db()
        self.assertEqual(self.evaluation.statut, StatutEvaluation.RETIREE)
        # La ligne existe toujours : l'historique reste verifiable.
        self.assertEqual(Evaluation.objects.count(), 1)
        # Mais elle ne compte plus.
        self.assertEqual(Evaluation.objects.valides().count(), 0)

    def test_un_avis_retire_puis_corrige_redevient_visible(self):
        EvaluationService.retirer(self.evaluation, self.acheteur)
        self.client.patch(
            f"{URL}{self.evaluation.pk}/", {"note_produit": 4}, format="json"
        )
        self.evaluation.refresh_from_db()
        self.assertEqual(self.evaluation.statut, StatutEvaluation.VISIBLE)


class ReputationTests(BaseEvaluationTests):
    def test_moyennes_du_vendeur(self):
        self._avis(produit=5, vendeur=4)
        autre_vente = self._vente_terminee(self.tiers, quantite=1)
        self._avis(vente=autre_vente, auteur=self.tiers, produit=3, vendeur=2)

        reponse = self.client.get(f"{URL}my-rating/")
        self.assertEqual(reponse.status_code, status.HTTP_200_OK)
        # L'acheteur n'a recu aucun avis en tant que vendeur.
        self.assertEqual(reponse.data["nombre_evaluations"], 0)

        self.client.force_authenticate(self.vendeur)
        reponse = self.client.get(f"{URL}my-rating/")
        self.assertEqual(reponse.data["nombre_evaluations"], 2)
        self.assertEqual(reponse.data["note_vendeur"], 3.0)  # (4 + 2) / 2
        self.assertEqual(reponse.data["note_produit"], 4.0)  # (5 + 3) / 2

    def test_un_avis_masque_sort_des_moyennes(self):
        """Regle : les notes se calculent sur les evaluations valides."""
        premier = self._avis(produit=5, vendeur=5)
        autre_vente = self._vente_terminee(self.tiers, quantite=1)
        self._avis(vente=autre_vente, auteur=self.tiers, produit=1, vendeur=1)

        self.client.force_authenticate(self.vendeur)
        avant = self.client.get(f"{URL}my-rating/").data
        self.assertEqual(avant["note_vendeur"], 3.0)

        EvaluationService.moderer(
            Evaluation.objects.exclude(pk=premier.pk).get(),
            self.vendeur,
            StatutEvaluation.MASQUEE,
            "Propos insultants",
        )
        apres = self.client.get(f"{URL}my-rating/").data
        self.assertEqual(apres["nombre_evaluations"], 1)
        self.assertEqual(apres["note_vendeur"], 5.0)

    def test_un_avis_retire_sort_des_moyennes(self):
        evaluation = self._avis(produit=5, vendeur=5)
        EvaluationService.retirer(evaluation, self.acheteur)

        self.client.force_authenticate(self.vendeur)
        reponse = self.client.get(f"{URL}my-rating/")
        self.assertEqual(reponse.data["nombre_evaluations"], 0)
        self.assertIsNone(reponse.data["note_vendeur"])

    def test_vendeur_sans_avis(self):
        self.client.force_authenticate(self.vendeur)
        reponse = self.client.get(f"{URL}my-rating/")
        self.assertIsNone(reponse.data["note_vendeur"])
        self.assertEqual(reponse.data["nombre_evaluations"], 0)


class ListesEtFiltresTests(BaseEvaluationTests):
    def setUp(self):
        super().setUp()
        self.mon_avis = self._avis(produit=5, vendeur=4, commentaire="Parfait")
        # Un avis recu par l'acheteur en tant que vendeur.
        self.mon_produit = self._creer("Piano", "900000", owner=self.acheteur)
        vente = VenteService.enregistrer_vente_directe(
            self.mon_produit, self.acheteur, self.tiers, 1
        )
        VenteService.confirmer_paiement(vente, self.acheteur)
        VenteService.confirmer_reception(vente, self.tiers)
        self.avis_recu = EvaluationService.creer(
            vente, self.tiers, note_produit=2, note_vendeur=3
        )

    def test_mes_avis(self):
        reponse = self.client.get(f"{URL}my-reviews/")
        identifiants = [ligne["id"] for ligne in reponse.data["results"]]
        self.assertEqual(identifiants, [self.mon_avis.pk])

    def test_avis_recus(self):
        reponse = self.client.get(f"{URL}received/")
        identifiants = [ligne["id"] for ligne in reponse.data["results"]]
        self.assertEqual(identifiants, [self.avis_recu.pk])

    def test_liste_globale_contient_les_deux(self):
        reponse = self.client.get(URL)
        identifiants = {ligne["id"] for ligne in reponse.data["results"]}
        self.assertEqual(identifiants, {self.mon_avis.pk, self.avis_recu.pk})

    def test_avis_d_un_tiers_invisible(self):
        autre = User.objects.create_user(
            username="curieux", password="MotDePasse2026"
        )
        self.client.force_authenticate(autre)
        self.assertEqual(len(self.client.get(URL).data["results"]), 0)
        self.assertEqual(
            self.client.get(f"{URL}{self.mon_avis.pk}/").status_code,
            status.HTTP_404_NOT_FOUND,
        )

    def test_filtre_note(self):
        reponse = self.client.get(f"{URL}?note_produit__lte=2")
        identifiants = [ligne["id"] for ligne in reponse.data["results"]]
        self.assertEqual(identifiants, [self.avis_recu.pk])

    def test_filtre_avec_commentaire(self):
        reponse = self.client.get(f"{URL}?avec_commentaire=true")
        identifiants = [ligne["id"] for ligne in reponse.data["results"]]
        self.assertEqual(identifiants, [self.mon_avis.pk])

    def test_filtre_titre(self):
        reponse = self.client.get(f"{URL}?titre=piano")
        identifiants = [ligne["id"] for ligne in reponse.data["results"]]
        self.assertEqual(identifiants, [self.avis_recu.pk])

    def test_filtre_localisation_icontains(self):
        reponse = self.client.get(f"{URL}?localisation=rohero")
        self.assertEqual(len(reponse.data["results"]), 2)
        reponse = self.client.get(f"{URL}?localisation=ngozi")
        self.assertEqual(len(reponse.data["results"]), 0)


class SignalementTests(BaseEvaluationTests):
    def setUp(self):
        super().setUp()
        self.evaluation = self._avis(produit=1, vendeur=1, commentaire="Propos durs")

    def test_le_vendeur_signale_un_avis(self):
        self.client.force_authenticate(self.vendeur)
        reponse = self.client.post(
            f"{URL}{self.evaluation.pk}/report/",
            {"motif": "INSULTE", "description": "Insultes personnelles"},
            format="json",
        )
        self.assertEqual(reponse.status_code, status.HTTP_201_CREATED, reponse.data)
        self.assertEqual(SignalementEvaluation.objects.count(), 1)

    def test_un_tiers_peut_signaler(self):
        """Un avis insultant nuit a toute la plateforme."""
        self.client.force_authenticate(self.tiers)
        reponse = self.client.post(
            f"{URL}{self.evaluation.pk}/report/", {"motif": "SPAM"}, format="json"
        )
        self.assertEqual(reponse.status_code, status.HTTP_201_CREATED, reponse.data)

    def test_l_auteur_ne_signale_pas_son_propre_avis(self):
        reponse = self.client.post(
            f"{URL}{self.evaluation.pk}/report/", {"motif": "AUTRE"}, format="json"
        )
        self.assertEqual(reponse.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(SignalementEvaluation.objects.exists())

    def test_pas_deux_signalements_non_traites(self):
        self.client.force_authenticate(self.vendeur)
        self.client.post(
            f"{URL}{self.evaluation.pk}/report/", {"motif": "FAUX"}, format="json"
        )
        reponse = self.client.post(
            f"{URL}{self.evaluation.pk}/report/", {"motif": "FAUX"}, format="json"
        )
        self.assertEqual(reponse.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(SignalementEvaluation.objects.count(), 1)

    def test_motif_invalide(self):
        self.client.force_authenticate(self.vendeur)
        reponse = self.client.post(
            f"{URL}{self.evaluation.pk}/report/",
            {"motif": "PARCE_QUE"},
            format="json",
        )
        self.assertEqual(reponse.status_code, status.HTTP_400_BAD_REQUEST)


class ModerationTests(BaseEvaluationTests):
    def setUp(self):
        super().setUp()
        self.evaluation = self._avis(produit=1, vendeur=1, commentaire="Insultes")
        EvaluationService.signaler(self.evaluation, self.vendeur, "INSULTE")

        self.moderateur = User.objects.create_user(
            username="moderateur_avis", password="MotDePasse2026"
        )
        groupe = Group.objects.create(name="Moderation Avis Test")
        groupe.permissions.add(
            Permission.objects.get(codename="view_evaluation"),
            Permission.objects.get(codename="change_evaluation"),
        )
        self.moderateur.groups.add(groupe)

        # Un groupe volontairement limite a la lecture.
        self.observateur = User.objects.create_user(
            username="observateur_avis", password="MotDePasse2026"
        )
        lecture_seule = Group.objects.create(name="Lecture Avis Test")
        lecture_seule.permissions.add(
            Permission.objects.get(codename="view_evaluation")
        )
        self.observateur.groups.add(lecture_seule)

    def test_masquer_un_avis(self):
        self.client.force_authenticate(self.moderateur)
        reponse = self.client.post(
            f"{URL_ADMIN}{self.evaluation.pk}/moderate/",
            {"statut": "MASQUEE", "motif": "Propos insultants"},
            format="json",
        )
        self.assertEqual(reponse.status_code, status.HTTP_200_OK, reponse.data)

        self.evaluation.refresh_from_db()
        self.assertEqual(self.evaluation.statut, StatutEvaluation.MASQUEE)
        self.assertEqual(self.evaluation.motif_moderation, "Propos insultants")
        # La decision est imputable : on sait qui a tranche, et quand.
        self.assertEqual(self.evaluation.moderee_par, self.moderateur)
        self.assertIsNotNone(self.evaluation.moderee_le)
        # Le signalement est considere comme traite.
        self.assertFalse(
            SignalementEvaluation.objects.filter(traite_le__isnull=True).exists()
        )

    def test_la_moderation_ne_reecrit_pas_le_contenu(self):
        EvaluationService.moderer(
            self.evaluation, self.moderateur, StatutEvaluation.MASQUEE, "Insultes"
        )
        self.evaluation.refresh_from_db()
        # Les notes et le texte restent ceux de leur auteur.
        self.assertEqual(self.evaluation.note_produit, 1)
        self.assertEqual(self.evaluation.commentaire, "Insultes")

    def test_reafficher_un_avis(self):
        EvaluationService.moderer(
            self.evaluation, self.moderateur, StatutEvaluation.MASQUEE, "Erreur"
        )
        self.client.force_authenticate(self.moderateur)
        self.client.post(
            f"{URL_ADMIN}{self.evaluation.pk}/moderate/",
            {"statut": "VISIBLE"},
            format="json",
        )
        self.evaluation.refresh_from_db()
        self.assertEqual(self.evaluation.statut, StatutEvaluation.VISIBLE)

    def test_groupe_en_lecture_seule_ne_peut_pas_moderer(self):
        """Regle du projet : un groupe ne fait QUE ce qu'il autorise."""
        self.client.force_authenticate(self.observateur)
        # La lecture passe...
        self.assertEqual(
            self.client.get(URL_ADMIN).status_code, status.HTTP_200_OK
        )
        self.assertEqual(
            self.client.get(f"{URL_ADMIN}reports/").status_code, status.HTTP_200_OK
        )
        # ... mais pas la moderation.
        reponse = self.client.post(
            f"{URL_ADMIN}{self.evaluation.pk}/moderate/",
            {"statut": "MASQUEE"},
            format="json",
        )
        self.assertEqual(reponse.status_code, status.HTTP_403_FORBIDDEN)
        self.evaluation.refresh_from_db()
        self.assertEqual(self.evaluation.statut, StatutEvaluation.VISIBLE)

    def test_utilisateur_sans_permission_refuse(self):
        self.client.force_authenticate(self.acheteur)
        self.assertEqual(
            self.client.get(URL_ADMIN).status_code, status.HTTP_403_FORBIDDEN
        )

    def test_liste_des_signalements(self):
        self.client.force_authenticate(self.moderateur)
        reponse = self.client.get(f"{URL_ADMIN}reports/")
        self.assertEqual(reponse.status_code, status.HTTP_200_OK)
        self.assertEqual(len(reponse.data["results"]), 1)
        self.assertEqual(reponse.data["results"][0]["motif"], "INSULTE")

    def test_filtre_signalees(self):
        self.client.force_authenticate(self.moderateur)
        reponse = self.client.get(f"{URL_ADMIN}?signalees=true")
        identifiants = [ligne["id"] for ligne in reponse.data["results"]]
        self.assertEqual(identifiants, [self.evaluation.pk])

    def test_un_avis_masque_n_est_plus_modifiable(self):
        EvaluationService.moderer(
            self.evaluation, self.moderateur, StatutEvaluation.MASQUEE, "Insultes"
        )
        self.client.force_authenticate(self.acheteur)
        reponse = self.client.patch(
            f"{URL}{self.evaluation.pk}/", {"commentaire": "Pardon"}, format="json"
        )
        self.assertEqual(reponse.status_code, status.HTTP_400_BAD_REQUEST)


class AvisPublicsTests(BaseEvaluationTests):
    def setUp(self):
        super().setUp()
        self.visible = self._avis(produit=5, vendeur=4, commentaire="Tres bien")
        autre_vente = self._vente_terminee(self.tiers, quantite=1)
        self.masque = self._avis(
            vente=autre_vente, auteur=self.tiers, produit=1, vendeur=1
        )
        EvaluationService.moderer(
            self.masque, self.vendeur, StatutEvaluation.MASQUEE, "Spam"
        )
        self.client.force_authenticate(None)

    def test_avis_publics_d_un_produit(self):
        reponse = self.client.get(
            f"/api/v1/public/products/{self.produit.pk}/reviews/"
        )
        self.assertEqual(reponse.status_code, status.HTTP_200_OK)
        identifiants = [ligne["id"] for ligne in reponse.data["results"]]
        # L'avis masque n'apparait pas.
        self.assertEqual(identifiants, [self.visible.pk])
        self.assertEqual(reponse.data["reputation"]["note_produit"], 5.0)
        self.assertEqual(reponse.data["reputation"]["nombre_evaluations"], 1)

    def test_la_representation_publique_ne_fuite_rien(self):
        reponse = self.client.get(
            f"/api/v1/public/products/{self.produit.pk}/reviews/"
        )
        ligne = reponse.data["results"][0]
        for champ in ("vente", "statut", "motif_moderation", "auteur"):
            self.assertNotIn(champ, ligne)
        self.assertEqual(ligne["auteur_username"], self.acheteur.username)

    def test_produit_non_public_renvoie_404(self):
        brouillon = self._creer("Brouillon", "1000")
        brouillon.status = StatutProduit.DRAFT
        brouillon.save(update_fields=["status"])
        reponse = self.client.get(
            f"/api/v1/public/products/{brouillon.pk}/reviews/"
        )
        self.assertEqual(reponse.status_code, status.HTTP_404_NOT_FOUND)

    def test_avis_publics_d_un_vendeur(self):
        reponse = self.client.get(
            f"/api/v1/public/sellers/{self.vendeur.pk}/reviews/"
        )
        self.assertEqual(reponse.status_code, status.HTTP_200_OK)
        identifiants = [ligne["id"] for ligne in reponse.data["results"]]
        self.assertEqual(identifiants, [self.visible.pk])

        reputation = reponse.data["reputation"]
        self.assertEqual(reputation["note_vendeur"], 4.0)
        self.assertEqual(reputation["nombre_evaluations"], 1)
        # Repartition par etoile : toutes les cles sont presentes.
        self.assertEqual(reputation["repartition"]["4"], 1)
        self.assertEqual(reputation["repartition"]["1"], 0)

    def test_la_vitrine_du_vendeur_affiche_sa_note(self):
        """Le champ laisse vide par le module 5 est desormais alimente."""
        reponse = self.client.get(f"/api/v1/public/sellers/{self.vendeur.pk}/")
        self.assertEqual(reponse.status_code, status.HTTP_200_OK)
        self.assertEqual(reponse.data["note_moyenne"], 4.0)
        self.assertEqual(reponse.data["nombre_evaluations"], 1)

    def test_la_fiche_produit_affiche_sa_note(self):
        reponse = self.client.get(f"/api/v1/public/products/{self.produit.pk}/")
        self.assertEqual(reponse.status_code, status.HTTP_200_OK)
        self.assertEqual(reponse.data["reputation"]["note_produit"], 5.0)
        self.assertEqual(reponse.data["reputation"]["nombre_evaluations"], 1)

    def test_vendeur_sans_avis_garde_une_note_nulle(self):
        autre_vendeur = User.objects.create_user(
            username="vendeur_sans_avis", password="MotDePasse2026"
        )
        self._creer("Tam-tam", "40000", owner=autre_vendeur)
        reponse = self.client.get(f"/api/v1/public/sellers/{autre_vendeur.pk}/")
        self.assertIsNone(reponse.data["note_moyenne"])
        self.assertEqual(reponse.data["nombre_evaluations"], 0)
