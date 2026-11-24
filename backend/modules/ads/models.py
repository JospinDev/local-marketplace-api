"""Publicites de la plateforme : bandeau administre, affiche en haut de
l'accueil mobile.

Deux niveaux d'extinction, volontairement separes :

1. chaque publicite a son propre `actif` et sa fenetre de diffusion ;
2. `ParametrePlateforme["PUBLICITES_ACTIVES"]` coupe le bandeau entier.

Le second existe pour qu'un administrateur puisse faire disparaitre
l'espace d'un coup, sans toucher aux publicites une par une ni les
supprimer. Quand aucune publicite n'est diffusable, la route publique
renvoie une liste vide et le client fait disparaitre l'emplacement : il n'y
a jamais de bandeau vide a l'ecran.
"""
from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone

from common.models import TimeStampedModel


class TypeCiblePublicite(models.TextChoices):
    """Ce qui s'ouvre quand on appuie sur la publicite."""

    AUCUNE = "AUCUNE", "Aucune (simple image)"
    PRODUIT = "PRODUIT", "Une annonce"
    CATEGORIE = "CATEGORIE", "Une categorie"
    VENDEUR = "VENDEUR", "La boutique d'un vendeur"
    URL = "URL", "Une adresse web externe"


class PubliciteQuerySet(models.QuerySet):
    def diffusables(self):
        """Publicites reellement affichables maintenant.

        Une publicite sans date de debut est consideree comme demarree, et
        une publicite sans date de fin ne s'arrete pas : les deux champs
        sont facultatifs pour qu'un bandeau permanent reste simple a
        creer.
        """
        maintenant = timezone.now()
        return (
            self.filter(actif=True)
            .filter(models.Q(debut_le__isnull=True) | models.Q(debut_le__lte=maintenant))
            .filter(models.Q(fin_le__isnull=True) | models.Q(fin_le__gte=maintenant))
        )


class Publicite(TimeStampedModel):
    """Un emplacement publicitaire cree par l'administration."""

    titre = models.CharField("titre", max_length=120)
    sous_titre = models.CharField("sous-titre", max_length=200, blank=True)

    image = models.ImageField("image", upload_to="publicites/%Y/%m/")

    #: Texte du bouton. Vide, aucun bouton n'est dessine.
    libelle_action = models.CharField("libelle du bouton", max_length=40, blank=True)

    type_cible = models.CharField(
        "type de cible",
        max_length=10,
        choices=TypeCiblePublicite.choices,
        default=TypeCiblePublicite.AUCUNE,
    )

    #: Identifiant de l'annonce, de la categorie ou du vendeur vise.
    cible_id = models.PositiveIntegerField("identifiant de la cible", null=True, blank=True)

    #: Adresse externe, pour `type_cible = URL`.
    cible_url = models.URLField("adresse web", max_length=500, blank=True)

    actif = models.BooleanField("active", default=True, db_index=True)

    #: Les plus petits passent en premier. Deux publicites de meme ordre
    #: sont ensuite departagees par date de creation.
    ordre = models.PositiveIntegerField(
        "ordre d'affichage",
        default=0,
        validators=[MinValueValidator(0)],
        db_index=True,
    )

    debut_le = models.DateTimeField("debut de diffusion", null=True, blank=True)
    fin_le = models.DateTimeField("fin de diffusion", null=True, blank=True)

    #: Compteurs indicatifs, incrementes par la route publique et par le
    #: client. Ils ne servent qu'a l'administration, jamais a un calcul
    #: metier.
    nombre_affichages = models.PositiveIntegerField("affichages", default=0)
    nombre_clics = models.PositiveIntegerField("clics", default=0)

    cree_par = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="creee par",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="publicites_creees",
    )

    objects = PubliciteQuerySet.as_manager()

    class Meta:
        verbose_name = "publicite"
        verbose_name_plural = "publicites"
        ordering = ("ordre", "-created_at")
        indexes = [
            models.Index(fields=["actif", "ordre"], name="ads_pub_actif_ordre_idx"),
            models.Index(fields=["debut_le", "fin_le"], name="ads_pub_fenetre_idx"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(fin_le__isnull=True)
                | models.Q(debut_le__isnull=True)
                | models.Q(fin_le__gte=models.F("debut_le")),
                name="publicite_fenetre_coherente",
            ),
        ]

    def __str__(self):
        return self.titre

    @property
    def est_diffusable(self) -> bool:
        if not self.actif:
            return False
        maintenant = timezone.now()
        if self.debut_le and self.debut_le > maintenant:
            return False
        if self.fin_le and self.fin_le < maintenant:
            return False
        return True
