"""Serializers du module 12."""
from rest_framework import serializers

from modules.notifications.models import (
    AppareilPush,
    Notification,
    PlateformeAppareil,
)


class NotificationSerializer(serializers.ModelSerializer):
    """Une notification, telle que l'API et le WebSocket la renvoient.

    La forme est volontairement identique sur les deux canaux : le client
    Flutter traite un evenement temps reel exactement comme une ligne de
    l'historique.
    """

    type_libelle = serializers.CharField(
        source="get_type_notification_display", read_only=True
    )
    est_lue = serializers.BooleanField(read_only=True)

    class Meta:
        model = Notification
        fields = (
            "id", "type_notification", "type_libelle", "titre", "message",
            "reference_type", "reference_id", "donnees",
            "est_lue", "lu_le", "created_at",
        )
        read_only_fields = fields


class MarquageLectureSerializer(serializers.Serializer):
    """Entree de POST /notifications/read/."""

    identifiants = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        required=False,
        help_text=(
            "Notifications a marquer comme lues. Sans ce champ, TOUTES les "
            "notifications non lues sont marquees."
        ),
    )


class CompteurNonLuesSerializer(serializers.Serializer):
    """Sortie de GET /notifications/unread-count/."""

    non_lues = serializers.IntegerField()


class ResultatMarquageSerializer(serializers.Serializer):
    """Sortie de POST /notifications/read/."""

    success = serializers.BooleanField()
    message = serializers.CharField()
    marquees = serializers.IntegerField()
    non_lues = serializers.IntegerField()


class AppareilPushSerializer(serializers.ModelSerializer):
    """Appareil enregistre pour le push."""

    plateforme_libelle = serializers.CharField(
        source="get_plateforme_display", read_only=True
    )

    class Meta:
        model = AppareilPush
        fields = (
            "id", "jeton", "plateforme", "plateforme_libelle", "libelle",
            "actif", "derniere_utilisation", "created_at",
        )
        read_only_fields = (
            "id", "plateforme_libelle", "actif", "derniere_utilisation",
            "created_at",
        )


class AppareilPushCreationSerializer(serializers.Serializer):
    """Entree de POST /notifications/devices/."""

    jeton = serializers.CharField(
        max_length=255,
        help_text="Jeton fourni par le service push (FCM, APNs...).",
    )
    plateforme = serializers.ChoiceField(choices=PlateformeAppareil.choices)
    libelle = serializers.CharField(required=False, allow_blank=True, max_length=100)


class EtatPushSerializer(serializers.Serializer):
    """Sortie de GET /notifications/devices/status/."""

    push_configure = serializers.BooleanField(
        help_text=(
            "Faux si le serveur n'a aucune cle push : les notifications "
            "internes et le temps reel fonctionnent quand meme."
        )
    )
    appareils_actifs = serializers.IntegerField()
