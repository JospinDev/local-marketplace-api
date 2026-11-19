"""Connexion par username + password uniquement (pas de telephone)."""
from django.contrib.auth import authenticate, get_user_model
from rest_framework import serializers
from rest_framework_simplejwt.tokens import RefreshToken

from modules.accounts.models import StatutCompte
from modules.accounts.serializers.UserSerializer import UserSerializer

User = get_user_model()


class LoginSerializer(serializers.Serializer):
    """Identification par nom d'utilisateur et mot de passe."""

    username = serializers.CharField(write_only=True)
    password = serializers.CharField(write_only=True, style={"input_type": "password"})

    access = serializers.CharField(read_only=True)
    refresh = serializers.CharField(read_only=True)
    utilisateur = UserSerializer(read_only=True)

    default_error_messages = {
        "invalide": "Nom d'utilisateur ou mot de passe incorrect.",
    }

    def validate(self, attrs):
        request = self.context.get("request")
        username = attrs["username"].strip()
        utilisateur = authenticate(
            request=request, username=username, password=attrs["password"]
        )

        if utilisateur is None:
            existant = User.objects.filter(username__iexact=username).first()
            if existant is not None and not existant.is_active:
                if existant.email and not existant.email_verifie:
                    raise serializers.ValidationError(
                        {
                            "email": (
                                "Votre email n'est pas encore verifie. Saisissez le "
                                "code recu sur votre adresse email pour activer le "
                                "compte."
                            )
                        }
                    )
                raise serializers.ValidationError(
                    {"detail": "Ce compte est desactive ou suspendu."}
                )
            # Message generique : pas d'enumeration des comptes existants.
            self.fail("invalide")

        if utilisateur.statut_compte == StatutCompte.SUSPENDU:
            raise serializers.ValidationError({"detail": "Ce compte est suspendu."})

        refresh = RefreshToken.for_user(utilisateur)
        return {
            "access": str(refresh.access_token),
            "refresh": str(refresh),
            "utilisateur": utilisateur,
        }
