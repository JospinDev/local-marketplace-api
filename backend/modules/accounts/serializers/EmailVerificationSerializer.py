"""Verification de l'email declare a l'inscription (code a 6 chiffres).

Si l'utilisateur ne saisit jamais le code recu, l'adresse ne lui appartient
pas : le compte reste inactif et inutilisable.
"""
from django.contrib.auth import get_user_model
from rest_framework import serializers

from modules.accounts.models import TypeCodeVerification
from modules.accounts.services import EmailVerificationService

User = get_user_model()


class EmailVerifySerializer(serializers.Serializer):
    """Le compte est identifie par son username (identifiant unique)."""

    username = serializers.CharField()
    code = serializers.CharField(max_length=6, min_length=6)

    def validate(self, attrs):
        utilisateur = User.objects.filter(
            username__iexact=attrs["username"].strip()
        ).first()
        if utilisateur is None:
            raise serializers.ValidationError({"username": "Compte introuvable."})
        if utilisateur.email_verifie:
            raise serializers.ValidationError({"email": "Cet email est deja verifie."})

        EmailVerificationService.verifier_code(
            utilisateur, attrs["code"], TypeCodeVerification.EMAIL
        )
        attrs["utilisateur"] = utilisateur
        return attrs


class EmailResendSerializer(serializers.Serializer):
    """Renvoi du code de verification, avec correction possible de l'adresse."""

    username = serializers.CharField()
    email = serializers.EmailField(
        required=False,
        help_text="Permet de corriger l'adresse si elle a ete mal saisie.",
    )

    def validate(self, attrs):
        utilisateur = User.objects.filter(
            username__iexact=attrs["username"].strip()
        ).first()
        if utilisateur is None:
            raise serializers.ValidationError({"username": "Compte introuvable."})
        if utilisateur.email_verifie:
            raise serializers.ValidationError({"email": "Cet email est deja verifie."})

        nouvel_email = attrs.get("email")
        if nouvel_email:
            nouvel_email = nouvel_email.strip().lower()
            doublon = (
                User.objects.filter(email__iexact=nouvel_email)
                .exclude(pk=utilisateur.pk)
                .exists()
            )
            if doublon:
                raise serializers.ValidationError(
                    {"email": "Cette adresse email est deja utilisee."}
                )
            utilisateur.email = nouvel_email
            utilisateur.save(update_fields=["email", "updated_at"])

        if not utilisateur.email:
            raise serializers.ValidationError(
                {"email": "Aucune adresse email n'est associee a ce compte."}
            )

        EmailVerificationService.envoyer_code(utilisateur)
        attrs["utilisateur"] = utilisateur
        return attrs
