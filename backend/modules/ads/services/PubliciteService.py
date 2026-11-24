"""Regles d'affichage du bandeau publicitaire."""
import logging

from django.db import transaction
from django.db.models import F

from modules.ads.models import Publicite

logger = logging.getLogger(__name__)

#: Clef de l'interrupteur global dans `ParametrePlateforme`.
CLE_INTERRUPTEUR = "PUBLICITES_ACTIVES"


class PubliciteService:
    """Lecture et extinction du bandeau."""

    @staticmethod
    def bandeau_actif() -> bool:
        """Etat de l'interrupteur global.

        Par defaut **actif** : une plateforme neuve n'a aucune publicite,
        donc le bandeau reste invisible de toute facon, et l'administrateur
        n'a pas a penser a allumer un interrupteur avant sa premiere
        publicite.
        """
        from modules.moderation.models import ParametrePlateforme

        valeur = ParametrePlateforme.valeur_de(CLE_INTERRUPTEUR, True)
        if isinstance(valeur, bool):
            return valeur
        return str(valeur).strip().lower() not in {"0", "false", "non", "off", ""}

    @staticmethod
    def basculer(actives: bool, utilisateur=None) -> bool:
        """Allume ou coupe le bandeau entier."""
        from modules.moderation.models import ParametrePlateforme, TypeValeurParametre

        parametre, _ = ParametrePlateforme.objects.update_or_create(
            cle=CLE_INTERRUPTEUR,
            defaults={
                "valeur": "true" if actives else "false",
                "type_valeur": TypeValeurParametre.BOOLEEN,
                "description": (
                    "Affiche le bandeau publicitaire en haut de l'accueil mobile."
                ),
                "modifie_par": utilisateur if utilisateur else None,
            },
        )
        return parametre.valeur.strip().lower() == "true"

    @staticmethod
    def diffusables():
        """Publicites a envoyer au client, dans l'ordre d'affichage.

        L'interrupteur global est verifie ici et non dans le ViewSet : la
        regle « coupe tout » doit tenir quel que soit l'appelant.
        """
        if not PubliciteService.bandeau_actif():
            return Publicite.objects.none()
        return Publicite.objects.diffusables().order_by("ordre", "-created_at")

    @staticmethod
    def compter_affichages(identifiants) -> None:
        """Incremente le compteur d'affichages, sans jamais echouer.

        Un compteur indicatif ne doit pas faire tomber la requete qui
        affiche le bandeau. Le point de sauvegarde isole l'ecriture : si
        elle echoue, la lecture reste valide.
        """
        identifiants = [i for i in identifiants if i]
        if not identifiants:
            return
        try:
            with transaction.atomic():
                Publicite.objects.filter(id__in=identifiants).update(
                    nombre_affichages=F("nombre_affichages") + 1
                )
        except Exception:
            logger.warning("Comptage des affichages impossible", exc_info=True)

    @staticmethod
    def compter_clic(publicite_id) -> None:
        """Idem pour un clic."""
        try:
            with transaction.atomic():
                Publicite.objects.filter(id=publicite_id).update(
                    nombre_clics=F("nombre_clics") + 1
                )
        except Exception:
            logger.warning("Comptage du clic impossible", exc_info=True)
