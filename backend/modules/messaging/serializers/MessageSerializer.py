"""Serializers des messages, avec validation stricte des photos envoyees."""
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from modules.messaging.models import Message

EXTENSIONS_AUTORISEES = ("jpg", "jpeg", "png", "webp")
TAILLE_MAX_MO = 5
LONGUEUR_MAX_CONTENU = 5000


class MessageSerializer(serializers.ModelSerializer):
    """Message tel qu'il est restitue dans l'historique."""

    expediteur_username = serializers.CharField(
        source="expediteur.username", read_only=True
    )
    est_lu = serializers.BooleanField(read_only=True)
    est_de_moi = serializers.SerializerMethodField()

    class Meta:
        model = Message
        fields = (
            "id", "conversation", "expediteur", "expediteur_username",
            "contenu", "image", "est_lu", "lu_le", "est_de_moi", "created_at",
        )
        read_only_fields = fields

    @extend_schema_field(serializers.BooleanField)
    def get_est_de_moi(self, obj) -> bool:
        request = self.context.get("request")
        if request is None or not request.user.is_authenticated:
            return False
        return obj.expediteur_id == request.user.pk


class MessageEnvoiSerializer(serializers.Serializer):
    """Envoi d'un message : texte, image, ou les deux."""

    contenu = serializers.CharField(
        required=False, allow_blank=True, max_length=LONGUEUR_MAX_CONTENU
    )
    image = serializers.ImageField(required=False, allow_null=True)

    def validate_image(self, fichier):
        if fichier is None:
            return None
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

    def validate(self, attrs):
        contenu = (attrs.get("contenu") or "").strip()
        if not contenu and not attrs.get("image"):
            raise serializers.ValidationError(
                {"contenu": "Un message doit contenir du texte ou une image."}
            )
        attrs["contenu"] = contenu
        return attrs
