"""Service metier : envoi et controle des codes de verification email."""
import logging
from datetime import timedelta

from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction
from django.utils import timezone
from rest_framework import serializers
from rest_framework.exceptions import APIException

logger = logging.getLogger(__name__)


class EmailIndisponible(APIException):
    """Le serveur d'envoi d'emails ne repond pas (503).

    Le compte n'est alors pas cree : la transaction est annulee, car un
    compte declare avec un email jamais verifiable serait inutilisable.
    """

    status_code = 503
    default_detail = (
        "Le service d'envoi d'emails est momentanement indisponible. "
        "Reessayez dans quelques instants, ou creez le compte sans email."
    )
    default_code = "email_indisponible"

from common.utils import generate_numeric_code
from modules.accounts.models import (
    CodeVerificationEmail,
    StatutCompte,
    TypeCodeVerification,
)


class EmailVerificationService:
    """Regle : un email declare doit etre prouve par un code recu dessus."""

    @staticmethod
    @transaction.atomic
    def envoyer_code(utilisateur, type_code=TypeCodeVerification.EMAIL, email=None):
        cible = email or utilisateur.email
        if not cible:
            raise serializers.ValidationError(
                {"email": "Aucune adresse email n'est associee a ce compte."}
            )

        # Les anciens codes non utilises du meme type sont invalides.
        CodeVerificationEmail.objects.filter(
            utilisateur=utilisateur, type_code=type_code, utilise_le__isnull=True
        ).update(expire_le=timezone.now())

        code = generate_numeric_code(6)
        verification = CodeVerificationEmail.objects.create(
            utilisateur=utilisateur,
            email=cible,
            code=code,
            type_code=type_code,
            expire_le=timezone.now()
            + timedelta(minutes=settings.EMAIL_CODE_TTL_MINUTES),
        )

        if type_code == TypeCodeVerification.EMAIL:
            sujet = "Marketplace Burundi - Code de verification de votre email"
            corps = (
                f"Bonjour {utilisateur.username},\n\n"
                f"Votre code de verification est : {code}\n"
                f"Il expire dans {settings.EMAIL_CODE_TTL_MINUTES} minutes.\n\n"
                "Si vous n'avez pas cree de compte, ignorez ce message."
            )
        else:
            sujet = "Marketplace Burundi - Reinitialisation du mot de passe"
            corps = (
                f"Bonjour {utilisateur.username},\n\n"
                f"Votre code de reinitialisation est : {code}\n"
                f"Il expire dans {settings.EMAIL_CODE_TTL_MINUTES} minutes."
            )

        try:
            envoyes = send_mail(
                subject=sujet,
                message=corps,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[cible],
                fail_silently=False,
            )
        except Exception as exc:  # SMTP injoignable, identifiants refuses...
            logger.error(
                "Echec d'envoi du code de verification a %s : %s", cible, exc
            )
            raise EmailIndisponible() from exc

        if not envoyes:
            logger.error("Aucun email envoye a %s (0 destinataire accepte).", cible)
            raise EmailIndisponible()

        return verification

    @staticmethod
    @transaction.atomic
    def verifier_code(utilisateur, code, type_code=TypeCodeVerification.EMAIL):
        verification = (
            CodeVerificationEmail.objects.select_for_update()
            .filter(utilisateur=utilisateur, type_code=type_code, utilise_le__isnull=True)
            .order_by("-created_at")
            .first()
        )

        if verification is None:
            raise serializers.ValidationError(
                {"code": "Aucun code en attente. Demandez un nouvel envoi."}
            )

        if verification.est_expire:
            raise serializers.ValidationError(
                {"code": "Ce code a expire. Demandez un nouvel envoi."}
            )

        if verification.tentatives >= settings.EMAIL_CODE_MAX_ATTEMPTS:
            raise serializers.ValidationError(
                {"code": "Trop de tentatives. Demandez un nouvel envoi."}
            )

        if verification.code != str(code):
            verification.tentatives += 1
            verification.save(update_fields=["tentatives", "updated_at"])
            raise serializers.ValidationError({"code": "Code incorrect."})

        verification.utilise_le = timezone.now()
        verification.save(update_fields=["utilise_le", "updated_at"])

        if type_code == TypeCodeVerification.EMAIL:
            utilisateur.email = verification.email
            utilisateur.email_verifie = True
            # L'inscription avec email reste bloquee jusqu'a cette etape.
            utilisateur.is_active = True
            if utilisateur.statut_compte == StatutCompte.EN_ATTENTE:
                utilisateur.statut_compte = StatutCompte.ACTIF
            utilisateur.save(update_fields=[
                "email", "email_verifie", "is_active", "statut_compte", "updated_at",
            ])

        return verification
