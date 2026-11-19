"""Module 3 - Product Management.

Regles metier fondamentales du cahier des charges :

- Un produit est une ANNONCE ; il est distinct d'une reservation et d'une vente.
- Trois quantites sont suivies dans `Inventaire` :
  `quantite_totale`, `quantite_reservee`, `quantite_vendue`.
- `quantite_disponible = quantite_totale - quantite_reservee - quantite_vendue`.
- Le systeme ne doit jamais permettre de reserver ou vendre plus que la
  quantite disponible (controle fait cote serveur, en transaction).
- Le vendeur ne modifie jamais directement la quantite vendue ni reservee.
- Un produit entierement vendu passe automatiquement en OUT_OF_STOCK.
- Le prix de l'annonce peut changer sans alterer les ventes passees : chaque
  ligne de vente conservera son propre prix unitaire (module 9).
"""
from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.utils.text import slugify

from common.models import TimeStampedModel


class StatutProduit(models.TextChoices):
    DRAFT = "DRAFT", "Brouillon"
    PENDING = "PENDING", "En attente de moderation"
    ACTIVE = "ACTIVE", "Active"
    OUT_OF_STOCK = "OUT_OF_STOCK", "Rupture de stock"
    PAUSED = "PAUSED", "En pause"
    ARCHIVED = "ARCHIVED", "Archivee"
    REMOVED = "REMOVED", "Retiree par l'administration"


class EtatProduit(models.TextChoices):
    NEUF = "NEUF", "Neuf"
    OCCASION = "OCCASION", "Occasion"


class Devise(models.TextChoices):
    BIF = "BIF", "Franc burundais"


class ProduitQuerySet(models.QuerySet):
    """Jeux de resultats reutilises par les modules 3, 4 et suivants."""

    def visibles(self):
        """Annonces exposables au public (API publiques du module 4)."""
        return self.filter(
            status__in=[StatutProduit.ACTIVE, StatutProduit.OUT_OF_STOCK],
            owner__is_active=True,
        )

    def disponibles(self):
        return self.filter(status=StatutProduit.ACTIVE)

    def de(self, utilisateur):
        return self.filter(owner=utilisateur)

    def avec_inventaire(self):
        return self.select_related("inventaire", "categorie", "owner")


class Produit(TimeStampedModel):
    """Annonce commerciale publiee par un utilisateur."""

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="proprietaire",
        on_delete=models.CASCADE,
        related_name="produits",
        help_text="Chaque produit appartient obligatoirement a un utilisateur.",
    )
    categorie = models.ForeignKey(
        "categories.Categorie",
        verbose_name="categorie",
        on_delete=models.PROTECT,
        related_name="produits",
    )

    titre = models.CharField("titre", max_length=200, db_index=True)
    slug = models.SlugField("slug", max_length=240, blank=True, db_index=True)
    description = models.TextField("description", blank=True)

    prix = models.DecimalField(
        "prix unitaire",
        max_digits=14,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0"))],
        db_index=True,
        help_text="Montant en devise entiere, sans erreur d'arrondi.",
    )
    devise = models.CharField(
        "devise", max_length=3, choices=Devise.choices, default=Devise.BIF
    )
    etat = models.CharField(
        "etat du produit", max_length=10, choices=EtatProduit.choices,
        default=EtatProduit.NEUF, db_index=True,
    )
    status = models.CharField(
        "statut de l'annonce",
        max_length=15,
        choices=StatutProduit.choices,
        default=StatutProduit.DRAFT,
        db_index=True,
    )

    # --- localisation : un seul champ texte, saisi librement ---------------
    # Aucune table ni identifiant de localisation. Le vendeur ecrit ou se
    # trouve le produit ("Taba", "Kinindo pres du marche", "Gitega centre") et
    # l'acheteur retrouve l'annonce des que sa saisie est contenue dans ce
    # texte (lookup `icontains`).
    localisation = models.CharField(
        "localisation",
        max_length=255,
        blank=True,
        db_index=True,
        help_text=(
            "Texte libre : quartier, zone, commune ou province. Le vendeur "
            "n'est jamais oblige d'indiquer son adresse exacte, il peut se "
            "limiter a un point de rencontre."
        ),
    )
    latitude = models.DecimalField(
        "latitude", max_digits=9, decimal_places=6, blank=True, null=True
    )
    longitude = models.DecimalField(
        "longitude", max_digits=9, decimal_places=6, blank=True, null=True
    )

    # --- mise en avant et popularite (module 4) ---------------------------
    est_mis_en_avant = models.BooleanField(
        "mis en avant", default=False, db_index=True,
        help_text="Reserve a l'administration.",
    )
    nombre_vues = models.PositiveIntegerField("nombre de vues", default=0, db_index=True)

    # --- moderation (module 14) -------------------------------------------
    publie_le = models.DateTimeField("date de publication", blank=True, null=True)
    motif_moderation = models.CharField("motif de moderation", max_length=255, blank=True)

    objects = ProduitQuerySet.as_manager()

    class Meta:
        verbose_name = "produit"
        verbose_name_plural = "produits"
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["status", "-created_at"]),
            models.Index(fields=["categorie", "status"]),
            models.Index(fields=["localisation"]),
            models.Index(fields=["prix"]),
        ]

    def __str__(self):
        return f"{self.titre} ({self.prix} {self.devise})"

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.titre)[:240]
        super().save(*args, **kwargs)

    # ------------------------------------------------------------- proprietes
    @property
    def quantite_disponible(self) -> int:
        inventaire = getattr(self, "inventaire", None)
        return inventaire.quantite_disponible if inventaire else 0

    @property
    def est_visible_publiquement(self) -> bool:
        return self.status in (StatutProduit.ACTIVE, StatutProduit.OUT_OF_STOCK)


class Inventaire(TimeStampedModel):
    """Etat du stock d'un produit.

    Les quantites reservee et vendue ne sont jamais modifiees par le vendeur
    via l'API : elles sont pilotees par les modules Reservations (8) et
    Ventes (9), en transaction.
    """

    produit = models.OneToOneField(
        Produit, verbose_name="produit", on_delete=models.CASCADE,
        related_name="inventaire",
    )
    quantite_totale = models.PositiveIntegerField(
        "quantite totale", default=0,
        help_text="Quantite physique enregistree par le vendeur.",
    )
    quantite_reservee = models.PositiveIntegerField(
        "quantite reservee", default=0,
        help_text="Pilotee par le module Reservations.",
    )
    quantite_vendue = models.PositiveIntegerField(
        "quantite vendue", default=0,
        help_text="Pilotee par le module Ventes.",
    )

    class Meta:
        verbose_name = "inventaire"
        verbose_name_plural = "inventaires"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(
                    quantite_totale__gte=models.F("quantite_reservee")
                    + models.F("quantite_vendue")
                ),
                name="inventaire_quantites_coherentes",
            ),
        ]

    def __str__(self):
        return f"{self.produit.titre} : {self.quantite_disponible} disponible(s)"

    @property
    def quantite_disponible(self) -> int:
        return max(
            self.quantite_totale - self.quantite_reservee - self.quantite_vendue, 0
        )

    @property
    def valeur_stock(self):
        return self.quantite_disponible * self.produit.prix

    @property
    def valeur_reservations(self):
        return self.quantite_reservee * self.produit.prix


class ProduitImage(TimeStampedModel):
    """Photo d'une annonce. La premiere image ajoutee devient principale."""

    produit = models.ForeignKey(
        Produit, verbose_name="produit", on_delete=models.CASCADE,
        related_name="images",
    )
    image = models.ImageField("image", upload_to="produits/%Y/%m/")
    legende = models.CharField("legende", max_length=150, blank=True)
    est_principale = models.BooleanField("image principale", default=False)
    ordre = models.PositiveSmallIntegerField("ordre d'affichage", default=0)

    class Meta:
        verbose_name = "image de produit"
        verbose_name_plural = "images de produits"
        ordering = ("-est_principale", "ordre", "created_at")

    def __str__(self):
        return f"Image de {self.produit.titre}"

    def save(self, *args, **kwargs):
        nouvelle = self._state.adding
        super().save(*args, **kwargs)
        # Une seule image principale par produit.
        if self.est_principale:
            ProduitImage.objects.filter(produit=self.produit).exclude(
                pk=self.pk
            ).update(est_principale=False)
        elif nouvelle and not ProduitImage.objects.filter(
            produit=self.produit, est_principale=True
        ).exists():
            ProduitImage.objects.filter(pk=self.pk).update(est_principale=True)


# ---------------------------------------------------------------------------
# Historique des mouvements de stock (InventoryMovement du cahier des charges)
# ---------------------------------------------------------------------------
class TypeMouvementStock(models.TextChoices):
    """Raison pour laquelle une quantite a change."""

    ENTREE = "ENTREE", "Entree de stock"
    RESERVATION = "RESERVATION", "Quantite reservee"
    LIBERATION = "LIBERATION", "Quantite liberee"
    VENTE = "VENTE", "Quantite vendue"
    ANNULATION_VENTE = "ANNULATION_VENTE", "Vente annulee"
    AJUSTEMENT = "AJUSTEMENT", "Ajustement manuel"


class MouvementStock(TimeStampedModel):
    """Trace d'audit : pourquoi une quantite a augmente ou diminue.

    Le cahier des charges exige cet historique ("indispensable pour
    comprendre pourquoi une quantite a augmente ou diminue"). Chaque ligne
    enregistre AUSSI l'etat du stock juste apres l'operation : on peut donc
    rejouer l'histoire d'un produit sans recalculer quoi que ce soit.

    Les lignes ne sont jamais modifiees ni supprimees par l'API.
    """

    produit = models.ForeignKey(
        Produit, verbose_name="produit", on_delete=models.CASCADE,
        related_name="mouvements_stock",
    )
    type_mouvement = models.CharField(
        "type de mouvement", max_length=20,
        choices=TypeMouvementStock.choices, db_index=True,
    )
    quantite = models.PositiveIntegerField(
        "quantite concernee",
        help_text="Toujours positive : c'est le type de mouvement qui donne le sens.",
    )

    # Origine du mouvement : "reservation", "vente", "vendeur"...
    reference_type = models.CharField("type de reference", max_length=30, blank=True)
    reference_id = models.PositiveBigIntegerField(
        "identifiant de reference", blank=True, null=True
    )
    effectue_par = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="effectue par",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="mouvements_stock",
    )
    commentaire = models.CharField("commentaire", max_length=255, blank=True)

    # Photographie du stock apres le mouvement.
    quantite_totale_apres = models.PositiveIntegerField("quantite totale apres", default=0)
    quantite_reservee_apres = models.PositiveIntegerField("quantite reservee apres", default=0)
    quantite_vendue_apres = models.PositiveIntegerField("quantite vendue apres", default=0)

    class Meta:
        verbose_name = "mouvement de stock"
        verbose_name_plural = "mouvements de stock"
        ordering = ("-created_at", "-id")
        indexes = [
            models.Index(fields=["produit", "-created_at"]),
            models.Index(fields=["reference_type", "reference_id"]),
        ]

    def __str__(self):
        return f"{self.get_type_mouvement_display()} de {self.quantite} ({self.produit_id})"

    @property
    def quantite_disponible_apres(self) -> int:
        return max(
            self.quantite_totale_apres
            - self.quantite_reservee_apres
            - self.quantite_vendue_apres,
            0,
        )
