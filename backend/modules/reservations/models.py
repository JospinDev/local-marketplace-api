"""Module 8 - Reservation Management.

Regles metier fondamentales du cahier des charges :

- Une reservation est une quantite MISE DE COTE pour un acheteur ; elle ne
  constitue jamais un revenu.
- Une reservation porte sur un seul produit, a un acheteur et un vendeur
  distincts, et une quantite strictement positive.
- Le stock n'est immobilise qu'a l'ACCEPTATION du vendeur. Une simple
  demande (PENDING) n'empeche personne d'acheter : c'est exactement
  l'exemple du cahier des charges ("un acheteur demande 3 telephones, le
  vendeur confirme la reservation, reserve = 3").
- Une reservation annulee ou expiree libere sa quantite et ne touche JAMAIS
  `quantite_vendue`.
- Les transitions de stock sont transactionnelles et verrouillees
  (`select_for_update`) : deux acceptations simultanees ne peuvent pas
  depasser le stock disponible.
"""
from django.conf import settings
from django.db import models
from django.utils import timezone

from common.models import TimeStampedModel


class StatutReservation(models.TextChoices):
    """Cycle de vie decrit au paragraphe 3.3 du cahier des charges."""

    PENDING = "PENDING", "Demande en attente"
    CONFIRMED = "CONFIRMED", "Acceptee par le vendeur"
    CANCELLED = "CANCELLED", "Annulee"
    EXPIRED = "EXPIRED", "Expiree"
    FULFILLED = "FULFILLED", "Transformee en vente"


class RoleCloture(models.TextChoices):
    ACHETEUR = "ACHETEUR", "Acheteur"
    VENDEUR = "VENDEUR", "Vendeur"
    SYSTEME = "SYSTEME", "Systeme (expiration)"


class ReservationQuerySet(models.QuerySet):
    """Jeux de resultats reutilises par les modules 8, 9 et 10."""

    #: Statuts qui immobilisent ou peuvent encore immobiliser du stock.
    STATUTS_ACTIFS = (StatutReservation.PENDING, StatutReservation.CONFIRMED)

    def actives(self):
        return self.filter(statut__in=self.STATUTS_ACTIFS)

    def de(self, utilisateur):
        """Reservations ou l'utilisateur est partie prenante."""
        return self.filter(
            models.Q(acheteur=utilisateur) | models.Q(vendeur=utilisateur)
        )

    def demandees_par(self, utilisateur):
        return self.filter(acheteur=utilisateur)

    def recues_par(self, utilisateur):
        return self.filter(vendeur=utilisateur)

    def expirables(self, maintenant=None):
        """Reservations actives dont la date limite est depassee."""
        return self.actives().filter(expire_le__lt=maintenant or timezone.now())

    def complet(self):
        return self.select_related(
            "produit", "produit__inventaire", "produit__categorie",
            "acheteur", "vendeur",
        )


class Reservation(TimeStampedModel):
    """Quantite d'un produit mise de cote pour un acheteur."""

    produit = models.ForeignKey(
        "products.Produit",
        verbose_name="produit",
        # PROTECT : on ne supprime pas une annonce qui porte un historique
        # de reservations. Le vendeur archive son annonce (suppression douce).
        on_delete=models.PROTECT,
        related_name="reservations",
    )
    acheteur = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="acheteur",
        on_delete=models.CASCADE,
        related_name="reservations_demandees",
    )
    vendeur = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="vendeur",
        on_delete=models.CASCADE,
        related_name="reservations_recues",
        help_text="Toujours le proprietaire de l'annonce, jamais saisi par le client.",
    )

    quantite_demandee = models.PositiveIntegerField(
        "quantite demandee",
        help_text="Quantite souhaitee par l'acheteur. Strictement positive.",
    )
    quantite_confirmee = models.PositiveIntegerField(
        "quantite confirmee",
        default=0,
        help_text=(
            "Quantite reellement mise de cote par le vendeur. Elle seule "
            "immobilise du stock. Peut etre inferieure a la demande."
        ),
    )
    quantite_livree = models.PositiveIntegerField(
        "quantite livree",
        default=0,
        help_text=(
            "Quantite finalement achetee et payee (module 9). Le solde non "
            "achete est libere et redevient disponible."
        ),
    )

    statut = models.CharField(
        "statut",
        max_length=10,
        choices=StatutReservation.choices,
        default=StatutReservation.PENDING,
        db_index=True,
    )
    message = models.CharField(
        "message de l'acheteur", max_length=500, blank=True,
        help_text="Precision facultative : heure de passage, point de retrait.",
    )

    expire_le = models.DateTimeField(
        "expire le",
        db_index=True,
        help_text=(
            "Duree configurable (RESERVATION_DUREE_HEURES). Passee cette "
            "date, la reservation expire et le stock est libere."
        ),
    )
    confirmee_le = models.DateTimeField("acceptee le", blank=True, null=True)
    cloturee_le = models.DateTimeField(
        "cloturee le", blank=True, null=True,
        help_text="Date d'annulation, d'expiration ou de transformation en vente.",
    )

    cloturee_par = models.CharField(
        "cloturee par", max_length=10, choices=RoleCloture.choices, blank=True
    )
    motif = models.CharField("motif de la cloture", max_length=255, blank=True)

    objects = ReservationQuerySet.as_manager()

    class Meta:
        verbose_name = "reservation"
        verbose_name_plural = "reservations"
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["acheteur", "statut"]),
            models.Index(fields=["vendeur", "statut"]),
            models.Index(fields=["produit", "statut"]),
            models.Index(fields=["statut", "expire_le"]),
        ]
        constraints = [
            # La quantite demandee doit etre superieure a zero.
            models.CheckConstraint(
                condition=models.Q(quantite_demandee__gte=1),
                name="reservation_quantite_positive",
            ),
            # On ne confirme ni ne livre jamais plus que ce qui est demande.
            models.CheckConstraint(
                condition=models.Q(
                    quantite_confirmee__lte=models.F("quantite_demandee")
                ),
                name="reservation_confirmee_inferieure_demandee",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    quantite_livree__lte=models.F("quantite_confirmee")
                ),
                name="reservation_livree_inferieure_confirmee",
            ),
            # Un utilisateur ne reserve pas chez lui-meme.
            models.CheckConstraint(
                condition=~models.Q(acheteur=models.F("vendeur")),
                name="reservation_pas_chez_soi",
            ),
            # Une seule reservation active par couple (acheteur, produit) :
            # pour changer d'avis, l'acheteur modifie sa quantite au lieu
            # d'empiler des demandes. Contrainte partielle, car les
            # reservations cloturees doivent, elles, pouvoir etre nombreuses.
            models.UniqueConstraint(
                fields=["produit", "acheteur"],
                condition=models.Q(statut__in=["PENDING", "CONFIRMED"]),
                name="reservation_active_unique_par_acheteur",
            ),
        ]

    def __str__(self):
        return (
            f"Reservation {self.pk} : {self.quantite_demandee} x "
            f"{self.produit_id} pour {self.acheteur_id} ({self.statut})"
        )

    # ------------------------------------------------------------ proprietes
    @property
    def est_active(self) -> bool:
        return self.statut in ReservationQuerySet.STATUTS_ACTIFS

    @property
    def est_expiree(self) -> bool:
        """Date limite depassee alors que la reservation est encore active."""
        return bool(
            self.est_active
            and self.expire_le is not None
            and self.expire_le < timezone.now()
        )

    @property
    def quantite_immobilisee(self) -> int:
        """Quantite reellement retiree du stock disponible a cet instant."""
        if self.statut == StatutReservation.CONFIRMED:
            return self.quantite_confirmee
        return 0

    @property
    def quantite_non_achetee(self) -> int:
        """Solde libere lors d'une vente partielle."""
        if self.statut != StatutReservation.FULFILLED:
            return 0
        return self.quantite_confirmee - self.quantite_livree

    @property
    def valeur_estimee(self):
        """Valeur indicative, au prix actuel de l'annonce.

        Ce n'est jamais un revenu : le chiffre d'affaires se calcule
        uniquement sur les ventes confirmees (module 9).
        """
        quantite = self.quantite_confirmee or self.quantite_demandee
        return quantite * self.produit.prix

    def est_participant(self, utilisateur) -> bool:
        return utilisateur.pk in (self.acheteur_id, self.vendeur_id)

    def role_de(self, utilisateur) -> str:
        if utilisateur.pk == self.acheteur_id:
            return RoleCloture.ACHETEUR
        if utilisateur.pk == self.vendeur_id:
            return RoleCloture.VENDEUR
        return ""
