"""Garde-fou sur la configuration de la couche de canaux.

Pourquoi ce test existe : la suite tourne sur `InMemoryChannelLayer`, donc
AUCUN test de WebSocket ne touche Redis. Un reglage Redis casse passe donc
inapercu — c'est exactement ce qui est arrive.

Le defaut : redis-py 8 a change `socket_timeout` de `None` a 5 secondes,
alors que channels-redis fait un `bzpopmin(timeout=brpop_timeout)` de 5
secondes lui aussi. Le delai de lecture de la socket expirait donc
exactement quand le pop bloquant devait rendre la main : chaque consumer
mourait sur `redis.exceptions.TimeoutError` au bout de cinq secondes et la
connexion se fermait avec le code 1011.

Ce test lit la configuration reelle de `base.py` et verifie l'inegalite
qui doit tenir. Il ne demande ni Redis ni reseau.
"""
from django.test import SimpleTestCase

from channels_redis.core import RedisChannelLayer
from channels_redis.utils import decode_hosts

from config.settings import base


class ConfigurationCoucheCanaux(SimpleTestCase):
    """La configuration Redis doit survivre a un pop bloquant."""

    def setUp(self):
        self.config = base.CHANNEL_LAYERS["default"]["CONFIG"]
        self.hotes = decode_hosts(self.config["hosts"])

    def test_socket_timeout_est_explicite(self):
        """Ne pas dependre du defaut de redis-py, qui a deja change."""
        for hote in self.hotes:
            self.assertIn(
                "socket_timeout",
                hote,
                "Chaque hote doit fixer `socket_timeout` explicitement : "
                "le defaut de redis-py est passe de None a 5 s en version 8, "
                "ce qui a casse tous les WebSocket sans qu'aucun test le voie.",
            )

    def test_socket_timeout_depasse_le_pop_bloquant(self):
        """L'inegalite qui empeche le `TimeoutError` et la fermeture 1011."""
        attente_pop = RedisChannelLayer.brpop_timeout

        for hote in self.hotes:
            self.assertGreater(
                hote["socket_timeout"],
                attente_pop,
                "`socket_timeout` (%s s) doit depasser le `brpop_timeout` de "
                "channels-redis (%s s), sinon la lecture de la socket expire "
                "pendant le pop bloquant et le consumer meurt."
                % (hote.get("socket_timeout"), attente_pop),
            )

    def test_hotes_sont_des_dictionnaires(self):
        """Une simple chaine ne permettrait pas de regler les delais."""
        for entree in self.config["hosts"]:
            self.assertIsInstance(
                entree,
                dict,
                "Les hotes doivent etre des dictionnaires `{'address': ..., "
                "'socket_timeout': ...}` pour porter les delais.",
            )
