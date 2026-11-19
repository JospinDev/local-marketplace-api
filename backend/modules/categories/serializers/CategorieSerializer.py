"""Serializers du module 2."""
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from modules.categories.models import Categorie


class CategorieSerializer(serializers.ModelSerializer):
    """Lecture / ecriture d'une categorie."""

    # `parent` reste facultatif : une categorie sans parent est une racine.
    # Il est declare explicitement car la contrainte d'unicite (parent, nom)
    # rendrait sinon le champ obligatoire via UniqueTogetherValidator.
    parent = serializers.PrimaryKeyRelatedField(
        queryset=Categorie.objects.all(),
        required=False,
        allow_null=True,
        default=None,
        help_text="Vide pour une categorie racine.",
    )
    parent_nom = serializers.CharField(source="parent.nom", read_only=True, default=None)
    chemin_complet = serializers.CharField(read_only=True)
    niveau = serializers.IntegerField(read_only=True)
    nombre_sous_categories = serializers.SerializerMethodField()

    class Meta:
        model = Categorie
        fields = (
            "id", "nom", "slug", "description", "parent", "parent_nom",
            "chemin_complet", "niveau", "image", "icone", "ordre", "is_active",
            "nombre_sous_categories", "created_at", "updated_at",
        )
        read_only_fields = ("id", "slug", "created_at", "updated_at")
        # Le controle d'unicite (nom unique sous un meme parent) est fait dans
        # `validate()` : il doit aussi fonctionner quand `parent` est NULL,
        # ce que le validateur automatique de DRF ne gere pas.
        validators = []

    def get_nombre_sous_categories(self, obj) -> int:
        return obj.sous_categories.count()

    def validate_nom(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Le nom est obligatoire.")
        return value

    def validate(self, attrs):
        parent = attrs.get("parent", getattr(self.instance, "parent", None))
        nom = attrs.get("nom", getattr(self.instance, "nom", None))

        # Pas de doublon de nom sous un meme parent.
        doublon = Categorie.objects.filter(parent=parent, nom__iexact=nom)
        if self.instance is not None:
            doublon = doublon.exclude(pk=self.instance.pk)
        if doublon.exists():
            raise serializers.ValidationError(
                {"nom": "Une categorie porte deja ce nom au meme niveau."}
            )

        # Pas de cycle dans la hierarchie.
        if self.instance is not None and parent is not None:
            if parent.pk == self.instance.pk:
                raise serializers.ValidationError(
                    {"parent": "Une categorie ne peut pas etre sa propre parente."}
                )
            ancetre = parent
            while ancetre is not None:
                if ancetre.pk == self.instance.pk:
                    raise serializers.ValidationError(
                        {"parent": "Hierarchie circulaire detectee."}
                    )
                ancetre = ancetre.parent
        return attrs


class SousCategorieSerializer(serializers.ModelSerializer):
    """Representation allegee utilisee dans l'arborescence."""

    class Meta:
        model = Categorie
        fields = ("id", "nom", "slug", "image", "icone", "ordre", "is_active")


class CategorieTreeSerializer(serializers.ModelSerializer):
    """Categorie racine avec ses sous-categories actives."""

    sous_categories = serializers.SerializerMethodField()

    class Meta:
        model = Categorie
        fields = (
            "id", "nom", "slug", "description", "image", "icone",
            "ordre", "is_active", "sous_categories",
        )

    @extend_schema_field(SousCategorieSerializer(many=True))
    def get_sous_categories(self, obj):
        enfants = obj.sous_categories.filter(is_active=True).order_by("ordre", "nom")
        return SousCategorieSerializer(enfants, many=True, context=self.context).data
