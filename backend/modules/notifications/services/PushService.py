"""Envoi des notifications push (module 12), via FCM HTTP v1.

Le cahier des charges est categorique : le push est un COMPLEMENT, et
l'application doit continuer a fonctionner si le service est indisponible.
Ce fichier applique cette exigence a la lettre :

- sans configuration (`FIREBASE_CREDENTIALS_PATH` absent du `.env`), le
  service est simplement inactif : aucune erreur, aucune exception, et la
  notification interne reste enregistree en base ;
- sans la bibliotheque `firebase-admin` installee, meme chose : le module
  se desactive au lieu de faire planter l'import ;
- en cas d'echec d'envoi, on journalise et on continue. Un jeton rejete
  par Google est desactive, pour ne pas etre retente indefiniment ;
- aucune exception ne remonte jamais a l'appelant.

Note d'histoire, utile a qui relira du vieux code ou de vieux tutoriels :
l'ancienne API « FCM legacy », qui s'authentifiait avec une simple
`FCM_SERVER_KEY` envoyee a `fcm.googleapis.com/fcm/send`, a ete
**desactivee par Google en 2024**. Elle ne fonctionne plus, quelle que
soit la cle. L'API actuelle est HTTP v1 : elle s'authentifie avec un
COMPTE DE SERVICE (un fichier JSON telecharge depuis la console Firebase)
et un jeton OAuth2 de courte duree, que `firebase-admin` renouvelle tout
seul. C'est pourquoi ce service ne connait plus de « cle serveur ».

Mise en route :

1. console.firebase.google.com, creer le projet ;
2. roue dentee > Parametres du projet > Comptes de service >
   « Generer une nouvelle cle privee » : un fichier JSON se telecharge ;
3. le placer HORS du depot Git, et renseigner dans le `.env` :
   `FIREBASE_CREDENTIALS_PATH=C:/chemin/vers/le-fichier.json` ;
4. `pip install firebase-admin`.

Le fichier JSON donne un acces complet a l'envoi de notifications pour le
projet : il se traite comme un mot de passe.
"""
import logging
import os
import threading

from django.conf import settings

logger = logging.getLogger(__name__)

#: Verrou d'initialisation : plusieurs requetes peuvent vouloir demarrer
#: Firebase en meme temps, et l'initialiser deux fois leve une exception.
_verrou = threading.Lock()
_application_firebase = None
_initialisation_tentee = False


class PushService:
    """Transport push, volontairement faillible sans consequence."""

    # ------------------------------------------------------- configuration
    @staticmethod
    def chemin_identifiants() -> str:
        return getattr(settings, 'FIREBASE_CREDENTIALS_PATH', '') or ''

    @staticmethod
    def est_configure() -> bool:
        """Vrai seulement si tout est reuni pour envoyer reellement.

        On verifie l'existence du FICHIER, pas seulement le reglage : un
        chemin mal copie est l'erreur la plus courante, et il vaut mieux
        la voir ici que dans une trace d'erreur au premier envoi.
        """
        chemin = PushService.chemin_identifiants()
        if not chemin:
            return False
        if not os.path.isfile(chemin):
            logger.warning(
                'FIREBASE_CREDENTIALS_PATH pointe vers un fichier '
                'introuvable : %s. Le push reste inactif.',
                chemin,
            )
            return False
        return PushService._messagerie() is not None

    # -------------------------------------------------------- initialisation
    @staticmethod
    def _messagerie():
        """Retourne le module `messaging` de firebase-admin, ou None.

        L'import est local et tolerant : `firebase-admin` n'est pas une
        dependance obligatoire du projet. Une plateforme qui ne veut pas
        de push n'a aucune raison de l'installer.
        """
        global _application_firebase, _initialisation_tentee

        if _application_firebase is not None:
            from firebase_admin import messaging

            return messaging

        with _verrou:
            # Un autre fil a pu initialiser pendant l'attente du verrou.
            if _application_firebase is not None:
                from firebase_admin import messaging

                return messaging
            if _initialisation_tentee:
                return None
            _initialisation_tentee = True

            try:
                import firebase_admin
                from firebase_admin import credentials, messaging
            except ImportError:
                logger.info(
                    'firebase-admin absent : notifications push inactives. '
                    'Les notifications internes et le temps reel '
                    'fonctionnent normalement.'
                )
                return None

            try:
                # Une autre partie du projet a pu initialiser l'application
                # par defaut : on la reutilise plutot que d'echouer.
                if firebase_admin._apps:
                    _application_firebase = firebase_admin.get_app()
                else:
                    identifiants = credentials.Certificate(
                        PushService.chemin_identifiants()
                    )
                    _application_firebase = firebase_admin.initialize_app(
                        identifiants
                    )
                return messaging
            except Exception:
                logger.warning(
                    'Initialisation de Firebase impossible : le push reste '
                    'inactif.',
                    exc_info=True,
                )
                return None

    # ------------------------------------------------------------ appareils
    @staticmethod
    def jetons_de(utilisateur) -> list:
        from modules.notifications.models import AppareilPush

        return list(
            AppareilPush.objects.filter(utilisateur=utilisateur, actif=True)
            .values_list('jeton', flat=True)
        )

    # --------------------------------------------------------------- envoi
    @staticmethod
    def envoyer(notification) -> int:
        """Pousse une notification deja enregistree. Retourne le nombre d'envois.

        Retourne 0 si le service n'est pas configure ou si l'utilisateur
        n'a aucun appareil : ce n'est pas une erreur, c'est le cas normal
        en developpement.
        """
        messaging = PushService._messagerie()
        if messaging is None or not PushService.chemin_identifiants():
            return 0

        jetons = PushService.jetons_de(notification.destinataire)
        if not jetons:
            return 0

        # FCM v1 n'accepte que des chaines dans `data` : tout est converti,
        # et c'est au client Flutter de reinterpreter les nombres.
        donnees = {
            'type': str(notification.type_notification),
            'reference_type': str(notification.reference_type or ''),
            'reference_id': str(notification.reference_id or ''),
            'notification_id': str(notification.pk),
        }
        for cle, valeur in (notification.donnees or {}).items():
            donnees[str(cle)] = str(valeur)

        envoyes = 0
        for jeton in jetons:
            if PushService._envoyer(messaging, jeton, notification, donnees):
                envoyes += 1
        return envoyes

    @staticmethod
    def _envoyer(messaging, jeton: str, notification, donnees: dict) -> bool:
        try:
            message = messaging.Message(
                token=jeton,
                notification=messaging.Notification(
                    title=notification.titre,
                    body=notification.message,
                ),
                data=donnees,
                android=messaging.AndroidConfig(
                    priority='high',
                    notification=messaging.AndroidNotification(
                        # Permet a l'application de regrouper les
                        # notifications d'une meme conversation.
                        tag=f'{notification.reference_type}'
                            f'-{notification.reference_id}'
                        if notification.reference_type
                        else None,
                    ),
                ),
            )
            messaging.send(message)
            return True
        except Exception as erreur:
            PushService._traiter_echec(messaging, jeton, erreur)
            return False

    @staticmethod
    def _traiter_echec(messaging, jeton: str, erreur: Exception) -> None:
        """Desactive un jeton que Google declare mort.

        `UnregisteredError` signifie que l'application a ete desinstallee
        ou que le jeton a ete renouvele : le garder actif reviendrait a
        retenter a chaque notification, pour rien.
        """
        mort = False
        try:
            mort = isinstance(
                erreur,
                (
                    messaging.UnregisteredError,
                    messaging.SenderIdMismatchError,
                ),
            )
        except Exception:
            mort = False

        if mort:
            PushService._desactiver(jeton)
            logger.info('Jeton push desactive (appareil desinscrit).')
        else:
            logger.warning('Envoi push impossible.', exc_info=True)

    @staticmethod
    def _desactiver(jeton: str) -> None:
        from modules.notifications.models import AppareilPush

        try:
            AppareilPush.objects.filter(jeton=jeton).update(actif=False)
        except Exception:
            logger.warning(
                'Desactivation du jeton push impossible.', exc_info=True
            )

    # ------------------------------------------------------------ outillage
    @staticmethod
    def reinitialiser() -> None:
        """Oublie l'initialisation. Reserve aux tests."""
        global _application_firebase, _initialisation_tentee
        with _verrou:
            _application_firebase = None
            _initialisation_tentee = False
