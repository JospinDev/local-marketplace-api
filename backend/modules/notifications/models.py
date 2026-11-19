"""Module 12 - Notifications.

Le cahier des charges demande quatre choses : des notifications internes, des
notifications push, un historique et un marquage comme lu. Il ajoute une
exigence qui gouverne toute la conception du module :

    "Les notifications push doivent etre une fonctionnalite complementaire :
     l'application doit continuer a fonctionner meme si les services push ne
     sont pas disponibles."

D'ou le choix suivant : la notification INTERNE, en base, est la seule source
de verite. Le temps reel (WebSocket) et le push (Firebase ou autre) ne sont
que deux moyens de transport ; si les deux tombent, l'utilisateur retrouve
tout dans son historique a la prochaine ouverture de l'application.

Une notification ne modifie jamais rien : elle n'a pas de regle metier, et
son echec ne doit jamais faire echouer l'operation qui l'a declenchee.
"""
from django.conf import settings
from django.db import models
from django.utils import timezone

from common.models import TimeStampedModel


class TypeNotification(models.TextChoices):
    """Evenements listes au module 12 du cahier des charges.

    Certains types servent aux deux roles : un nouveau message concerne
    l'acheteur comme le vendeur, et une annulation de reservation est
    notifiee a celui qui ne l'a pas demandee.
    """

    # --- commun ---------------------------------------------------------
    MESSAGE_NOUVEAU = "MESSAGE_NOUVEAU", "Nouveau message"

    # --- destinees a l'acheteur -----------------------------------------
    RESERVATION_ACCEPTEE = "RESERVATION_ACCEPTEE", "Reservation acceptee"
    RESERVATION_REFUSEE = "RESERVATION_REFUSEE", "Demande de reservation refusee"
    RESERVATION_ANNULEE = "RESERVATION_ANNULEE", "Reservation annulee"
    RESERVATION_EXPIREE = "RESERVATION_EXPIREE", "Reservation expiree"
    FAVORI_INDISPONIBLE = "FAVORI_INDISPONIBLE", "Un favori n'est plus disponible"
    VENDEUR_NOUVELLE_ANNONCE = (
        "VENDEUR_NOUVELLE_ANNONCE",
        "Nouvelle annonce d'un vendeur suivi",
    )

    # --- destinees au vendeur -------------------------------------------
    RESERVATION_DEMANDE = "RESERVATION_DEMANDE", "Nouvelle demande de reservation"
    ACHAT_CONFIRME = "ACHAT_CONFIRME", "Achat confirme par le client"
    AVIS_NOUVEAU = "AVIS_NOUVEAU", "Nouvel avis recu"
    STOCK_PRESQUE_EPUISE = "STOCK_PRESQUE_EPUISE", "Produit presque epuise"
    STOCK_EPUISE = "STOCK_EPUISE", "Produit en rupture de stock"

    # --- administration -------------------------------------------------
    COMPTE_SUSPENDU = "COMPTE_SUSPENDU", "Compte suspendu"
    COMPTE_REACTIVE = "COMPTE_REACTIVE", "Compte reactive"
    ANNONCE_MODEREE = "ANNONCE_MODEREE", "Annonce moderee"
    AVIS_MODERE = "AVIS_MODERE", "Avis modere"


class PlateformeAppareil(models.TextChoices):
    ANDROID = "ANDROID", "Android"
    IOS = "IOS", "iOS"
    WEB = "WEB", "Navigateur web"


class NotificationQuerySet(models.QuerySet):
    def de(self, utilisateur):
        return self.filter(destinataire=utilisateur)

    def non_lues(self):
        return self.filter(lu_le__isnull=True)

    def lues(self):
        return self.filter(lu_le__isnull=False)


class Notification(TimeStampedModel):
    """Notification interne : la source de verite de l'historique."""

    destinataire = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="destinataire",
        on_delete=models.CASCADE,
        related_name="notifications",
    )
    type_notification = models.CharField(
        "type",
        max_length=25,
        choices=TypeNotification.choices,
        db_index=True,
    )
    titre = models.CharField("titre", max_length=150)
    message = models.CharField("message", max_length=500, blank=True)

    # Cible de la notification : de quoi construire un lien profond dans
    # l'application mobile sans que le serveur connaisse ses ecrans.
    reference_type = models.CharField(
        "type de reference",
        max_length=20,
        blank=True,
        help_text="produit, reservation, vente, conversation, evaluation...",
    )
    reference_id = models.PositiveBigIntegerField(
        "identifiant de reference", blank=True, null=True
    )
    donnees = models.JSONField(
        "donnees complementaires",
        default=dict,
        blank=True,
        help_text="Charge utile libre, consommee par l'application mobile.",
    )

    lu_le = models.DateTimeField("lue le", blank=True, null=True, db_index=True)

    objects = NotificationQuerySet.as_manager()

    class Meta:
        verbose_name = "notification"
        verbose_name_plural = "notifications"
        ordering = ("-created_at", "-id")
        indexes = [
            models.Index(fields=["destinataire", "-created_at"]),
            models.Index(fields=["destinataire", "lu_le"]),
            models.Index(fields=["reference_type", "reference_id"]),
        ]

    def __str__(self):
        return f"{self.get_type_notification_display()} pour {self.destinataire_id}"

    @property
    def est_lue(self) -> bool:
        return self.lu_le is not None

    @property
    def nom_groupe(self) -> str:
        return Notification.groupe_de(self.destinataire_id)

    @staticmethod
    def groupe_de(utilisateur_id) -> str:
        """Groupe Channels personnel : une notification ne sort jamais du sien."""
        return f"notifications_{utilisateur_id}"

    def marquer_comme_lue(self):
        if self.lu_le is None:
            self.lu_le = timezone.now()
            self.save(update_fields=["lu_le", "updated_at"])
        return self


class AppareilPush(TimeStampedModel):
    """Jeton d'un appareil, pour les notifications push.

    Le module fonctionne entierement sans aucun appareil enregistre : le
    push est un complement, comme l'exige le cahier des charges.
    """

    utilisateur = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="utilisateur",
        on_delete=models.CASCADE,
        related_name="appareils_push",
    )
    jeton = models.CharField(
        "jeton de l'appareil",
        max_length=255,
        unique=True,
        help_text="Jeton fourni par le service push (FCM, APNs...).",
    )
    plateforme = models.CharField(
        "plateforme", max_length=10, choices=PlateformeAppareil.choices
    )
    libelle = models.CharField(
        "libelle", max_length=100, blank=True,
        help_text="Nom lisible de l'appareil, pour que l'utilisateur s'y retrouve.",
    )
    actif = models.BooleanField("actif", default=True, db_index=True)
    derniere_utilisation = models.DateTimeField(
        "derniere utilisation", blank=True, null=True
    )

    class Meta:
        verbose_name = "appareil push"
        verbose_name_plural = "appareils push"
        ordering = ("-created_at",)
        indexes = [models.Index(fields=["utilisateur", "actif"])]

    def __str__(self):
        return f"{self.get_plateforme_display()} de {self.utilisateur_id}"

    def desactiver(self):
        """Un jeton refuse par le service push ne sert plus a rien."""
        if self.actif:
            self.actif = False
            self.save(update_fields=["actif", "updated_at"])
        return self
