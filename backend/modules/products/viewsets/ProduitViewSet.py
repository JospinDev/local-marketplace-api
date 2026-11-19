"""Module 3 - Gestion de ses propres annonces (/products/).

Acces : tout utilisateur authentifie et non suspendu peut vendre (le cahier
des charges prevoit un compte unique acheteur / vendeur). La protection
repose donc sur la PROPRIETE de l'objet, pas sur les permissions de groupe :
le queryset est restreint a `owner=request.user`, un vendeur ne peut donc ni
voir ni modifier les annonces d'un autre.

La moderation par groupe se fait sur `/admin/products/`
(voir ProduitAdminViewSet).
"""
from django.db.models import Prefetch
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from common.permissions import IsNotSuspended, IsOwner
from modules.products.filters import ProduitFilter
from modules.products.models import Produit, ProduitImage
from modules.products.serializers import (
    InventaireSerializer,
    ProduitImageAjoutSerializer,
    ProduitImageSerializer,
    ProduitListeSerializer,
    ProduitSerializer,
)
from modules.products.services import ProduitStatutService


@extend_schema_view(
    list=extend_schema(
        tags=["Vendeur - Mes annonces"],
        summary="Mes annonces",
        description=(
            "Retourne uniquement les annonces de l'utilisateur connecte, "
            "tous statuts confondus (brouillons inclus)."
        ),
    ),
    retrieve=extend_schema(tags=["Vendeur - Mes annonces"], summary="Detail de mon annonce"),
    create=extend_schema(
        tags=["Vendeur - Mes annonces"],
        summary="Publier un produit",
        description=(
            "L'annonce est creee en statut DRAFT. Le stock initial se declare "
            "via `inventaire.quantite_totale`. Utilisez ensuite "
            "`POST /products/{id}/publish/` pour la rendre visible."
        ),
    ),
    update=extend_schema(tags=["Vendeur - Mes annonces"], summary="Modifier mon annonce"),
    partial_update=extend_schema(
        tags=["Vendeur - Mes annonces"], summary="Modifier partiellement mon annonce"
    ),
    destroy=extend_schema(
        tags=["Vendeur - Mes annonces"],
        summary="Archiver mon annonce",
        description="Suppression douce : le statut passe a ARCHIVED.",
    ),
    mes_produits=extend_schema(tags=["Vendeur - Mes annonces"], summary="Mes annonces"),
    publier=extend_schema(tags=["Vendeur - Mes annonces"], summary="Publier l'annonce"),
    mettre_en_pause=extend_schema(
        tags=["Vendeur - Mes annonces"], summary="Suspendre temporairement l'annonce"
    ),
    stock=extend_schema(
        tags=["Vendeur - Mes annonces"],
        summary="Mettre a jour le stock total",
        description=(
            "Seule `quantite_totale` est modifiable. Les quantites reservee "
            "et vendue sont pilotees par les modules Reservations et Ventes."
        ),
    ),
    ajouter_images=extend_schema(
        tags=["Vendeur - Mes annonces"], summary="Ajouter des images"
    ),
    supprimer_image=extend_schema(
        tags=["Vendeur - Mes annonces"], summary="Supprimer une image"
    ),
)
class ProduitViewSet(viewsets.ModelViewSet):
    """CRUD de ses propres annonces."""

    permission_classes = [IsAuthenticated, IsNotSuspended, IsOwner]
    parser_classes = [JSONParser, MultiPartParser, FormParser]
    filterset_class = ProduitFilter
    search_fields = ("titre", "description")
    ordering_fields = ("created_at", "prix", "titre", "nombre_vues", "publie_le")
    ordering = ("-created_at",)
    owner_field = "owner"

    def get_queryset(self):
        """Isolation stricte : on ne voit que ses propres annonces."""
        utilisateur = self.request.user
        if not utilisateur.is_authenticated:
            return Produit.objects.none()
        return (
            Produit.objects.filter(owner=utilisateur)
            .select_related("categorie", "owner", "inventaire")
            .prefetch_related(
                Prefetch("images", queryset=ProduitImage.objects.all())
            )
        )

    def get_serializer_class(self):
        if self.action in ("list", "mes_produits"):
            return ProduitListeSerializer
        if self.action == "stock":
            return InventaireSerializer
        if self.action == "ajouter_images":
            return ProduitImageAjoutSerializer
        return ProduitSerializer

    def perform_destroy(self, instance):
        # Regle : on archive au lieu de supprimer, pour conserver
        # l'historique des reservations et des ventes.
        ProduitStatutService.archiver(instance)

    # ------------------------------------------------------------- actions
    @action(detail=False, methods=["get"], url_path="my-products")
    def mes_produits(self, request):
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        serializer = self.get_serializer(
            page if page is not None else queryset, many=True
        )
        if page is not None:
            return self.get_paginated_response(serializer.data)
        return Response(serializer.data)

    @action(detail=True, methods=["post"], url_path="publish")
    def publier(self, request, pk=None):
        produit = self.get_object()
        ProduitStatutService.publier(produit)
        return Response(
            {
                "success": True,
                "message": f"Annonce publiee avec le statut {produit.status}.",
                "produit": ProduitSerializer(
                    produit, context=self.get_serializer_context()
                ).data,
            },
            status=status.HTTP_200_OK,
        )

    @action(detail=True, methods=["post"], url_path="pause")
    def mettre_en_pause(self, request, pk=None):
        produit = self.get_object()
        ProduitStatutService.mettre_en_pause(produit)
        return Response(
            {
                "success": True,
                "message": "Annonce mise en pause.",
                "produit": ProduitSerializer(
                    produit, context=self.get_serializer_context()
                ).data,
            },
            status=status.HTTP_200_OK,
        )

    @action(detail=True, methods=["get", "patch"], url_path="stock")
    def stock(self, request, pk=None):
        produit = self.get_object()
        inventaire = produit.inventaire

        if request.method == "GET":
            return Response(InventaireSerializer(inventaire).data)

        serializer = InventaireSerializer(inventaire, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        produit.refresh_from_db()
        ProduitStatutService.synchroniser_statut_stock(produit)
        return Response(
            {
                "success": True,
                "message": "Stock mis a jour.",
                "status_annonce": produit.status,
                "inventaire": InventaireSerializer(produit.inventaire).data,
            },
            status=status.HTTP_200_OK,
        )

    @action(detail=True, methods=["post"], url_path="images")
    def ajouter_images(self, request, pk=None):
        produit = self.get_object()
        serializer = ProduitImageAjoutSerializer(
            data=request.data,
            context={**self.get_serializer_context(), "produit": produit},
        )
        serializer.is_valid(raise_exception=True)
        images = serializer.save()
        return Response(
            {
                "success": True,
                "message": f"{len(images)} image(s) ajoutee(s).",
                "images": ProduitImageSerializer(
                    produit.images.all(), many=True, context=self.get_serializer_context()
                ).data,
            },
            status=status.HTTP_201_CREATED,
        )

    @action(
        detail=True,
        methods=["delete"],
        url_path="images/(?P<image_id>[0-9]+)",
    )
    def supprimer_image(self, request, pk=None, image_id=None):
        produit = self.get_object()
        image = produit.images.filter(pk=image_id).first()
        if image is None:
            return Response(
                {"success": False, "message": "Image introuvable pour cette annonce."},
                status=status.HTTP_404_NOT_FOUND,
            )
        image.delete()
        # Si l'image principale a ete supprimee, la suivante prend le relais.
        if not produit.images.filter(est_principale=True).exists():
            suivante = produit.images.first()
            if suivante is not None:
                suivante.est_principale = True
                suivante.save(update_fields=["est_principale"])
        return Response(status=status.HTTP_204_NO_CONTENT)
