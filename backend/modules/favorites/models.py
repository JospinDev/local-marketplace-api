"""Module 6 - Favorites Management.

Regles du cahier des charges :

- Un utilisateur ne peut pas ajouter deux fois le meme produit aux favoris.
- Les favoris sont prives : personne d'autre ne peut les consulter.
- Un produit supprime ne doit plus etre propose comme disponible.
- Les changements de prix doivent etre visibles : le prix au moment de
  l'ajout est donc conserve dans la ligne de favori.
"""
from django.conf import settings
from django.db import models

from common.models import TimeStampedModel


class FavoriQuerySet(models.QuerySet):
    def de(self, utilisateur):
        return self.filter(utilisateur=utilisateur)


class Favori(TimeStampedModel):
    """Produit sauvegarde par un utilisateur."""

    utilisateur = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="utilisateur",
        on_delete=models.CASCADE,
        related_name="favoris",
    )
    produit = models.ForeignKey(
        "products.Produit",
        verbose_name="produit",
        on_delete=models.CASCADE,
        related_name="favoris",
    )
    prix_a_l_ajout = models.DecimalField(
        "prix au moment de l'ajout",
        max_digits=14,
        decimal_places=2,
        help_text=(
            "Conserve pour signaler a l'utilisateur une hausse ou une baisse "
            "de prix depuis sa mise en favori."
        ),
    )

    objects = FavoriQuerySet.as_manager()

    class Meta:
        verbose_name = "favori"
        verbose_name_plural = "favoris"
        ordering = ("-created_at",)
        constraints = [
            models.UniqueConstraint(
                fields=["utilisateur", "produit"], name="favori_unique"
            ),
        ]
        indexes = [
            models.Index(fields=["utilisateur", "-created_at"]),
        ]

    def __str__(self):
        return f"{self.utilisateur.username} aime {self.produit.titre}"

    # ------------------------------------------------------------ proprietes
    @property
    def variation_prix(self):
        """Difference entre le prix actuel et celui du jour de l'ajout."""
        return self.produit.prix - self.prix_a_l_ajout

    @property
    def prix_a_change(self) -> bool:
        return self.produit.prix != self.prix_a_l_ajout

    @property
    def est_toujours_disponible(self) -> bool:
        """Le produit est visible, en ligne et il reste du stock."""
        from modules.products.models import StatutProduit

        produit = self.produit
        return (
            produit.status == StatutProduit.ACTIVE
            and produit.owner.is_active
            and produit.quantite_disponible > 0
        )

    @property
    def est_retire(self) -> bool:
        """L'annonce a ete archivee, retiree, ou le vendeur desactive."""
        from modules.products.models import StatutProduit

        return (
            self.produit.status
            in (StatutProduit.ARCHIVED, StatutProduit.REMOVED)
            or not self.produit.owner.is_active
        )
