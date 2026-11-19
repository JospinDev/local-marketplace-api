"""Module 5 - Seller Profile & Following.

Le cahier des charges distingue deux fonctionnalites a ne jamais confondre :

1. Favorite Product (module 6) : sauvegarder un PRODUIT.
2. Follow Seller (ce module)   : suivre un VENDEUR.

Suivre un vendeur alimente la section "Mes vendeurs preferes". Cela ne
supprime aucun produit du catalogue general et ne modifie pas le classement
des resultats de recherche.
"""
from django.conf import settings
from django.db import models

from common.models import TimeStampedModel


class AbonnementVendeurQuerySet(models.QuerySet):
    def de(self, utilisateur):
        """Abonnements souscrits par cet utilisateur."""
        return self.filter(abonne=utilisateur)

    def vers(self, vendeur):
        """Abonnes de ce vendeur."""
        return self.filter(vendeur=vendeur)


class AbonnementVendeur(TimeStampedModel):
    """Un utilisateur (`abonne`) suit un vendeur (`vendeur`)."""

    abonne = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="abonne",
        on_delete=models.CASCADE,
        related_name="abonnements",
        help_text="Utilisateur qui suit le vendeur.",
    )
    vendeur = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="vendeur suivi",
        on_delete=models.CASCADE,
        related_name="abonnes",
    )

    objects = AbonnementVendeurQuerySet.as_manager()

    class Meta:
        verbose_name = "abonnement a un vendeur"
        verbose_name_plural = "abonnements aux vendeurs"
        ordering = ("-created_at",)
        constraints = [
            # Un utilisateur ne peut pas suivre deux fois le meme vendeur.
            models.UniqueConstraint(
                fields=["abonne", "vendeur"], name="abonnement_unique"
            ),
            # Un utilisateur ne peut pas se suivre lui-meme.
            models.CheckConstraint(
                condition=~models.Q(abonne=models.F("vendeur")),
                name="abonnement_pas_soi_meme",
            ),
        ]
        indexes = [
            models.Index(fields=["vendeur", "-created_at"]),
        ]

    def __str__(self):
        return f"{self.abonne.username} suit {self.vendeur.username}"
