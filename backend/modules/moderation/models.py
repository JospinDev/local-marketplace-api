"""Module 14 - Admin & Moderation.

Deux modeles seulement, parce que l'essentiel de l'administration existe
deja : les comptes (`/admin/users/`), les categories
(`/admin/categories/`), les annonces (`/admin/products/`) et les avis
(`/admin/reviews/`) sont livres avec leurs modules respectifs, chacun avec
ses permissions de groupe. Ce module ajoute ce qui n'appartenait a aucun
autre :

- `JournalAudit` : le journal d'audit demande par le cahier des charges.
  "Toute correction doit creer une trace d'audit" (paragraphe 8.2) et "les
  administrateurs doivent pouvoir consulter l'historique des modifications
  de stock et des ventes en cas de litige" (module 14).
- `ParametrePlateforme` : la "configuration de la plateforme", pour que les
  reglages metier soient modifiables sans redeployer.

Les deux sont en LECTURE SEULE cote API pour le journal, et bornes aux
permissions de groupe pour la configuration.
"""
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.db import models

from common.models import TimeStampedModel


class ActionAudit(models.TextChoices):
    """Actes d'administration qui laissent une trace."""

    SUSPENSION_COMPTE = "SUSPENSION_COMPTE", "Suspension d'un compte"
    REACTIVATION_COMPTE = "REACTIVATION_COMPTE", "Reactivation d'un compte"
    MODERATION_ANNONCE = "MODERATION_ANNONCE", "Moderation d'une annonce"
    SUPPRESSION_ANNONCE = "SUPPRESSION_ANNONCE", "Suppression d'une annonce"
    MODERATION_AVIS = "MODERATION_AVIS", "Moderation d'un avis"
    TRAITEMENT_SIGNALEMENT = "TRAITEMENT_SIGNALEMENT", "Traitement d'un signalement"
    MODIFICATION_PARAMETRE = "MODIFICATION_PARAMETRE", "Modification d'un parametre"
    MODIFICATION_CATEGORIE = "MODIFICATION_CATEGORIE", "Modification d'une categorie"
    AUTRE = "AUTRE", "Autre"


class JournalAuditQuerySet(models.QuerySet):
    def de(self, acteur):
        return self.filter(acteur=acteur)

    def sur(self, cible_type: str, cible_id):
        return self.filter(cible_type=cible_type, cible_id=cible_id)

    def complet(self):
        return self.select_related("acteur")


class JournalAudit(TimeStampedModel):
    """Qui a fait quoi, sur quoi, quand, et pourquoi.

    Jamais modifie ni supprime : ni par l'API, ni par l'admin Django. Un
    journal que l'on peut retoucher ne vaut rien en cas de litige.
    """

    acteur = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="acteur",
        # SET_NULL : la suppression d'un compte d'administration ne doit pas
        # effacer les decisions qu'il a prises.
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="actions_audit",
    )
    acteur_username = models.CharField(
        "nom de l'acteur",
        max_length=150,
        blank=True,
        help_text="Recopie : la trace reste lisible meme si le compte disparait.",
    )
    action = models.CharField(
        "action", max_length=25, choices=ActionAudit.choices, db_index=True
    )

    cible_type = models.CharField(
        "type de cible",
        # 30 et non 20 : "signalement_conversation" fait deja 24 caracteres.
        # PostgreSQL refuse le depassement (SQLite le tronque en silence).
        max_length=30,
        blank=True,
        help_text="utilisateur, produit, evaluation, parametre, signalement...",
    )
    cible_id = models.PositiveBigIntegerField(
        "identifiant de la cible", blank=True, null=True
    )
    cible_libelle = models.CharField(
        "libelle de la cible",
        max_length=255,
        blank=True,
        help_text="Nom lisible au moment de l'action.",
    )

    motif = models.CharField("motif", max_length=500, blank=True)
    donnees = models.JSONField(
        "avant / apres",
        default=dict,
        blank=True,
        help_text="Etat avant et apres, pour comprendre la decision.",
    )
    adresse_ip = models.GenericIPAddressField(
        "adresse IP", blank=True, null=True
    )

    objects = JournalAuditQuerySet.as_manager()

    class Meta:
        verbose_name = "entree du journal d'audit"
        verbose_name_plural = "journal d'audit"
        ordering = ("-created_at", "-id")
        indexes = [
            models.Index(fields=["action", "-created_at"]),
            models.Index(fields=["cible_type", "cible_id"]),
            models.Index(fields=["acteur", "-created_at"]),
        ]

    def __str__(self):
        return (
            f"{self.created_at:%Y-%m-%d %H:%M} {self.acteur_username} "
            f"{self.action} {self.cible_type}#{self.cible_id}"
        )


class TypeValeurParametre(models.TextChoices):
    TEXTE = "TEXTE", "Texte"
    ENTIER = "ENTIER", "Nombre entier"
    DECIMAL = "DECIMAL", "Nombre decimal"
    BOOLEEN = "BOOLEEN", "Oui / non"


class ParametrePlateforme(TimeStampedModel):
    """Reglage metier modifiable sans redeploiement.

    Les valeurs du `.env` restent la valeur par defaut : un parametre absent
    de cette table ne casse rien, le code retombe sur `settings`. C'est
    volontaire, pour que la plateforme demarre sur une base vide.
    """

    #: Parametres connus du code, avec leur reglage `settings` de repli.
    CLES_CONNUES = {
        "RESERVATION_DUREE_HEURES": (
            TypeValeurParametre.ENTIER,
            "Duree de validite d'une reservation, en heures.",
        ),
        "EVALUATION_DELAI_MODIFICATION_HEURES": (
            TypeValeurParametre.ENTIER,
            "Delai pendant lequel un avis reste modifiable, en heures.",
        ),
        "STOCK_SEUIL_ALERTE": (
            TypeValeurParametre.ENTIER,
            "Seuil de l'alerte \"produit presque epuise\", en unites.",
        ),
    }

    cle = models.CharField("cle", max_length=60, unique=True, db_index=True)
    valeur = models.CharField("valeur", max_length=255)
    type_valeur = models.CharField(
        "type", max_length=10, choices=TypeValeurParametre.choices,
        default=TypeValeurParametre.TEXTE,
    )
    description = models.CharField("description", max_length=255, blank=True)
    modifie_par = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="modifie par",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="parametres_modifies",
    )

    class Meta:
        verbose_name = "parametre de la plateforme"
        verbose_name_plural = "parametres de la plateforme"
        ordering = ("cle",)
        permissions = [
            (
                "consulter_statistiques",
                "Peut consulter les statistiques globales de la plateforme",
            ),
        ]

    def __str__(self):
        return f"{self.cle} = {self.valeur}"

    # ------------------------------------------------------------- conversion
    @property
    def valeur_typee(self):
        """Valeur convertie selon `type_valeur`, sans jamais lever."""
        return ParametrePlateforme._convertir(self.valeur, self.type_valeur)

    @staticmethod
    def _convertir(brut: str, type_valeur: str):
        try:
            if type_valeur == TypeValeurParametre.ENTIER:
                return int(brut)
            if type_valeur == TypeValeurParametre.DECIMAL:
                return Decimal(brut)
            if type_valeur == TypeValeurParametre.BOOLEEN:
                return str(brut).strip().lower() in ("1", "true", "oui", "yes")
        except (TypeError, ValueError, InvalidOperation):
            # Une valeur mal saisie ne doit pas casser une operation metier :
            # on retombe sur le texte, l'appelant utilisera son defaut.
            return None
        return brut

    @staticmethod
    def valeur_de(cle: str, defaut=None):
        """Lit un parametre, avec repli sur `settings` puis sur `defaut`.

        Ordre de priorite : base de donnees, puis `.env`/`settings`, puis la
        valeur passee en argument. Une table vide se comporte donc exactement
        comme avant l'existence du module 14.
        """
        try:
            parametre = ParametrePlateforme.objects.filter(cle=cle).first()
        except Exception:
            # Table absente (migration non appliquee) : on ne bloque rien.
            parametre = None

        if parametre is not None:
            valeur = parametre.valeur_typee
            if valeur is not None:
                return valeur

        return getattr(settings, cle, defaut)
