"""Module 2 - Categories Management.

Les categories sont dynamiques (jamais codees dans Flutter) et organisees en
arborescence sur deux niveaux ou plus : une categorie racine (`parent=null`)
contient des sous-categories.
"""
from django.core.exceptions import ValidationError
from django.db import models
from django.utils.text import slugify

from common.models import TimeStampedModel


class CategorieQuerySet(models.QuerySet):
    def actives(self):
        return self.filter(is_active=True)

    def racines(self):
        return self.filter(parent__isnull=True)


class Categorie(TimeStampedModel):
    """Categorie ou sous-categorie de produits."""

    nom = models.CharField("nom", max_length=120, db_index=True)
    slug = models.SlugField("slug", max_length=140, unique=True, blank=True)
    description = models.TextField("description", blank=True)

    parent = models.ForeignKey(
        "self",
        verbose_name="categorie parente",
        on_delete=models.CASCADE,
        related_name="sous_categories",
        blank=True,
        null=True,
        help_text="Vide pour une categorie racine.",
    )

    image = models.ImageField("image", upload_to="categories/", blank=True, null=True)
    icone = models.CharField(
        "icone",
        max_length=80,
        blank=True,
        help_text="Nom de l'icone utilisee par l'application mobile.",
    )
    ordre = models.PositiveIntegerField(
        "ordre d'affichage", default=0, db_index=True
    )
    is_active = models.BooleanField("active", default=True, db_index=True)

    objects = CategorieQuerySet.as_manager()

    class Meta:
        verbose_name = "categorie"
        verbose_name_plural = "categories"
        ordering = ("ordre", "nom")
        constraints = [
            models.UniqueConstraint(
                fields=["parent", "nom"],
                name="categorie_nom_unique_par_parent",
            ),
        ]
        indexes = [
            models.Index(fields=["parent", "is_active"]),
        ]

    def __str__(self):
        if self.parent_id:
            return f"{self.parent.nom} > {self.nom}"
        return self.nom

    # ------------------------------------------------------------- validations
    def clean(self):
        super().clean()
        if self.parent_id and self.parent_id == self.pk:
            raise ValidationError(
                {"parent": "Une categorie ne peut pas etre sa propre parente."}
            )
        # Interdit les cycles (A -> B -> A).
        ancetre = self.parent
        while ancetre is not None:
            if ancetre.pk == self.pk:
                raise ValidationError(
                    {"parent": "Hierarchie circulaire detectee."}
                )
            ancetre = ancetre.parent

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.nom)[:120] or "categorie"
            slug = base
            compteur = 2
            while Categorie.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug = f"{base}-{compteur}"
                compteur += 1
            self.slug = slug
        super().save(*args, **kwargs)

    # ------------------------------------------------------------- proprietes
    @property
    def est_racine(self) -> bool:
        return self.parent_id is None

    @property
    def niveau(self) -> int:
        niveau = 0
        parent = self.parent
        while parent is not None:
            niveau += 1
            parent = parent.parent
        return niveau

    @property
    def chemin_complet(self) -> str:
        elements = [self.nom]
        parent = self.parent
        while parent is not None:
            elements.insert(0, parent.nom)
            parent = parent.parent
        return " > ".join(elements)
