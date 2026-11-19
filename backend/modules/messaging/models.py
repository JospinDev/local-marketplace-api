"""Module 7 - Messaging & Chat.

Regles du cahier des charges :

- Une conversation nait generalement depuis une annonce : elle conserve alors
  le produit concerne ET le prix affiche au debut de la discussion, pour que
  la negociation reste lisible meme si le vendeur change son prix ensuite.
- Un utilisateur ne peut pas s'envoyer de message a lui-meme.
- Un utilisateur ne peut pas acceder aux conversations d'autres personnes.
- Une conversation ne doit pas etre dupliquee pour le meme couple
  acheteur / vendeur / produit.
- Les messages sont conserves en base (PostgreSQL), Redis ne sert qu'au
  transport temps reel.
"""
from django.conf import settings
from django.db import models
from django.utils import timezone

from common.models import TimeStampedModel


class ConversationQuerySet(models.QuerySet):
    def de(self, utilisateur):
        """Conversations dont l'utilisateur est l'un des deux participants."""
        return self.filter(
            models.Q(acheteur=utilisateur) | models.Q(vendeur=utilisateur)
        )


class Conversation(TimeStampedModel):
    """Discussion entre un acheteur et un vendeur, au sujet d'une annonce."""

    acheteur = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="acheteur",
        on_delete=models.CASCADE,
        related_name="conversations_achat",
        help_text="Utilisateur qui a ouvert la discussion.",
    )
    vendeur = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="vendeur",
        on_delete=models.CASCADE,
        related_name="conversations_vente",
    )
    produit = models.ForeignKey(
        "products.Produit",
        verbose_name="produit concerne",
        on_delete=models.SET_NULL,
        related_name="conversations",
        blank=True,
        null=True,
        help_text="Annonce depuis laquelle la discussion a demarre.",
    )
    prix_initial = models.DecimalField(
        "prix affiche au debut de la conversation",
        max_digits=14,
        decimal_places=2,
        blank=True,
        null=True,
        help_text=(
            "Figé a la creation : une modification ulterieure du prix de "
            "l'annonce ne doit pas reecrire l'historique de la negociation."
        ),
    )

    dernier_message_le = models.DateTimeField(
        "dernier message le", blank=True, null=True, db_index=True
    )

    # --- blocage ----------------------------------------------------------
    bloquee_par = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="bloquee par",
        on_delete=models.SET_NULL,
        related_name="conversations_bloquees",
        blank=True,
        null=True,
        help_text="Participant ayant bloque la discussion.",
    )
    bloquee_le = models.DateTimeField("bloquee le", blank=True, null=True)

    objects = ConversationQuerySet.as_manager()

    class Meta:
        verbose_name = "conversation"
        verbose_name_plural = "conversations"
        ordering = ("-dernier_message_le", "-created_at")
        constraints = [
            # Pas de doublon pour un meme trio acheteur / vendeur / produit.
            models.UniqueConstraint(
                fields=["acheteur", "vendeur", "produit"],
                name="conversation_unique_par_produit",
                condition=models.Q(produit__isnull=False),
            ),
            # Les NULL etant distincts en SQL, une contrainte partielle est
            # necessaire pour les discussions sans produit.
            models.UniqueConstraint(
                fields=["acheteur", "vendeur"],
                name="conversation_unique_sans_produit",
                condition=models.Q(produit__isnull=True),
            ),
            models.CheckConstraint(
                condition=~models.Q(acheteur=models.F("vendeur")),
                name="conversation_pas_avec_soi_meme",
            ),
        ]
        indexes = [
            models.Index(fields=["acheteur", "-dernier_message_le"]),
            models.Index(fields=["vendeur", "-dernier_message_le"]),
        ]

    def __str__(self):
        return f"{self.acheteur.username} <-> {self.vendeur.username}"

    # ------------------------------------------------------------ proprietes
    @property
    def est_bloquee(self) -> bool:
        return self.bloquee_par_id is not None

    @property
    def nom_groupe(self) -> str:
        """Nom du groupe Channels associe a cette conversation."""
        return f"conversation_{self.pk}"

    def participants_ids(self):
        return {self.acheteur_id, self.vendeur_id}

    def est_participant(self, utilisateur) -> bool:
        return utilisateur.is_authenticated and (
            utilisateur.pk in self.participants_ids()
        )

    def interlocuteur_de(self, utilisateur):
        return self.vendeur if utilisateur.pk == self.acheteur_id else self.acheteur

    def bloquer(self, utilisateur):
        self.bloquee_par = utilisateur
        self.bloquee_le = timezone.now()
        self.save(update_fields=["bloquee_par", "bloquee_le", "updated_at"])

    def debloquer(self):
        self.bloquee_par = None
        self.bloquee_le = None
        self.save(update_fields=["bloquee_par", "bloquee_le", "updated_at"])


class MessageQuerySet(models.QuerySet):
    def non_lus_pour(self, utilisateur):
        """Messages recus et pas encore lus par cet utilisateur."""
        return self.filter(lu_le__isnull=True).exclude(expediteur=utilisateur)


class Message(TimeStampedModel):
    """Message texte et/ou photo, conserve en base de donnees."""

    conversation = models.ForeignKey(
        Conversation,
        verbose_name="conversation",
        on_delete=models.CASCADE,
        related_name="messages",
    )
    expediteur = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="expediteur",
        on_delete=models.CASCADE,
        related_name="messages_envoyes",
    )
    contenu = models.TextField("contenu", blank=True)
    image = models.ImageField(
        "image", upload_to="messages/%Y/%m/", blank=True, null=True
    )
    lu_le = models.DateTimeField("lu le", blank=True, null=True)

    objects = MessageQuerySet.as_manager()

    class Meta:
        verbose_name = "message"
        verbose_name_plural = "messages"
        ordering = ("created_at",)
        constraints = [
            # Un message vide n'a pas de sens : texte ou image obligatoire.
            models.CheckConstraint(
                condition=~models.Q(contenu="") | models.Q(image__isnull=False),
                name="message_texte_ou_image",
            ),
        ]
        indexes = [
            models.Index(fields=["conversation", "created_at"]),
            models.Index(fields=["conversation", "lu_le"]),
        ]

    def __str__(self):
        apercu = (self.contenu or "[image]")[:40]
        return f"{self.expediteur.username} : {apercu}"

    @property
    def est_lu(self) -> bool:
        return self.lu_le is not None


class MotifSignalement(models.TextChoices):
    ARNAQUE = "ARNAQUE", "Tentative d'arnaque"
    HARCELEMENT = "HARCELEMENT", "Harcelement ou insultes"
    SPAM = "SPAM", "Spam ou publicite"
    PRODUIT_INTERDIT = "PRODUIT_INTERDIT", "Produit interdit"
    AUTRE = "AUTRE", "Autre"


class SignalementConversation(TimeStampedModel):
    """Signalement d'une conversation, traite par la moderation (module 14)."""

    conversation = models.ForeignKey(
        Conversation,
        verbose_name="conversation",
        on_delete=models.CASCADE,
        related_name="signalements",
    )
    signale_par = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="signale par",
        on_delete=models.CASCADE,
        related_name="signalements_conversations",
    )
    motif = models.CharField("motif", max_length=20, choices=MotifSignalement.choices)
    description = models.TextField("description", blank=True)
    traite_le = models.DateTimeField("traite le", blank=True, null=True)

    class Meta:
        verbose_name = "signalement de conversation"
        verbose_name_plural = "signalements de conversations"
        ordering = ("-created_at",)
        constraints = [
            # Un utilisateur ne signale qu'une fois la meme conversation tant
            # que son signalement n'a pas ete traite.
            models.UniqueConstraint(
                fields=["conversation", "signale_par"],
                name="signalement_unique_non_traite",
                condition=models.Q(traite_le__isnull=True),
            ),
        ]

    def __str__(self):
        return f"{self.signale_par.username} signale {self.conversation_id}"
