"""Module 1 - Administration des comptes (/admin/users/).

Acces pilote UNIQUEMENT par les permissions Django des groupes :

- `accounts.view_user`   -> GET (liste et detail)
- `accounts.add_user`    -> POST
- `accounts.change_user` -> PUT, PATCH, et les actions suspendre / activer
- `accounts.delete_user` -> DELETE

Un membre du groupe "Moderateur" qui ne possede que `view_user` peut donc
consulter les comptes mais recoit 403 sur toute tentative de creation,
modification ou suppression.
"""
from django.contrib.auth import get_user_model
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from common.permissions import StrictModelPermission
from modules.accounts.filters import UserFilter
from modules.accounts.serializers import SuspensionSerializer, UserAdminSerializer

User = get_user_model()


@extend_schema_view(
    list=extend_schema(tags=["Admin - Utilisateurs"], summary="Liste des comptes"),
    retrieve=extend_schema(tags=["Admin - Utilisateurs"], summary="Detail d'un compte"),
    create=extend_schema(tags=["Admin - Utilisateurs"], summary="Creer un compte"),
    update=extend_schema(tags=["Admin - Utilisateurs"], summary="Modifier un compte"),
    partial_update=extend_schema(
        tags=["Admin - Utilisateurs"], summary="Modifier partiellement un compte"
    ),
    destroy=extend_schema(tags=["Admin - Utilisateurs"], summary="Supprimer un compte"),
    suspendre=extend_schema(
        tags=["Admin - Utilisateurs"],
        summary="Suspendre un compte",
        description="Exige la permission `accounts.change_user`.",
    ),
    activer=extend_schema(
        tags=["Admin - Utilisateurs"],
        summary="Reactiver un compte",
        description="Exige la permission `accounts.change_user`.",
    ),
)
class UserAdminViewSet(viewsets.ModelViewSet):
    """CRUD des comptes, strictement borne par les permissions du groupe."""

    queryset = User.objects.all().prefetch_related("groups")
    serializer_class = UserAdminSerializer
    permission_classes = [IsAuthenticated, StrictModelPermission]
    filterset_class = UserFilter
    search_fields = ("username", "nom_complet", "nom_commercial", "email", "telephone")
    ordering_fields = ("date_joined", "username", "statut_compte")
    ordering = ("-date_joined",)

    # Les actions personnalisees (POST) ne doivent pas exiger `add_user`
    # mais la permission qui correspond reellement a leur effet.
    action_permissions = {
        "suspendre": ["%(app_label)s.change_%(model_name)s"],
        "activer": ["%(app_label)s.change_%(model_name)s"],
    }

    def get_serializer_class(self):
        if self.action in ("suspendre", "activer"):
            return SuspensionSerializer
        return super().get_serializer_class()

    @action(detail=True, methods=["post"], url_path="suspend")
    def suspendre(self, request, pk=None):
        utilisateur = self.get_object()
        serializer = SuspensionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        motif = serializer.validated_data.get("motif", "")
        utilisateur.suspendre(motif)

        # Modules 14 et 12 : la decision est tracee, et l'interesse
        # est prevenu. Imports locaux : ces modules dependent des
        # comptes, un import global ferait un cycle.
        from modules.moderation.services import AuditService
        from modules.notifications.services import NotificationService

        AuditService.suspension(request.user, utilisateur, motif, request)
        NotificationService.compte_suspendu(utilisateur, motif)
        return Response(
            {
                "success": True,
                "message": f"Le compte {utilisateur.username} est suspendu.",
                "utilisateur": UserAdminSerializer(
                    utilisateur, context=self.get_serializer_context()
                ).data,
            },
            status=status.HTTP_200_OK,
        )

    @action(detail=True, methods=["post"], url_path="activate")
    def activer(self, request, pk=None):
        utilisateur = self.get_object()
        utilisateur.reactiver()

        from modules.moderation.services import AuditService
        from modules.notifications.services import NotificationService

        AuditService.reactivation(request.user, utilisateur, request)
        NotificationService.compte_reactive(utilisateur)
        return Response(
            {
                "success": True,
                "message": f"Le compte {utilisateur.username} est reactive.",
                "utilisateur": UserAdminSerializer(
                    utilisateur, context=self.get_serializer_context()
                ).data,
            },
            status=status.HTTP_200_OK,
        )
