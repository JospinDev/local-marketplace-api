"""Configuration des tests automatises : base SQLite en memoire, emails captures."""
from .base import *  # noqa: F401,F403

DEBUG = False

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}

EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"

# Couche de canaux en memoire : les tests WebSocket ne dependent pas
# de Redis. La configuration de developpement, elle, utilise Redis.
CHANNEL_LAYERS = {
    "default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}
}

PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

# Les quotas de requetes ne doivent pas faire echouer les tests.
REST_FRAMEWORK = {  # noqa: F405
    **REST_FRAMEWORK,  # noqa: F405
    "DEFAULT_THROTTLE_RATES": {"auth": "10000/min", "email_code": "10000/min"},
}

# Les tests de robustesse provoquent de vraies pannes (notifications, push,
# audit) pour verifier qu'elles ne cassent rien. Leurs traces sont donc
# attendues : les taire garde la sortie des tests lisible. En developpement
# et en production, elles restent bien visibles.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"nulle": {"class": "logging.NullHandler"}},
    "loggers": {
        "modules.notifications": {"handlers": ["nulle"], "level": "CRITICAL"},
        "modules.moderation": {"handlers": ["nulle"], "level": "CRITICAL"},
        "modules.messaging": {"handlers": ["nulle"], "level": "CRITICAL"},
    },
}
