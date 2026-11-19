"""Module 1 - Profil de l'utilisateur connecte (/me/).

ViewSet sans pk : l'objet manipule est toujours `request.user`.
"""
from django.contrib.auth import get_user_model
from django.utils import timezone
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from modules.accounts.serializers import UserSerializer

User = get_user_model()


@extend_schema_view(
    retrieve=extend_schema(tags=["Mon compte"], summary="Mon profil"),
    partial_update=extend_schema(tags=["Mon compte"], summary="Modifier mon profil"),
    update=extend_schema(tags=["Mon compte"], summary="Remplacer mon profil"),
    destroy=extend_schema(
        tags=["Mon compte"],
        summary="Demander la suppression de mon compte",
        description=(
            "Suppression douce : le compte est desactive et marque comme "
            "'suppression demandee'. Les annonces et ventes passees sont "
            "conservees pour l'historique."
        ),
    ),
    parametres=extend_schema(tags=["Mon compte"], summary="Mes parametres"),
)
class MeViewSet(
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """Lecture et mise a jour du compte de l'utilisateur authentifie."""

    serializer_class = UserSerializer
    permission_classes = [IsAuthenticated]
    queryset = User.objects.all()
    pagination_class = None

    def get_object(self):
        return self.request.user

    def perform_destroy(self, instance):
        from modules.accounts.models import StatutCompte

        instance.suppression_demandee_le = timezone.now()
        instance.statut_compte = StatutCompte.DESACTIVE
        instance.is_active = False
        instance.save(
            update_fields=[
                "suppression_demandee_le",
                "statut_compte",
                "is_active",
                "updated_at",
            ]
        )

    @action(detail=False, methods=["get"], url_path="settings")
    def parametres(self, request):
        utilisateur = request.user
        return Response(
            {
                "username": utilisateur.username,
                "email": utilisateur.email,
                "email_verifie": utilisateur.email_verifie,
                "telephone_public": utilisateur.telephone_public,
                "statut_compte": utilisateur.statut_compte,
                "groupes": list(utilisateur.groups.values_list("name", flat=True)),
                "permissions": sorted(utilisateur.get_all_permissions()),
                "langue": "fr",
                "devise": "BIF",
            },
            status=status.HTTP_200_OK,
        )
