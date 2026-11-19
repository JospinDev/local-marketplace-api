"""Serializers du module 3 - gestion des annonces par leur proprietaire."""
from django.db import transaction
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from modules.categories.models import Categorie
from modules.products.models import Inventaire, Produit, StatutProduit
from modules.products.serializers.InventaireSerializer import (
    InventaireLectureSerializer,
    InventaireSerializer,
)
from modules.products.serializers.ProduitImageSerializer import ProduitImageSerializer


class ProduitSerializer(serializers.ModelSerializer):
    """Lecture et ecriture d'une annonce par son vendeur.

    `owner` n'est jamais accepte en entree : il est deduit de l'utilisateur
    authentifie. `status`, `quantite_vendue` et `quantite_reservee` ne sont
    pas modifiables par le vendeur.
    """

    categorie = serializers.PrimaryKeyRelatedField(
        queryset=Categorie.objects.filter(is_active=True)
    )
    categorie_nom = serializers.CharField(source="categorie.nom", read_only=True)
    categorie_chemin = serializers.CharField(
        source="categorie.chemin_complet", read_only=True
    )

    owner_username = serializers.CharField(source="owner.username", read_only=True)

    # Stock : ecriture possible uniquement sur `quantite_totale`.
    inventaire = InventaireSerializer(required=False)
    quantite_disponible = serializers.IntegerField(read_only=True)

    images = ProduitImageSerializer(many=True, read_only=True)
    image_principale = serializers.SerializerMethodField()

    class Meta:
        model = Produit
        fields = (
            "id", "titre", "slug", "description",
            "categorie", "categorie_nom", "categorie_chemin",
            "owner", "owner_username",
            "prix", "devise", "etat", "status",
            "localisation", "latitude", "longitude",
            "inventaire", "quantite_disponible",
            "images", "image_principale",
            "est_mis_en_avant", "nombre_vues",
            "publie_le", "motif_moderation", "created_at", "updated_at",
        )
        read_only_fields = (
            "id", "slug", "owner", "status", "est_mis_en_avant", "nombre_vues",
            "publie_le", "motif_moderation", "created_at", "updated_at",
        )

    @extend_schema_field(ProduitImageSerializer)
    def get_image_principale(self, obj):
        image = next(
            (i for i in obj.images.all() if i.est_principale),
            next(iter(obj.images.all()), None),
        )
        return ProduitImageSerializer(image, context=self.context).data if image else None

    def validate_prix(self, value):
        if value <= 0:
            raise serializers.ValidationError("Le prix doit etre superieur a zero.")
        return value

    def validate(self, attrs):
        latitude = attrs.get("latitude", getattr(self.instance, "latitude", None))
        longitude = attrs.get("longitude", getattr(self.instance, "longitude", None))
        if (latitude is None) != (longitude is None):
            raise serializers.ValidationError(
                {
                    "latitude": (
                        "Latitude et longitude doivent etre fournies ensemble "
                        "ou laissees vides."
                    )
                }
            )
        return attrs

    @transaction.atomic
    def create(self, validated_data):
        donnees_inventaire = validated_data.pop("inventaire", None) or {}
        quantite = donnees_inventaire.get("quantite_totale", 0)

        # Regle 1 : chaque produit appartient obligatoirement a un utilisateur.
        produit = Produit.objects.create(
            owner=self.context["request"].user,
            status=StatutProduit.DRAFT,
            **validated_data,
        )
        Inventaire.objects.create(produit=produit, quantite_totale=quantite)
        return produit

    @transaction.atomic
    def update(self, instance, validated_data):
        donnees_inventaire = validated_data.pop("inventaire", None)

        # Regle 4 : modifier le prix n'affecte pas les ventes deja enregistrees,
        # chaque ligne de vente conservant son propre prix unitaire (module 9).
        for champ, valeur in validated_data.items():
            setattr(instance, champ, valeur)
        instance.save()

        if donnees_inventaire is not None:
            inventaire = instance.inventaire
            inventaire_serializer = InventaireSerializer(
                inventaire, data=donnees_inventaire, partial=True
            )
            inventaire_serializer.is_valid(raise_exception=True)
            inventaire_serializer.save()
            instance.refresh_from_db()

            # Regle 6 : un produit entierement vendu passe en OUT_OF_STOCK,
            # et redevient ACTIVE si du stock est reapprovisionne.
            from modules.products.services import ProduitStatutService

            ProduitStatutService.synchroniser_statut_stock(instance)

        return instance


class ProduitListeSerializer(serializers.ModelSerializer):
    """Vue allegee pour les listes (mes annonces, moderation)."""

    categorie_nom = serializers.CharField(source="categorie.nom", read_only=True)
    inventaire = InventaireLectureSerializer(read_only=True)
    quantite_disponible = serializers.IntegerField(read_only=True)
    image_principale = serializers.SerializerMethodField()
    owner_username = serializers.CharField(source="owner.username", read_only=True)

    class Meta:
        model = Produit
        fields = (
            "id", "titre", "slug", "prix", "devise", "etat", "status",
            "categorie", "categorie_nom", "owner", "owner_username",
            "localisation",
            "inventaire", "quantite_disponible", "image_principale",
            "est_mis_en_avant", "nombre_vues", "publie_le", "created_at",
        )
        read_only_fields = fields

    @extend_schema_field(ProduitImageSerializer)
    def get_image_principale(self, obj):
        image = next(
            (i for i in obj.images.all() if i.est_principale),
            next(iter(obj.images.all()), None),
        )
        return ProduitImageSerializer(image, context=self.context).data if image else None


class ProduitModerationSerializer(serializers.Serializer):
    """Decision de moderation (module 14, expose des le module 3)."""

    status = serializers.ChoiceField(
        choices=[
            StatutProduit.ACTIVE,
            StatutProduit.PENDING,
            StatutProduit.REMOVED,
            StatutProduit.PAUSED,
        ]
    )
    motif = serializers.CharField(max_length=255, required=False, allow_blank=True)
    est_mis_en_avant = serializers.BooleanField(required=False)

    def validate(self, attrs):
        if attrs["status"] == StatutProduit.REMOVED and not attrs.get("motif"):
            raise serializers.ValidationError(
                {"motif": "Un motif est obligatoire pour retirer une annonce."}
            )
        return attrs
