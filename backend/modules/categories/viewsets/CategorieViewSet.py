"""Module 2 - Gestion des categories (administration / moderation).

Permissions STRICTEMENT issues des groupes Django :

- `categories.view_categorie`   -> GET liste et detail
- `categories.add_categorie`    -> POST
- `categories.change_categorie` -> PUT, PATCH, actions activer / desactiver
- `categories.delete_categorie` -> DELETE

Un utilisateur dont le groupe ne contient que `add_categorie` peut uniquement
creer une categorie ; toute autre operation renvoie 403.
"""
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from common.permissions import StrictModelPermission
from modules.categories.filters import CategorieFilter
from modules.categories.models import Categorie
from modules.categories.serializers import CategorieSerializer


@extend_schema_view(
    list=extend_schema(
        tags=["Admin - Categories"],
        summary="Liste des categories",
        description="Exige `categories.view_categorie`.",
    ),
    retrieve=extend_schema(
        tags=["Admin - Categories"],
        summary="Detail d'une categorie",
        description="Exige `categories.view_categorie`.",
    ),
    create=extend_schema(
        tags=["Admin - Categories"],
        summary="Creer une categorie",
        description="Exige `categories.add_categorie`.",
    ),
    update=extend_schema(
        tags=["Admin - Categories"],
        summary="Modifier une categorie",
        description="Exige `categories.change_categorie`.",
    ),
    partial_update=extend_schema(
        tags=["Admin - Categories"],
        summary="Modifier partiellement une categorie",
        description="Exige `categories.change_categorie`.",
    ),
    destroy=extend_schema(
        tags=["Admin - Categories"],
        summary="Supprimer une categorie",
        description="Exige `categories.delete_categorie`.",
    ),
    desactiver=extend_schema(
        tags=["Admin - Categories"],
        summary="Desactiver une categorie",
        description="Exige `categories.change_categorie` (et non add).",
    ),
    activer=extend_schema(
        tags=["Admin - Categories"],
        summary="Activer une categorie",
        description="Exige `categories.change_categorie`.",
    ),
)
class CategorieViewSet(viewsets.ModelViewSet):
    """CRUD complet, borne par les permissions du groupe de l'utilisateur."""

    queryset = (
        Categorie.objects.all()
        .select_related("parent")
        .prefetch_related("sous_categories")
    )
    serializer_class = CategorieSerializer
    permission_classes = [IsAuthenticated, StrictModelPermission]
    filterset_class = CategorieFilter
    search_fields = ("nom", "description", "slug")
    ordering_fields = ("ordre", "nom", "created_at", "updated_at")
    ordering = ("ordre", "nom")

    # Les actions POST personnalisees exigent la permission de leur effet reel.
    action_permissions = {
        "desactiver": ["%(app_label)s.change_%(model_name)s"],
        "activer": ["%(app_label)s.change_%(model_name)s"],
    }

    def perform_update(self, serializer):
        """Module 14 : les modifications de categories sont tracees."""
        etat_avant = {
            "nom": serializer.instance.nom,
            "is_active": serializer.instance.is_active,
        }
        categorie = serializer.save()
        self._tracer(categorie, etat_avant)

    def perform_destroy(self, instance):
        # Une categorie parente est supprimee avec ses sous-categories
        # (CASCADE) : on previent l'appelant via la reponse du ViewSet.
        self._tracer(instance, {"nom": instance.nom, "existe": True}, supprimee=True)
        instance.delete()

    def _tracer(self, categorie, etat_avant, supprimee=False):
        from modules.moderation.models import ActionAudit
        from modules.moderation.services import AuditService

        AuditService.tracer(
            self.request.user,
            ActionAudit.MODIFICATION_CATEGORIE,
            cible=categorie,
            cible_type="categorie",
            cible_libelle=categorie.nom,
            avant=etat_avant,
            apres=(
                {"existe": False}
                if supprimee
                else {"nom": categorie.nom, "is_active": categorie.is_active}
            ),
            requete=self.request,
        )

    @action(detail=True, methods=["post"], url_path="deactivate")
    def desactiver(self, request, pk=None):
        categorie = self.get_object()
        categorie.is_active = False
        categorie.save(update_fields=["is_active", "updated_at"])
        # Une categorie desactivee masque aussi ses sous-categories.
        categorie.sous_categories.update(is_active=False)
        return Response(
            {
                "success": True,
                "message": f"Categorie '{categorie.nom}' desactivee.",
                "categorie": self.get_serializer(categorie).data,
            },
            status=status.HTTP_200_OK,
        )

    @action(detail=True, methods=["post"], url_path="activate")
    def activer(self, request, pk=None):
        categorie = self.get_object()
        categorie.is_active = True
        categorie.save(update_fields=["is_active", "updated_at"])
        return Response(
            {
                "success": True,
                "message": f"Categorie '{categorie.nom}' activee.",
                "categorie": self.get_serializer(categorie).data,
            },
            status=status.HTTP_200_OK,
        )
