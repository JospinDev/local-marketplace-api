"""Module 5 - Vitrine publique d'un vendeur.

Aucune donnee privee : l'email n'est jamais expose, et le telephone
uniquement si le vendeur a coche `telephone_public`.
"""
from django.contrib.auth import get_user_model
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

User = get_user_model()


class VendeurListeSerializer(serializers.ModelSerializer):
    """Carte vendeur dans une liste."""

    nombre_produits_actifs = serializers.IntegerField(read_only=True, default=0)
    nombre_abonnes = serializers.IntegerField(read_only=True, default=0)
    est_suivi = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = (
            "id", "username", "nom_commercial", "nom_complet", "photo",
            "localisation", "nombre_produits_actifs", "nombre_abonnes",
            "est_suivi", "date_joined",
        )
        read_only_fields = fields

    @extend_schema_field(serializers.BooleanField)
    def get_est_suivi(self, obj) -> bool:
        """Vrai si l'utilisateur connecte suit ce vendeur."""
        request = self.context.get("request")
        if request is None or not request.user.is_authenticated:
            return False
        suivis = self.context.get("vendeurs_suivis")
        if suivis is not None:
            return obj.pk in suivis
        from modules.sellers.models import AbonnementVendeur

        return AbonnementVendeur.objects.filter(
            abonne=request.user, vendeur=obj
        ).exists()


class VendeurDetailSerializer(VendeurListeSerializer):
    """Profil public complet : description, statistiques, contact."""

    telephone = serializers.SerializerMethodField()
    nombre_produits_publies = serializers.IntegerField(read_only=True, default=0)
    nombre_produits_en_rupture = serializers.IntegerField(read_only=True, default=0)
    note_moyenne = serializers.SerializerMethodField()
    nombre_evaluations = serializers.SerializerMethodField()

    class Meta(VendeurListeSerializer.Meta):
        fields = VendeurListeSerializer.Meta.fields + (
            "description", "telephone", "nombre_produits_publies",
            "nombre_produits_en_rupture", "note_moyenne", "nombre_evaluations",
            "statut_compte",
        )
        read_only_fields = fields

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_telephone(self, obj):
        # Confidentialite : le vendeur decide d'afficher son numero ou non.
        return obj.telephone if obj.telephone_public else None

    def _reputation(self, obj) -> dict:
        """Notes du vendeur, annotees par la vue quand c'est possible.

        Le ViewSet public annote `note_moyenne_vendeur` et
        `nombre_evaluations_valides` en une seule requete. Le repli calcule
        la valeur a la demande, pour les appels qui construisent ce
        serializer sans passer par la vue.
        """
        annotee = getattr(obj, "note_moyenne_vendeur", "absent")
        if annotee != "absent":
            return {
                "note": round(annotee, 2) if annotee is not None else None,
                "nombre": getattr(obj, "nombre_evaluations_valides", 0) or 0,
            }

        from modules.reviews.models import Evaluation

        moyennes = Evaluation.objects.recues_par(obj).moyennes()
        return {
            "note": moyennes["note_vendeur"],
            "nombre": moyennes["nombre_evaluations"],
        }

    @extend_schema_field(serializers.FloatField(allow_null=True))
    def get_note_moyenne(self, obj):
        # Module 11 : moyenne des notes de vendeur, sur les avis valides.
        return self._reputation(obj)["note"]

    @extend_schema_field(serializers.IntegerField)
    def get_nombre_evaluations(self, obj) -> int:
        return self._reputation(obj)["nombre"]


class AbonnementSerializer(serializers.ModelSerializer):
    """Ligne de la liste "mes vendeurs suivis"."""

    vendeur = VendeurListeSerializer(read_only=True)

    class Meta:
        from modules.sellers.models import AbonnementVendeur

        model = AbonnementVendeur
        fields = ("id", "vendeur", "created_at")
        read_only_fields = fields
