"""Module 1 - Authentication & User Management.

Regles d'identite retenues :
- `username` est OBLIGATOIRE et UNIQUE : c'est l'identifiant de connexion.
- `password` est obligatoire.
- `email` est FACULTATIF. S'il est fourni, il doit etre reellement possede par
  l'utilisateur : un code de verification lui est envoye et le compte reste
  non verifie (`email_verifie=False`) tant que le code n'est pas saisi.
- Aucune verification de numero de telephone (le telephone reste un simple
  champ de contact facultatif).
- Un seul compte sert a la fois d'acheteur et de vendeur.
"""
from django.contrib.auth.models import AbstractUser, UserManager as DjangoUserManager
from django.db import models
from django.utils import timezone

from common.models import TimeStampedModel


class StatutCompte(models.TextChoices):
    ACTIF = "ACTIF", "Actif"
    EN_ATTENTE = "EN_ATTENTE", "En attente de verification email"
    SUSPENDU = "SUSPENDU", "Suspendu"
    DESACTIVE = "DESACTIVE", "Desactive"


class UserManager(DjangoUserManager):
    """Manager : email facultatif, username obligatoire."""

    def create_user(self, username, email=None, password=None, **extra_fields):
        if not username:
            raise ValueError("Le nom d'utilisateur est obligatoire.")
        email = self.normalize_email(email) if email else None
        user = self.model(username=username, email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, username, email=None, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("statut_compte", StatutCompte.ACTIF)
        extra_fields.setdefault("email_verifie", bool(email))
        return self.create_user(username, email, password, **extra_fields)


class User(AbstractUser, TimeStampedModel):
    """Compte utilisateur : acheteur et vendeur a la fois."""

    # --- identite ---------------------------------------------------------
    username = models.CharField(
        "nom d'utilisateur",
        max_length=150,
        unique=True,
        db_index=True,
        help_text="Identifiant de connexion, obligatoire et unique.",
    )
    email = models.EmailField(
        "adresse email",
        blank=True,
        null=True,
        unique=True,
        default=None,
        help_text="Facultatif. Si renseigne, il doit etre verifie par code.",
    )
    email_verifie = models.BooleanField("email verifie", default=False)

    nom_complet = models.CharField("nom complet", max_length=150, blank=True)
    telephone = models.CharField(
        "telephone",
        max_length=20,
        blank=True,
        help_text="Contact facultatif, non verifie.",
    )
    photo = models.ImageField("photo de profil", upload_to="profils/", blank=True, null=True)

    # --- localisation : un seul champ texte, saisi librement ---------------
    # Aucune table ni identifiant de localisation : l'utilisateur tape sa
    # localisation comme il la connait ("Taba", "Kinindo pres du marche",
    # "Gitega centre"). La recherche se fait par `icontains`.
    localisation = models.CharField(
        "localisation",
        max_length=255,
        blank=True,
        db_index=True,
        help_text=(
            "Texte libre : quartier, zone, commune ou province, comme vous "
            "l'ecrivez. Jamais l'adresse exacte obligatoire."
        ),
    )

    # --- vitrine vendeur (Module 5 l'enrichira) ---------------------------
    nom_commercial = models.CharField("nom commercial", max_length=150, blank=True)
    description = models.TextField("description du vendeur", blank=True)
    telephone_public = models.BooleanField("afficher mon telephone", default=False)

    # --- etat du compte ---------------------------------------------------
    statut_compte = models.CharField(
        "statut du compte",
        max_length=20,
        choices=StatutCompte.choices,
        default=StatutCompte.ACTIF,
        db_index=True,
    )
    motif_suspension = models.CharField("motif de suspension", max_length=255, blank=True)
    suspendu_le = models.DateTimeField("suspendu le", blank=True, null=True)
    suppression_demandee_le = models.DateTimeField(
        "suppression demandee le", blank=True, null=True
    )

    # Champs AbstractUser non utilises par le projet.
    first_name = None
    last_name = None

    objects = UserManager()

    USERNAME_FIELD = "username"
    # L'email n'est pas obligatoire : il ne figure donc pas dans REQUIRED_FIELDS.
    REQUIRED_FIELDS = []
    EMAIL_FIELD = "email"

    class Meta:
        verbose_name = "utilisateur"
        verbose_name_plural = "utilisateurs"
        ordering = ("-date_joined",)

    def __str__(self):
        return self.username

    # --- helpers metier ---------------------------------------------------
    @property
    def est_suspendu(self) -> bool:
        return self.statut_compte == StatutCompte.SUSPENDU

    def suspendre(self, motif: str = ""):
        self.statut_compte = StatutCompte.SUSPENDU
        self.motif_suspension = motif
        self.suspendu_le = timezone.now()
        self.is_active = False
        self.save(update_fields=[
            "statut_compte", "motif_suspension", "suspendu_le", "is_active", "updated_at",
        ])

    def reactiver(self):
        self.statut_compte = StatutCompte.ACTIF
        self.motif_suspension = ""
        self.suspendu_le = None
        self.is_active = True
        self.save(update_fields=[
            "statut_compte", "motif_suspension", "suspendu_le", "is_active", "updated_at",
        ])


class TypeCodeVerification(models.TextChoices):
    EMAIL = "EMAIL", "Verification d'email"
    RESET_PASSWORD = "RESET_PASSWORD", "Reinitialisation du mot de passe"


class CodeVerificationEmail(TimeStampedModel):
    """Code a 6 chiffres envoye sur l'email declare par l'utilisateur.

    Si l'utilisateur ne saisit jamais le code, c'est que l'email ne lui
    appartient pas : le compte reste non verifie (et inactif a l'inscription).
    """

    utilisateur = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="codes_verification"
    )
    email = models.EmailField("email cible")
    code = models.CharField("code", max_length=6, db_index=True)
    type_code = models.CharField(
        "type", max_length=20, choices=TypeCodeVerification.choices,
        default=TypeCodeVerification.EMAIL,
    )
    expire_le = models.DateTimeField("expire le")
    utilise_le = models.DateTimeField("utilise le", blank=True, null=True)
    tentatives = models.PositiveSmallIntegerField("tentatives", default=0)

    class Meta:
        verbose_name = "code de verification email"
        verbose_name_plural = "codes de verification email"
        ordering = ("-created_at",)

    def __str__(self):
        return f"{self.utilisateur.username} - {self.type_code}"

    @property
    def est_expire(self) -> bool:
        return timezone.now() > self.expire_le

    @property
    def est_valide(self) -> bool:
        return self.utilise_le is None and not self.est_expire
