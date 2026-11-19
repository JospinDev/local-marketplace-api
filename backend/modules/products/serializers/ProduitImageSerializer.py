"""Serializers des images d'annonce, avec validation stricte des fichiers."""
from rest_framework import serializers

from modules.products.models import ProduitImage

EXTENSIONS_AUTORISEES = ("jpg", "jpeg", "png", "webp")
TAILLE_MAX_MO = 5
NOMBRE_MAX_IMAGES = 10


class ProduitImageSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProduitImage
        fields = ("id", "image", "legende", "est_principale", "ordre", "created_at")
        read_only_fields = ("id", "created_at")

    def validate_image(self, fichier):
        nom = (fichier.name or "").lower()
        extension = nom.rsplit(".", 1)[-1] if "." in nom else ""
        if extension not in EXTENSIONS_AUTORISEES:
            raise serializers.ValidationError(
                "Format non autorise. Formats acceptes : "
                + ", ".join(EXTENSIONS_AUTORISEES)
            )
        if fichier.size > TAILLE_MAX_MO * 1024 * 1024:
            raise serializers.ValidationError(
                f"Image trop volumineuse (maximum {TAILLE_MAX_MO} Mo)."
            )
        return fichier


class ProduitImageAjoutSerializer(serializers.Serializer):
    """Ajout d'une ou plusieurs images a une annonce existante."""

    images = serializers.ListField(
        child=serializers.ImageField(),
        allow_empty=False,
        max_length=NOMBRE_MAX_IMAGES,
    )
    est_principale = serializers.BooleanField(
        required=False,
        default=False,
        help_text="Applique a la premiere image envoyee.",
    )

    def validate(self, attrs):
        produit = self.context["produit"]
        deja = produit.images.count()
        if deja + len(attrs["images"]) > NOMBRE_MAX_IMAGES:
            raise serializers.ValidationError(
                {
                    "images": (
                        f"Maximum {NOMBRE_MAX_IMAGES} images par annonce "
                        f"({deja} deja presente(s))."
                    )
                }
            )
        for fichier in attrs["images"]:
            ProduitImageSerializer().validate_image(fichier)
        return attrs

    def create(self, validated_data):
        produit = self.context["produit"]
        principale_demandee = validated_data.get("est_principale", False)
        depart = produit.images.count()
        creees = []
        for index, fichier in enumerate(validated_data["images"]):
            creees.append(
                ProduitImage.objects.create(
                    produit=produit,
                    image=fichier,
                    ordre=depart + index,
                    est_principale=principale_demandee and index == 0,
                )
            )
        return creees
