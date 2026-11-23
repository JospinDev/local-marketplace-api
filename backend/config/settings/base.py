"""Configuration commune du backend Marketplace Burundi."""
from datetime import timedelta
from pathlib import Path

from decouple import Config, RepositoryEnv, config as env_config

BASE_DIR = Path(__file__).resolve().parent.parent.parent
ROOT_DIR = BASE_DIR.parent

_env_file = ROOT_DIR / ".env"
config = Config(RepositoryEnv(_env_file)) if _env_file.exists() else env_config

SECRET_KEY = config("SECRET_KEY", default="dev-insecure-key")
DEBUG = config("DEBUG", default=False, cast=bool)
ALLOWED_HOSTS = [h.strip() for h in config("ALLOWED_HOSTS", default="*").split(",")]

# ---------------------------------------------------------------- applications
DJANGO_APPS = [
    # `daphne` en premier : il remplace le serveur de developpement
    # par un serveur ASGI, ce qui rend les WebSocket testables avec
    # `manage.py runserver`.
    "daphne",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
]

THIRD_PARTY_APPS = [
    "channels",
    "rest_framework",
    "rest_framework_simplejwt",
    "rest_framework_simplejwt.token_blacklist",
    "django_filters",
    "drf_spectacular",
    "corsheaders",
]

# Modules metier (monolithe modulaire) - un module = une responsabilite.
LOCAL_APPS = [
    "modules.accounts",
    "modules.categories",
    "modules.products",
    "modules.search",
    "modules.sellers",
    "modules.favorites",
    "modules.messaging",
    "modules.reservations",
    "modules.sales",
    "modules.analytics",
    "modules.reviews",
    "modules.notifications",
    "modules.moderation",
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

# -------------------------------------------------------------------- database
DATABASES = {
    "default": {
        "ENGINE": config("DB_ENGINE", default="django.db.backends.postgresql"),
        "NAME": config("DB_NAME", default="marketplace_local"),
        "USER": config("DB_USER", default="postgres"),
        "PASSWORD": config("DB_PASSWORD", default="postgres"),
        "HOST": config("DB_HOST", default="127.0.0.1"),
        "PORT": config("DB_PORT", default="5432"),
        "ATOMIC_REQUESTS": False,
    }
}

# ---------------------------------------------------------------------- auth
AUTH_USER_MODEL = "accounts.User"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
     "OPTIONS": {"min_length": 8}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "fr"
TIME_ZONE = "Africa/Bujumbura"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ------------------------------------------------------------- django rest framework
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ),
    # Par defaut tout est ferme : chaque ViewSet declare explicitement son acces.
    "DEFAULT_PERMISSION_CLASSES": (
        "rest_framework.permissions.IsAuthenticated",
    ),
    "DEFAULT_FILTER_BACKENDS": (
        "django_filters.rest_framework.DjangoFilterBackend",
        "rest_framework.filters.SearchFilter",
        "common.filters.AliasOrderingFilter",
    ),
    "DEFAULT_PAGINATION_CLASS": "common.pagination.DefaultPagination",
    "PAGE_SIZE": 20,
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "EXCEPTION_HANDLER": "common.exceptions.api_exception_handler",
    "DEFAULT_THROTTLE_CLASSES": (
        "rest_framework.throttling.ScopedRateThrottle",
    ),
    "DEFAULT_THROTTLE_RATES": {
        "auth": "20/min",
        "email_code": "5/hour",
    },
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=60),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=15),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "UPDATE_LAST_LOGIN": True,
    "AUTH_HEADER_TYPES": ("Bearer",),
    "USER_ID_FIELD": "id",
    "USER_ID_CLAIM": "user_id",
}

SPECTACULAR_SETTINGS = {
    "TITLE": "Marketplace Burundi - API",
    "DESCRIPTION": (
        "API REST du marketplace local multi-vendeurs (Burundi).\n\n"
        "Modules livres : 1) Authentication & User Management, "
        "2) Categories Management, 3) Product Management, "
        "4) Product Discovery & Search, 5) Seller Profile & Following, "
        "6) Favorites Management, 7) Messaging & Chat.\n\n"
        "Temps reel : WebSocket sur `/ws/conversations/{id}/` "
        "(authentifie par JWT)."
    ),
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "COMPONENT_SPLIT_REQUEST": True,
    "SCHEMA_PATH_PREFIX": "/api/v1",
    # Nomme explicitement les enumerations partagees pour eviter des noms
    # generes du type "StatusBb8Enum" dans le schema consomme par Flutter.
    "ENUM_NAME_OVERRIDES": {
        "StatutProduitEnum": "modules.products.models.StatutProduit.choices",
        "StatutReservationEnum": "modules.reservations.models.StatutReservation.choices",
        "StatutVenteEnum": "modules.sales.models.StatutVente.choices",
        "StatutPaiementEnum": "modules.sales.models.StatutPaiement.choices",
        "MoyenPaiementEnum": "modules.sales.models.MoyenPaiement.choices",
        "ActionAuditEnum": "modules.moderation.models.ActionAudit.choices",
        "TypeValeurParametreEnum": "modules.moderation.models.TypeValeurParametre.choices",
        "TypeNotificationEnum": "modules.notifications.models.TypeNotification.choices",
        "PlateformeAppareilEnum": "modules.notifications.models.PlateformeAppareil.choices",
        "StatutEvaluationEnum": "modules.reviews.models.StatutEvaluation.choices",
        "MotifSignalementEvaluationEnum": "modules.reviews.models.MotifSignalementEvaluation.choices",
        "TypeMouvementStockEnum": "modules.products.models.TypeMouvementStock.choices",
        "StatutModerationEnum": [
            ("ACTIVE", "Active"),
            ("PENDING", "En attente de moderation"),
            ("REMOVED", "Retiree par l'administration"),
            ("PAUSED", "En pause"),
        ],
    },
    "TAGS": [
        {"name": "Auth", "description": "Inscription, connexion, verification email"},
        {"name": "Mon compte", "description": "Profil de l'utilisateur connecte"},
        {"name": "Admin - Utilisateurs", "description": "Gestion des comptes (permissions par groupe)"},
        {"name": "Public - Categories", "description": "Catalogue des categories (sans authentification)"},
        {"name": "Public - Produits", "description": "Catalogue, recherche et filtres (sans authentification)"},
        {"name": "Vendeur - Mes annonces", "description": "Gestion de ses propres annonces et de son stock"},
        {"name": "Admin - Annonces", "description": "Moderation du catalogue (permissions par groupe)"},
        {"name": "Public - Vendeurs", "description": "Vitrines commerciales des vendeurs (sans authentification)"},
        {"name": "Mes vendeurs suivis", "description": "Abonnements aux vendeurs et leurs annonces"},
        {"name": "Mes favoris", "description": "Produits sauvegardes (prive)"},
        {"name": "Messagerie", "description": "Conversations acheteur-vendeur et temps reel"},
        {"name": "Reservations", "description": "Demandes, acceptations et quantites mises de cote"},
        {"name": "Ventes", "description": "Ventes declarees, paiements et revenus"},
        {"name": "Tableau de bord vendeur", "description": "Indicateurs commerciaux et financiers du vendeur"},
        {"name": "Evaluations", "description": "Avis sur les produits et les vendeurs"},
        {"name": "Public - Evaluations", "description": "Avis visibles par tous (sans authentification)"},
        {"name": "Admin - Evaluations", "description": "Moderation des avis (permissions par groupe)"},
        {"name": "Notifications", "description": "Historique, non-lus et appareils push"},
        {"name": "Admin - Audit", "description": "Journal des decisions d'administration"},
        {"name": "Admin - Statistiques", "description": "Chiffres globaux de la plateforme"},
        {"name": "Admin - Signalements", "description": "File de moderation des signalements"},
        {"name": "Admin - Litiges", "description": "Historique du stock, ventes et reservations"},
        {"name": "Admin - Configuration", "description": "Reglages metier modifiables"},
        {"name": "Admin - Categories", "description": "Gestion des categories (permissions par groupe)"},
    ],
}

# ----------------------------------------------------------- temps reel
# Redis sert uniquement de transport pour les evenements WebSocket.
# Les messages eux-memes sont conserves dans PostgreSQL.
REDIS_HOST = config("REDIS_HOST", default="127.0.0.1")
REDIS_PORT = config("REDIS_PORT", default=6379, cast=int)
REDIS_DB = config("REDIS_DB", default=0, cast=int)
REDIS_PASSWORD = config("REDIS_PASSWORD", default="")

# channels-redis 4 attend une URL de connexion : un tuple (hote, port)
# leve "tuple object has no attribute decode" au premier envoi.
_authentification = f":{REDIS_PASSWORD}@" if REDIS_PASSWORD else ""
REDIS_URL = config(
    "REDIS_URL",
    default=f"redis://{_authentification}{REDIS_HOST}:{REDIS_PORT}/{REDIS_DB}",
)

# `socket_timeout` est explicite et PLUS GRAND que les 5 secondes du
# `bzpopmin` de channels-redis. redis-py 8 a change le defaut de
# `socket_timeout` de None a 5 secondes : le delai de lecture de la socket
# expirait donc exactement quand le pop bloquant devait rendre la main, et
# chaque consumer mourait sur `redis.exceptions.TimeoutError` au bout de
# cinq secondes, ferme avec le code 1011. Le symptome cote mobile etait un
# temps reel qui se reconnectait sans fin.
CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": {
            "hosts": [
                {
                    "address": REDIS_URL,
                    "socket_timeout": 20,
                    "socket_connect_timeout": 5,
                    "socket_keepalive": True,
                }
            ],
            "capacity": 1000,
            "expiry": 30,
        },
    }
}

# ------------------------------------------------------------------------ email
EMAIL_BACKEND = config(
    "EMAIL_BACKEND", default="django.core.mail.backends.smtp.EmailBackend"
)
EMAIL_HOST = config("EMAIL_HOST", default="smtp.gmail.com")
EMAIL_PORT = config("EMAIL_PORT", default=587, cast=int)
EMAIL_USE_TLS = config("EMAIL_USE_TLS", default=True, cast=bool)
EMAIL_USE_SSL = config("EMAIL_USE_SSL", default=False, cast=bool)
EMAIL_HOST_USER = config("EMAIL_HOST_USER", default="")
EMAIL_HOST_PASSWORD = config("EMAIL_HOST_PASSWORD", default="")
# Evite qu'un serveur SMTP muet bloque la requete d'inscription.
EMAIL_TIMEOUT = config("EMAIL_TIMEOUT", default=10, cast=int)
DEFAULT_FROM_EMAIL = config(
    "DEFAULT_FROM_EMAIL", default=EMAIL_HOST_USER or "no-reply@marketplace.bi"
)

# Filet de securite : si le backend SMTP est demande mais que les identifiants
# ne sont pas renseignes, on retombe sur la console plutot que de faire
# echouer toutes les inscriptions avec un email. Des que EMAIL_HOST_PASSWORD
# est renseigne dans .env, l'envoi reel s'active sans autre changement.
EMAIL_SMTP_CONFIGURE = bool(EMAIL_HOST_USER and EMAIL_HOST_PASSWORD)
if EMAIL_BACKEND.endswith("smtp.EmailBackend") and not EMAIL_SMTP_CONFIGURE:
    EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

# Duree de validite du code de verification envoye par email.
EMAIL_CODE_TTL_MINUTES = config("EMAIL_CODE_TTL_MINUTES", default=15, cast=int)
EMAIL_CODE_MAX_ATTEMPTS = config("EMAIL_CODE_MAX_ATTEMPTS", default=5, cast=int)

CORS_ALLOW_ALL_ORIGINS = DEBUG


# --------------------------------------------------- reservations (module 8)
# Duree de validite d'une reservation, en heures. Le cahier des charges
# demande une date d'expiration configurable : passe ce delai, la quantite
# mise de cote est liberee et redevient disponible pour les autres acheteurs.
# Le compte a rebours repart a l'acceptation du vendeur.
RESERVATION_DUREE_HEURES = config("RESERVATION_DUREE_HEURES", default=72, cast=int)


# ----------------------------------------------------- evaluations (module 11)
# Duree pendant laquelle l'auteur peut encore corriger son avis. Passe ce
# delai l'avis est definitif : une reputation ne doit pas pouvoir etre
# reecrite des mois plus tard, par exemple sous la pression du vendeur.
EVALUATION_DELAI_MODIFICATION_HEURES = config(
    "EVALUATION_DELAI_MODIFICATION_HEURES", default=48, cast=int
)


# --------------------------------------------------- notifications (module 12)
# Seuil de l'alerte "produit presque epuise", en unites restantes.
STOCK_SEUIL_ALERTE = config("STOCK_SEUIL_ALERTE", default=3, cast=int)

# Notifications push : COMPLEMENTAIRES. Sans fichier d'identifiants, le
# service est inactif et l'application continue de fonctionner
# (notifications internes + WebSocket), comme l'exige le cahier des charges.
#
# Firebase Cloud Messaging, API HTTP v1. L'ancienne « cle serveur »
# (`FCM_SERVER_KEY`) a ete DESACTIVEE par Google en 2024 : elle ne
# fonctionne plus, quelle que soit sa valeur. L'authentification se fait
# desormais avec un compte de service, c'est-a-dire un fichier JSON
# telecharge depuis la console Firebase (Parametres du projet > Comptes de
# service > Generer une nouvelle cle privee).
#
# Ce fichier donne un acces complet a l'envoi de notifications : il se
# place HORS du depot et n'est jamais versionne.
FIREBASE_CREDENTIALS_PATH = config("FIREBASE_CREDENTIALS_PATH", default="")
