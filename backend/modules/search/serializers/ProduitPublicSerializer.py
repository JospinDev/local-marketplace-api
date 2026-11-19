"""Module 4 - Representations publiques des annonces.

Aucune donnee privee n'est exposee : ni email, ni telephone du vendeur
lorsqu'il ne l'autorise pas, ni adresse exacte.
"""
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from modules.products.models import Produit
from modules.products.serializers import ProduitImageSerializer
from modules.reviews.serializers import ReputationSerializer


class VendeurResumeSerializer(serializers.Serializer):
    """Encart vendeur affiche sur une annonce (module 5 l'enrichira)."""

    id = serializers.IntegerField(read_only=True)
    username = serializers.CharField(read_only=True)
    nom_commercial = serializers.CharField(read_only=True)
    photo = serializers.ImageField(read_only=True)
    localisation = serializers.CharField(read_only=True)
    telephone = serializers.SerializerMethodField()
    membre_depuis = serializers.DateTimeField(source="date_joined", read_only=True)

    def get_telephone(self, obj) -> str | None:
        # Confidentialite : visible seulement si le vendeur l'a autorise.
        return obj.telephone if obj.telephone_public else None


class ProduitPublicListeSerializer(serializers.ModelSerializer):
    """Carte produit : listes, recherche, mises en avant."""

    categorie_nom = serializers.CharField(source="categorie.nom", read_only=True)
    quantite_disponible = serializers.IntegerField(read_only=True)
    image_principale = serializers.SerializerMethodField()
    vendeur_username = serializers.CharField(source="owner.username", read_only=True)
    distance_km = serializers.SerializerMethodField()

    class Meta:
        model = Produit
        fields = (
            "id", "titre", "slug", "prix", "devise", "etat", "status",
            "categorie", "categorie_nom",
            "localisation", "latitude", "longitude", "distance_km",
            "quantite_disponible", "image_principale",
            "vendeur_username", "est_mis_en_avant", "nombre_vues",
            "publie_le", "created_at",
        )
        read_only_fields = fields

    @extend_schema_field(ProduitImageSerializer)
    def get_image_principale(self, obj):
        image = next(
            (i for i in obj.images.all() if i.est_principale),
            next(iter(obj.images.all()), None),
        )
        return ProduitImageSerializer(image, context=self.context).data if image else None

    @extend_schema_field(serializers.FloatField(allow_null=True))
    def get_distance_km(self, obj):
        distance = getattr(obj, "distance_km", None)
        return round(float(distance), 2) if distance is not None else None


class ProduitPublicDetailSerializer(ProduitPublicListeSerializer):
    """Fiche produit complete pour le visiteur."""

    images = ProduitImageSerializer(many=True, read_only=True)
    vendeur = VendeurResumeSerializer(source="owner", read_only=True)
    categorie_chemin = serializers.CharField(
        source="categorie.chemin_complet", read_only=True
    )
    reputation = serializers.SerializerMethodField()

    class Meta(ProduitPublicListeSerializer.Meta):
        fields = ProduitPublicListeSerializer.Meta.fields + (
            "description", "categorie_chemin", "images", "vendeur",
            "reputation", "updated_at",
        )
        read_only_fields = fields

    @extend_schema_field(ReputationSerializer)
    def get_reputation(self, obj):
        """Notes du produit (module 11), sur les avis valides uniquement.

        Une seule requete : ce serializer ne sert qu'a une fiche a la fois.
        La liste du catalogue, elle, reste volontairement sans note pour ne
        pas payer une agregation par carte affichee ; le detail des avis est
        sur `/public/products/{id}/reviews/`.
        """
        from modules.reviews.models import Evaluation

        return ReputationSerializer(Evaluation.objects.du_produit(obj).moyennes()).data
