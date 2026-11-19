"""Module 3 / 14 - Moderation des annonces (/admin/products/).

Acces pilote UNIQUEMENT par les permissions Django des groupes :

- `products.view_produit`   -> GET (liste et detail de toutes les annonces)
- `products.change_produit` -> PATCH, PUT et l'action `moderate`
- `products.delete_produit` -> DELETE

Un modérateur dont le groupe ne contient que `view_produit` peut consulter
les annonces signalees mais recoit 403 s'il tente de les modifier ou de les
retirer.
"""
from django.db.models import Prefetch
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from common.permissions import StrictModelPermission
from modules.products.filters import ProduitFilter
from modules.products.models import Produit, ProduitImage, StatutProduit
from modules.products.serializers import (
    ProduitListeSerializer,
    ProduitModerationSerializer,
    ProduitSerializer,
)


@extend_schema_view(
    list=extend_schema(
        tags=["Admin - Annonces"],
        summary="Toutes les annonces",
        description="Exige `products.view_produit`.",
    ),
    retrieve=extend_schema(
        tags=["Admin - Annonces"],
        summary="Detail d'une annonce",
        description="Exige `products.view_produit`.",
    ),
    partial_update=extend_schema(
        tags=["Admin - Annonces"],
        summary="Corriger une annonce",
        description="Exige `products.change_produit`.",
    ),
    update=extend_schema(
        tags=["Admin - Annonces"],
        summary="Remplacer une annonce",
        description="Exige `products.change_produit`.",
    ),
    destroy=extend_schema(
        tags=["Admin - Annonces"],
        summary="Supprimer definitivement une annonce",
        description="Exige `products.delete_produit`.",
    ),
    moderer=extend_schema(
        tags=["Admin - Annonces"],
        summary="Moderer une annonce",
        description=(
            "Change le statut (ACTIVE, PENDING, PAUSED, REMOVED) et enregistre "
            "un motif. Exige `products.change_produit`. Un motif est "
            "obligatoire pour retirer une annonce."
        ),
    ),
)
class ProduitAdminViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """Supervision du catalogue par l'administration et la moderation."""

    queryset = (
        Produit.objects.all()
        .select_related("categorie", "owner", "inventaire")
        .prefetch_related(Prefetch("images", queryset=ProduitImage.objects.all()))
    )
    permission_classes = [IsAuthenticated, StrictModelPermission]
    filterset_class = ProduitFilter
    search_fields = ("titre", "description", "owner__username")
    ordering_fields = ("created_at", "prix", "nombre_vues", "status")
    ordering = ("-created_at",)

    # L'action `moderate` est un POST, mais son effet est une modification :
    # elle exige donc `change_produit` et non `add_produit`.
    action_permissions = {
        "moderer": ["%(app_label)s.change_%(model_name)s"],
    }

    def perform_destroy(self, instance):
        """Une suppression d'annonce par l'administration laisse une trace."""
        from modules.moderation.services import AuditService

        AuditService.suppression_annonce(self.request.user, instance, self.request)
        instance.delete()

    def get_serializer_class(self):
        if self.action == "list":
            return ProduitListeSerializer
        if self.action == "moderer":
            return ProduitModerationSerializer
        return ProduitSerializer

    @action(detail=True, methods=["post"], url_path="moderate")
    def moderer(self, request, pk=None):
        produit = self.get_object()
        serializer = ProduitModerationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        donnees = serializer.validated_data
        statut_avant = produit.status

        produit.status = donnees["status"]
        produit.motif_moderation = donnees.get("motif", "")
        champs = ["status", "motif_moderation", "updated_at"]

        if "est_mis_en_avant" in donnees:
            produit.est_mis_en_avant = donnees["est_mis_en_avant"]
            champs.append("est_mis_en_avant")

        produit.save(update_fields=champs)

        # Une annonce remise en ligne sans stock disponible doit refleter
        # la rupture plutot que d'annoncer une disponibilite inexistante.
        if (
            produit.status == StatutProduit.ACTIVE
            and produit.quantite_disponible == 0
        ):
            produit.status = StatutProduit.OUT_OF_STOCK
            produit.save(update_fields=["status", "updated_at"])

        # Modules 14 et 12 : trace d'audit et information du vendeur.
        from modules.moderation.services import AuditService
        from modules.notifications.services import NotificationService

        motif = donnees.get("motif", "")
        AuditService.moderation_annonce(
            request.user, produit, statut_avant, motif, request
        )
        NotificationService.annonce_moderee(produit, motif)

        return Response(
            {
                "success": True,
                "message": f"Annonce moderee : statut {produit.status}.",
                "produit": ProduitSerializer(
                    produit, context=self.get_serializer_context()
                ).data,
            },
            status=status.HTTP_200_OK,
        )
