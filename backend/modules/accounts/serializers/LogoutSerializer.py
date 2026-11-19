"""Deconnexion : mise en liste noire du refresh token."""
from rest_framework import serializers
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken


class LogoutSerializer(serializers.Serializer):
    refresh = serializers.CharField(write_only=True)

    def validate_refresh(self, value):
        try:
            self.token = RefreshToken(value)
        except TokenError:
            raise serializers.ValidationError("Token de rafraichissement invalide.")
        return value

    def save(self, **kwargs):
        try:
            self.token.blacklist()
        except AttributeError:  # pragma: no cover
            raise serializers.ValidationError(
                "La revocation des tokens est indisponible."
            )
        return self.token
