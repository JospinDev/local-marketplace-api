"""Inscription : username obligatoire et unique, email facultatif mais verifie."""
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.db import transaction
from rest_framework import serializers

from modules.accounts.models import StatutCompte
from modules.accounts.services import EmailVerificationService

User = get_user_model()


class RegisterSerializer(serializers.ModelSerializer):
    username = serializers.CharField(
        required=True,
        max_length=150,
        help_text="Obligatoire et unique : c'est l'identifiant de connexion.",
    )
    password = serializers.CharField(write_only=True, required=True, min_length=8)
    password_confirmation = serializers.CharField(write_only=True, required=True)
    email = serializers.EmailField(
        required=False,
        allow_blank=True,
        allow_null=True,
        help_text=(
            "Facultatif. Si fourni, un code est envoye a cette adresse et le "
            "compte reste inactif jusqu'a la saisie du code."
        ),
    )

    class Meta:
        model = User
        fields = (
            "username", "password", "password_confirmation", "email",
            "nom_complet", "telephone", "localisation",
        )

    def validate_username(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Le nom d'utilisateur est obligatoire.")
        if User.objects.filter(username__iexact=value).exists():
            raise serializers.ValidationError("Ce nom d'utilisateur est deja pris.")
        return value

    def validate_email(self, value):
        if not value:
            return None
        value = value.strip().lower()
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError("Cette adresse email est deja utilisee.")
        return value

    def validate(self, attrs):
        if attrs.get("password") != attrs.pop("password_confirmation", None):
            raise serializers.ValidationError(
                {"password_confirmation": "Les deux mots de passe ne correspondent pas."}
            )
        validate_password(attrs["password"])
        return attrs

    @transaction.atomic
    def create(self, validated_data):
        password = validated_data.pop("password")
        email = validated_data.pop("email", None)

        # Avec email : le compte attend la preuve de possession de l'adresse.
        # Sans email : le compte est immediatement utilisable.
        avec_email = bool(email)
        utilisateur = User(
            **validated_data,
            email=email,
            email_verifie=False,
            is_active=not avec_email,
            statut_compte=StatutCompte.EN_ATTENTE if avec_email else StatutCompte.ACTIF,
        )
        utilisateur.set_password(password)
        utilisateur.save()

        if avec_email:
            EmailVerificationService.envoyer_code(utilisateur)

        return utilisateur
