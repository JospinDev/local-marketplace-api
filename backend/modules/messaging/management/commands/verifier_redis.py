"""Verifie que la couche de canaux Redis fonctionne reellement.

Usage :

    python manage.py verifier_redis

Les tests automatises utilisent une couche en memoire pour ne pas dependre
d'un service externe. Cette commande, elle, exerce le vrai transport
configure dans `CHANNEL_LAYERS` : elle envoie un evenement dans un groupe et
verifie qu'il revient.
"""
import time

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Teste la couche de canaux (Redis) utilisee par les WebSocket."

    def handle(self, *args, **options):
        configuration = settings.CHANNEL_LAYERS["default"]
        self.stdout.write("Configuration de la couche de canaux :")
        self.stdout.write(f"  BACKEND = {configuration['BACKEND']}")
        for hote in configuration.get("CONFIG", {}).get("hosts", []):
            self.stdout.write(f"  hote    = {hote}")
        self.stdout.write("")

        couche = get_channel_layer()
        if couche is None:
            raise CommandError("Aucune couche de canaux configuree.")

        groupe = "verification_redis"
        canal = async_to_sync(couche.new_channel)()
        charge = {"type": "evenement.messagerie", "contenu": {"ping": time.time()}}

        try:
            async_to_sync(couche.group_add)(groupe, canal)
            async_to_sync(couche.group_send)(groupe, charge)
            recu = async_to_sync(couche.receive)(canal)
        except Exception as exc:
            self.stderr.write(self.style.ERROR(f"Echec : {exc}"))
            self.stderr.write(
                "Verifiez que Redis est demarre et accessible sur "
                f"{configuration.get('CONFIG', {}).get('hosts')}."
            )
            raise CommandError("La couche de canaux ne fonctionne pas.") from exc
        finally:
            try:
                async_to_sync(couche.group_discard)(groupe, canal)
            except Exception:
                pass

        if recu.get("contenu") != charge["contenu"]:
            raise CommandError(f"Evenement different de celui envoye : {recu}")

        self.stdout.write(
            self.style.SUCCESS(
                "Couche de canaux operationnelle : l'evenement envoye dans le "
                "groupe a bien ete recu. Les WebSocket peuvent diffuser en "
                "temps reel."
            )
        )
