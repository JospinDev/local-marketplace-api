"""Module 9 - Sales & Payment Confirmation.

Le cahier des charges est explicite : il n'y a PAS de passerelle de paiement.
Le moyen de paiement est declaratif ("Cash", "Lumicash"...), l'application
ne pretend pas verifier un transfert financier. Ce qu'elle garantit, en
revanche :

- seul le vendeur proprietaire peut declarer une vente ;
- une vente ne depasse jamais la quantite reservee ni le stock disponible ;
- le prix unitaire est FIGE dans la ligne de vente : changer le prix de
  l'annonce ensuite ne reecrit aucun revenu passe ;
- une vente confirmee n'est jamais modifiee silencieusement : son
  annulation exige un motif et laisse une trace dans l'historique des
  mouvements de stock ;
- le chiffre d'affaires se calcule sur les ventes confirmees, jamais sur
  les reservations (`VenteQuerySet.comptabilisables`).
"""
from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models

from common.models import TimeStampedModel


class StatutVente(models.TextChoices):
    """Cycle de vie decrit au paragraphe 3.4 du cahier des charges."""

    INITIATED = "INITIATED", "Declaree, en attente de confirmation"
    PAID = "PAID", "Paiement confirme par le vendeur"
    COMPLETED = "COMPLETED", "Terminee et validee par l'acheteur"
    CANCELLED = "CANCELLED", "Annulee"
    REFUNDED = "REFUNDED", "Remboursee"


class StatutPaiement(models.TextChoices):
    EN_ATTENTE = "EN_ATTENTE", "En attente"
    RECU = "RECU", "Recu"
    REMBOURSE = "REMBOURSE", "Rembourse"


class MoyenPaiement(models.TextChoices):
    """Moyens declaratifs listes par le cahier des charges."""

    CASH = "CASH", "Especes"
    LUMICASH = "LUMICASH", "Lumicash"
    ECOCASH = "ECOCASH", "EcoCash"
    VIREMENT = "VIREMENT", "Virement bancaire"
    AUTRE = "AUTRE", "Autre"


class VenteQuerySet(models.QuerySet):
    #: Seuls ces statuts entrent dans le chiffre d'affaires (module 10).
    STATUTS_COMPTABILISABLES = (StatutVente.PAID, StatutVente.COMPLETED)

    def comptabilisables(self):
        """Ventes qui comptent comme revenu reellement encaisse."""
        return self.filter(statut__in=self.STATUTS_COMPTABILISABLES)

    def de(self, utilisateur):
        return self.filter(
            models.Q(acheteur=utilisateur) | models.Q(vendeur=utilisateur)
        )

    def vendues_par(self, utilisateur):
        return self.filter(vendeur=utilisateur)

    def achetees_par(self, utilisateur):
        return self.filter(acheteur=utilisateur)

    def complet(self):
        return self.select_related("acheteur", "vendeur", "reservation").prefetch_related(
            "lignes", "lignes__produit"
        )


class Vente(TimeStampedModel):
    """Transaction reellement effectuee entre un vendeur et un acheteur."""

    reservation = models.ForeignKey(
        "reservations.Reservation",
        verbose_name="reservation d'origine",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="ventes",
        help_text=(
            "Facultatif : un vendeur peut declarer une vente directe, sans "
            "reservation prealable (client venu sur place)."
        ),
    )
    acheteur = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="acheteur",
        # PROTECT : l'historique comptable ne disparait pas avec un compte.
        # La suppression de compte est une suppression douce (module 1).
        on_delete=models.PROTECT,
        related_name="achats",
    )
    vendeur = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="vendeur",
        on_delete=models.PROTECT,
        related_name="ventes",
    )

    montant_total = models.DecimalField(
        "montant total",
        max_digits=14,
        decimal_places=2,
        default=Decimal("0"),
        validators=[MinValueValidator(Decimal("0"))],
        help_text="Somme des sous-totaux des lignes. Calcule par le serveur.",
    )
    devise = models.CharField("devise", max_length=3, default="BIF")

    moyen_paiement = models.CharField(
        "moyen de paiement declare",
        max_length=10,
        choices=MoyenPaiement.choices,
        default=MoyenPaiement.CASH,
        db_index=True,
    )
    statut_paiement = models.CharField(
        "statut du paiement",
        max_length=10,
        choices=StatutPaiement.choices,
        default=StatutPaiement.EN_ATTENTE,
        db_index=True,
    )
    statut = models.CharField(
        "statut de la vente",
        max_length=10,
        choices=StatutVente.choices,
        default=StatutVente.INITIATED,
        db_index=True,
    )

    note = models.CharField("note du vendeur", max_length=500, blank=True)

    confirmee_le = models.DateTimeField(
        "confirmee par le vendeur le", blank=True, null=True
    )
    confirmee_par_acheteur_le = models.DateTimeField(
        "confirmee par l'acheteur le",
        blank=True,
        null=True,
        help_text=(
            "Controle recommande par le cahier des charges : la confirmation "
            "de l'acheteur permet de detecter les ventes declarees a tort."
        ),
    )
    annulee_le = models.DateTimeField("annulee le", blank=True, null=True)
    motif_annulation = models.CharField("motif d'annulation", max_length=255, blank=True)

    objects = VenteQuerySet.as_manager()

    class Meta:
        verbose_name = "vente"
        verbose_name_plural = "ventes"
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["vendeur", "statut", "-created_at"]),
            models.Index(fields=["acheteur", "-created_at"]),
            models.Index(fields=["statut", "-created_at"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(montant_total__gte=0),
                name="vente_montant_positif",
            ),
            models.CheckConstraint(
                condition=~models.Q(acheteur=models.F("vendeur")),
                name="vente_pas_a_soi_meme",
            ),
        ]

    def __str__(self):
        return f"Vente {self.pk} : {self.montant_total} {self.devise} ({self.statut})"

    # ------------------------------------------------------------ proprietes
    @property
    def est_comptabilisable(self) -> bool:
        return self.statut in VenteQuerySet.STATUTS_COMPTABILISABLES

    @property
    def est_cloturee(self) -> bool:
        return self.statut in (StatutVente.CANCELLED, StatutVente.REFUNDED)

    @property
    def quantite_totale(self) -> int:
        return sum(ligne.quantite for ligne in self.lignes.all())

    def recalculer_montant(self, enregistrer: bool = True):
        """Recalcule le total a partir des lignes, jamais du prix du jour."""
        total = sum(
            (ligne.sous_total for ligne in self.lignes.all()), Decimal("0")
        )
        self.montant_total = total
        if enregistrer:
            self.save(update_fields=["montant_total", "updated_at"])
        return total

    def est_participant(self, utilisateur) -> bool:
        return utilisateur.pk in (self.acheteur_id, self.vendeur_id)


class LigneVente(TimeStampedModel):
    """Ligne d'une vente : un produit, une quantite, un prix fige.

    Le prix unitaire est copie au moment de la vente. C'est ce qui permet au
    vendeur de changer le prix de son annonce sans alterer ses revenus
    passes (regle du module 3, appliquee ici).
    """

    vente = models.ForeignKey(
        Vente, verbose_name="vente", on_delete=models.CASCADE, related_name="lignes"
    )
    produit = models.ForeignKey(
        "products.Produit",
        verbose_name="produit",
        on_delete=models.PROTECT,
        related_name="lignes_vente",
    )
    quantite = models.PositiveIntegerField("quantite vendue")
    prix_unitaire = models.DecimalField(
        "prix unitaire applique",
        max_digits=14,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0"))],
        help_text="Prix reellement convenu, fige a la vente.",
    )
    sous_total = models.DecimalField(
        "sous-total", max_digits=14, decimal_places=2, default=Decimal("0")
    )

    class Meta:
        verbose_name = "ligne de vente"
        verbose_name_plural = "lignes de vente"
        ordering = ("id",)
        indexes = [models.Index(fields=["produit", "-created_at"])]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(quantite__gte=1), name="ligne_vente_quantite_positive"
            ),
        ]

    def __str__(self):
        return f"{self.quantite} x {self.produit_id} a {self.prix_unitaire}"

    def save(self, *args, **kwargs):
        # Le sous-total n'est jamais saisi : il est derive.
        self.sous_total = Decimal(self.quantite) * self.prix_unitaire
        super().save(*args, **kwargs)
