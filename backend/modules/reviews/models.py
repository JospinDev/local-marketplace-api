"""Module 11 - Rating & Review.

Regles du cahier des charges, toutes appliquees :

- echelle de 1 a 5 etoiles ;
- deux notes distinctes : la QUALITE DU PRODUIT et la QUALITE DU VENDEUR ;
- une evaluation est toujours rattachee a une vente TERMINEE (statut
  COMPLETED, c'est-a-dire confirmee par le vendeur puis par l'acheteur) ;
- un utilisateur n'evalue pas son propre produit ;
- un utilisateur n'evalue pas deux fois la meme vente ;
- les evaluations peuvent etre moderees ;
- les moyennes ne se calculent que sur les evaluations VALIDES.

La derniere regle est la raison du champ `statut` : une evaluation masquee ou
retiree n'est jamais supprimee de la base (l'historique d'une reputation doit
rester verifiable), elle sort simplement des moyennes et des listes publiques.
"""
from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from common.models import TimeStampedModel

NOTE_MINIMALE = 1
NOTE_MAXIMALE = 5


class StatutEvaluation(models.TextChoices):
    VISIBLE = "VISIBLE", "Visible"
    MASQUEE = "MASQUEE", "Masquee par la moderation"
    RETIREE = "RETIREE", "Retiree par son auteur"


class MotifSignalementEvaluation(models.TextChoices):
    INSULTE = "INSULTE", "Propos insultants"
    FAUX = "FAUX", "Avis mensonger"
    HORS_SUJET = "HORS_SUJET", "Hors sujet"
    SPAM = "SPAM", "Spam ou publicite"
    AUTRE = "AUTRE", "Autre"


class EvaluationQuerySet(models.QuerySet):
    """Jeux de resultats des modules 11, 5 (vitrine) et 10 (tableau de bord)."""

    def valides(self):
        """Evaluations qui comptent : visibles et d'un compte actif.

        Le cahier des charges demande que les notes soient calculees a partir
        des evaluations valides. Une evaluation masquee par la moderation ou
        retiree par son auteur n'entre donc dans aucune moyenne.
        """
        return self.filter(statut=StatutEvaluation.VISIBLE, auteur__is_active=True)

    def de(self, utilisateur):
        """Evaluations ecrites par cet utilisateur."""
        return self.filter(auteur=utilisateur)

    def recues_par(self, vendeur):
        """Evaluations portant sur les ventes de ce vendeur."""
        return self.filter(vendeur=vendeur)

    def du_produit(self, produit):
        return self.filter(produit=produit)

    def complet(self):
        return self.select_related(
            "auteur", "vendeur", "produit", "produit__categorie", "vente"
        )

    def moyennes(self):
        """Notes moyennes et volume, sur les evaluations valides uniquement."""
        agregats = self.valides().aggregate(
            note_produit=models.Avg("note_produit"),
            note_vendeur=models.Avg("note_vendeur"),
            nombre=models.Count("id"),
        )
        return {
            "note_produit": (
                round(agregats["note_produit"], 2)
                if agregats["note_produit"] is not None
                else None
            ),
            "note_vendeur": (
                round(agregats["note_vendeur"], 2)
                if agregats["note_vendeur"] is not None
                else None
            ),
            "nombre_evaluations": agregats["nombre"],
        }

    def repartition(self):
        """Nombre d'avis par note de vendeur, de 1 a 5 etoiles."""
        comptes = dict(
            self.valides()
            .values_list("note_vendeur")
            .annotate(total=models.Count("id"))
            .values_list("note_vendeur", "total")
        )
        return {
            str(note): comptes.get(note, 0)
            for note in range(NOTE_MINIMALE, NOTE_MAXIMALE + 1)
        }


class Evaluation(TimeStampedModel):
    """Avis d'un acheteur sur un produit et sur son vendeur."""

    vente = models.ForeignKey(
        "sales.Vente",
        verbose_name="vente evaluee",
        # PROTECT : une vente qui porte un avis ne disparait pas. Son
        # annulation est deja une operation tracee (module 9).
        on_delete=models.PROTECT,
        related_name="evaluations",
        help_text="La vente doit etre terminee (confirmee par les deux parties).",
    )
    auteur = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="auteur",
        on_delete=models.CASCADE,
        related_name="evaluations_ecrites",
        help_text="Toujours l'acheteur de la vente.",
    )
    # Produit et vendeur sont recopies depuis la vente : ils permettent de
    # calculer les moyennes sans jointure, et restent exacts meme si la vente
    # est annulee par la suite.
    produit = models.ForeignKey(
        "products.Produit",
        verbose_name="produit evalue",
        on_delete=models.PROTECT,
        related_name="evaluations",
    )
    vendeur = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="vendeur evalue",
        on_delete=models.CASCADE,
        related_name="evaluations_recues",
    )

    note_produit = models.PositiveSmallIntegerField(
        "note du produit",
        validators=[
            MinValueValidator(NOTE_MINIMALE), MaxValueValidator(NOTE_MAXIMALE)
        ],
        help_text="Qualite du produit, de 1 a 5 etoiles.",
    )
    note_vendeur = models.PositiveSmallIntegerField(
        "note du vendeur",
        validators=[
            MinValueValidator(NOTE_MINIMALE), MaxValueValidator(NOTE_MAXIMALE)
        ],
        help_text="Qualite du vendeur (accueil, exactitude, ponctualite).",
    )
    commentaire = models.TextField("commentaire", blank=True, max_length=2000)

    statut = models.CharField(
        "statut",
        max_length=10,
        choices=StatutEvaluation.choices,
        default=StatutEvaluation.VISIBLE,
        db_index=True,
    )
    motif_moderation = models.CharField(
        "motif de moderation", max_length=255, blank=True
    )
    # Une decision de moderation doit rester explicable ET imputable : le
    # motif seul ne dit pas qui a tranche.
    moderee_par = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="moderee par",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="moderations_evaluations",
    )
    moderee_le = models.DateTimeField("moderee le", blank=True, null=True)
    modifiee_le = models.DateTimeField("modifiee le", blank=True, null=True)

    objects = EvaluationQuerySet.as_manager()

    class Meta:
        verbose_name = "evaluation"
        verbose_name_plural = "evaluations"
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["vendeur", "statut", "-created_at"]),
            models.Index(fields=["produit", "statut", "-created_at"]),
            models.Index(fields=["auteur", "-created_at"]),
        ]
        constraints = [
            # Un utilisateur n'evalue pas deux fois la meme vente.
            models.UniqueConstraint(
                fields=["vente", "auteur"], name="evaluation_unique_par_vente"
            ),
            # Un utilisateur n'evalue pas son propre produit.
            models.CheckConstraint(
                condition=~models.Q(auteur=models.F("vendeur")),
                name="evaluation_pas_son_propre_produit",
            ),
            # Echelle de 1 a 5 etoiles, garantie en base et pas seulement
            # par le serializer.
            models.CheckConstraint(
                condition=models.Q(note_produit__gte=NOTE_MINIMALE)
                & models.Q(note_produit__lte=NOTE_MAXIMALE),
                name="evaluation_note_produit_1_a_5",
            ),
            models.CheckConstraint(
                condition=models.Q(note_vendeur__gte=NOTE_MINIMALE)
                & models.Q(note_vendeur__lte=NOTE_MAXIMALE),
                name="evaluation_note_vendeur_1_a_5",
            ),
        ]

    def __str__(self):
        return (
            f"Avis {self.pk} : produit {self.note_produit}/5, "
            f"vendeur {self.note_vendeur}/5"
        )

    # ------------------------------------------------------------ proprietes
    @property
    def est_valide(self) -> bool:
        """Compte dans les moyennes et les listes publiques."""
        return self.statut == StatutEvaluation.VISIBLE

    @property
    def note_globale(self) -> float:
        return round((self.note_produit + self.note_vendeur) / 2, 2)

    @property
    def est_signalee(self) -> bool:
        return self.signalements.filter(traite_le__isnull=True).exists()


class SignalementEvaluation(TimeStampedModel):
    """Signalement d'un avis abusif, traite par la moderation."""

    evaluation = models.ForeignKey(
        Evaluation,
        verbose_name="evaluation signalee",
        on_delete=models.CASCADE,
        related_name="signalements",
    )
    signale_par = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="signale par",
        on_delete=models.CASCADE,
        related_name="signalements_evaluations",
    )
    motif = models.CharField(
        "motif", max_length=12, choices=MotifSignalementEvaluation.choices
    )
    description = models.TextField("description", blank=True)
    traite_le = models.DateTimeField("traite le", blank=True, null=True)

    class Meta:
        verbose_name = "signalement d'evaluation"
        verbose_name_plural = "signalements d'evaluations"
        ordering = ("-created_at",)
        constraints = [
            # Un utilisateur ne signale qu'une fois le meme avis tant que son
            # signalement n'a pas ete traite.
            models.UniqueConstraint(
                fields=["evaluation", "signale_par"],
                name="signalement_evaluation_unique_non_traite",
                condition=models.Q(traite_le__isnull=True),
            ),
        ]

    def __str__(self):
        return f"{self.signale_par_id} signale l'avis {self.evaluation_id}"
