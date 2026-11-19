"""Representation des utilisateurs (prive et public)."""
from django.contrib.auth import get_user_model
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

User = get_user_model()


class UserSerializer(serializers.ModelSerializer):
    """Vue complete du compte, destinee a son proprietaire ou a l'admin."""

    groupes = serializers.SerializerMethodField()
    permissions = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = (
            "id", "username", "email", "email_verifie", "nom_complet", "telephone",
            "photo", "localisation",
            "nom_commercial", "description", "telephone_public",
            "statut_compte", "motif_suspension", "is_active", "is_staff",
            # `is_superuser` est expose en lecture a son propre titulaire :
            # la console d'administration web en a besoin pour savoir, sans
            # appel supplementaire, si le compte a tous les droits (Django
            # accorde tout au superutilisateur sans stocker les permissions,
            # donc la liste `permissions` ne suffit pas a le deduire).
            "is_superuser",
            "groupes", "permissions", "date_joined", "last_login",
            "created_at", "updated_at",
        )
        read_only_fields = (
            "id", "username", "email", "email_verifie", "statut_compte",
            "motif_suspension", "is_active", "is_staff", "is_superuser",
            "date_joined", "last_login", "created_at", "updated_at",
        )

    @extend_schema_field(serializers.ListField(child=serializers.CharField()))
    def get_groupes(self, obj) -> list:
        return list(obj.groups.values_list("name", flat=True))

    @extend_schema_field(serializers.ListField(child=serializers.CharField()))
    def get_permissions(self, obj) -> list:
        return sorted(obj.get_all_permissions())


class UserPublicSerializer(serializers.ModelSerializer):
    """Profil public : aucune donnee sensible exposee."""

    groupes = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = (
            "id", "username", "nom_commercial", "nom_complet", "description",
            "photo", "localisation", "telephone", "groupes", "date_joined",
        )

    @extend_schema_field(serializers.ListField(child=serializers.CharField()))
    def get_groupes(self, obj) -> list:
        return list(obj.groups.values_list("name", flat=True))

    def to_representation(self, instance):
        data = super().to_representation(instance)
        # Confidentialite : le telephone n'est visible que si le vendeur l'autorise.
        if not instance.telephone_public:
            data["telephone"] = None
        return data


class UserAdminSerializer(UserSerializer):
    """Serializer d'administration : le staff peut editer plus de champs."""

    class Meta(UserSerializer.Meta):
        read_only_fields = (
            "id", "email_verifie", "date_joined", "last_login",
            "created_at", "updated_at",
        )
