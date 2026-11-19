"""Changement, reinitialisation et confirmation du mot de passe."""
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers

from modules.accounts.models import TypeCodeVerification
from modules.accounts.services import EmailVerificationService

User = get_user_model()


class PasswordChangeSerializer(serializers.Serializer):
    """L'utilisateur connecte modifie son mot de passe."""

    ancien_password = serializers.CharField(write_only=True)
    nouveau_password = serializers.CharField(write_only=True, min_length=8)
    nouveau_password_confirmation = serializers.CharField(write_only=True)

    def validate_ancien_password(self, value):
        utilisateur = self.context["request"].user
        if not utilisateur.check_password(value):
            raise serializers.ValidationError("Mot de passe actuel incorrect.")
        return value

    def validate(self, attrs):
        if attrs["nouveau_password"] != attrs["nouveau_password_confirmation"]:
            raise serializers.ValidationError(
                {
                    "nouveau_password_confirmation": (
                        "Les deux mots de passe ne correspondent pas."
                    )
                }
            )
        validate_password(attrs["nouveau_password"], self.context["request"].user)
        return attrs

    def save(self, **kwargs):
        utilisateur = self.context["request"].user
        utilisateur.set_password(self.validated_data["nouveau_password"])
        utilisateur.save(update_fields=["password", "updated_at"])
        return utilisateur


class PasswordResetRequestSerializer(serializers.Serializer):
    """Recuperation de compte : possible uniquement avec un email verifie."""

    username = serializers.CharField()

    def validate(self, attrs):
        utilisateur = User.objects.filter(
            username__iexact=attrs["username"].strip()
        ).first()
        if utilisateur is None:
            raise serializers.ValidationError({"username": "Compte introuvable."})
        if not utilisateur.email or not utilisateur.email_verifie:
            raise serializers.ValidationError(
                {
                    "email": (
                        "Aucun email verifie n'est associe a ce compte : la "
                        "reinitialisation automatique est impossible."
                    )
                }
            )
        EmailVerificationService.envoyer_code(
            utilisateur, TypeCodeVerification.RESET_PASSWORD
        )
        attrs["utilisateur"] = utilisateur
        return attrs


class PasswordResetConfirmSerializer(serializers.Serializer):
    """Validation du code recu par email puis definition du nouveau mot de passe."""

    username = serializers.CharField()
    code = serializers.CharField(max_length=6, min_length=6)
    nouveau_password = serializers.CharField(write_only=True, min_length=8)
    nouveau_password_confirmation = serializers.CharField(write_only=True)

    def validate(self, attrs):
        utilisateur = User.objects.filter(
            username__iexact=attrs["username"].strip()
        ).first()
        if utilisateur is None:
            raise serializers.ValidationError({"username": "Compte introuvable."})
        if attrs["nouveau_password"] != attrs["nouveau_password_confirmation"]:
            raise serializers.ValidationError(
                {
                    "nouveau_password_confirmation": (
                        "Les deux mots de passe ne correspondent pas."
                    )
                }
            )
        validate_password(attrs["nouveau_password"], utilisateur)
        EmailVerificationService.verifier_code(
            utilisateur, attrs["code"], TypeCodeVerification.RESET_PASSWORD
        )
        attrs["utilisateur"] = utilisateur
        return attrs

    def save(self, **kwargs):
        utilisateur = self.validated_data["utilisateur"]
        utilisateur.set_password(self.validated_data["nouveau_password"])
        utilisateur.save(update_fields=["password", "updated_at"])
        return utilisateur
