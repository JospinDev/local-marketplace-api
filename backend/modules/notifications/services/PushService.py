"""Envoi des notifications push (module 12).

Le cahier des charges est categorique : le push est un COMPLEMENT, et
l'application doit continuer a fonctionner si le service est indisponible.
Ce fichier applique cette exigence a la lettre :

- sans configuration (`FCM_SERVER_KEY` absent du `.env`), le service est
  simplement inactif : il n'y a aucune erreur, aucune exception, et la
  notification interne reste enregistree en base ;
- avec configuration, l'envoi est tente ; en cas d'echec, on journalise et
  on continue. Un jeton rejete par le service est desactive pour ne pas
  etre retente indefiniment ;
- aucune exception ne remonte jamais a l'appelant.

Pourquoi aucune dependance a `firebase-admin` : elle imposerait un fichier
de compte de service a l'installation, alors que le projet doit pouvoir
tourner sans aucun compte Firebase. L'API HTTP suffit, et le jour ou vous
choisissez un autre fournisseur, seule la methode `_envoyer` change.
"""
import json
import logging
import urllib.error
import urllib.request

from django.conf import settings

logger = logging.getLogger(__name__)

#: Point d'entree historique de Firebase Cloud Messaging. Surchargeable
#: pour viser un autre fournisseur ou un serveur de test.
URL_PAR_DEFAUT = "https://fcm.googleapis.com/fcm/send"


class PushService:
    """Transport push, volontairement faillible sans consequence."""

    @staticmethod
    def est_configure() -> bool:
        return bool(getattr(settings, "FCM_SERVER_KEY", ""))

    @staticmethod
    def jetons_de(utilisateur) -> list:
        from modules.notifications.models import AppareilPush

        return list(
            AppareilPush.objects.filter(utilisateur=utilisateur, actif=True)
            .values_list("jeton", flat=True)
        )

    @staticmethod
    def envoyer(notification) -> int:
        """Pousse une notification deja enregistree. Retourne le nombre d'envois.

        Retourne 0 si le service n'est pas configure ou si l'utilisateur n'a
        aucun appareil : ce n'est pas une erreur, c'est le cas normal en
        developpement.
        """
        if not PushService.est_configure():
            return 0

        jetons = PushService.jetons_de(notification.destinataire)
        if not jetons:
            return 0

        charge = {
            "notification": {
                "title": notification.titre,
                "body": notification.message,
            },
            "data": {
                "type": notification.type_notification,
                "reference_type": notification.reference_type,
                "reference_id": str(notification.reference_id or ""),
                "notification_id": str(notification.pk),
                **{cle: str(valeur) for cle, valeur in (notification.donnees or {}).items()},
            },
        }

        envoyes = 0
        for jeton in jetons:
            if PushService._envoyer(jeton, charge):
                envoyes += 1
        return envoyes

    # --------------------------------------------------------------- interne
    @staticmethod
    def _envoyer(jeton: str, charge: dict) -> bool:
        url = getattr(settings, "FCM_URL", URL_PAR_DEFAUT)
        corps = json.dumps({**charge, "to": jeton}).encode("utf-8")
        requete = urllib.request.Request(
            url,
            data=corps,
            headers={
                "Authorization": f"key={settings.FCM_SERVER_KEY}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(
                requete, timeout=getattr(settings, "FCM_TIMEOUT", 5)
            ) as reponse:
                return 200 <= reponse.status < 300
        except urllib.error.HTTPError as erreur:
            # 400 et 404 signalent un jeton invalide ou desinscrit : le
            # garder actif reviendrait a retenter a chaque notification.
            if erreur.code in (400, 404):
                PushService._desactiver(jeton)
            logger.warning("Push refuse (%s) pour un appareil", erreur.code)
            return False
        except Exception:
            # Reseau coupe, service en panne, DNS... jamais bloquant.
            logger.warning("Envoi push impossible", exc_info=True)
            return False

    @staticmethod
    def _desactiver(jeton: str) -> None:
        from modules.notifications.models import AppareilPush

        try:
            AppareilPush.objects.filter(jeton=jeton).update(actif=False)
        except Exception:
            logger.warning("Desactivation du jeton push impossible", exc_info=True)
