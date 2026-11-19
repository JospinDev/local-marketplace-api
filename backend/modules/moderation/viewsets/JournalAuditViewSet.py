"""Module 14 - Journal d'audit (/admin/audit-logs/).

Strictement en LECTURE : il n'y a ni creation, ni modification, ni
suppression, et ce n'est pas un oubli. Un journal d'audit que l'on peut
retoucher ne vaut rien en cas de litige ; les entrees sont ecrites par
`AuditService`, appele depuis les actions d'administration elles-memes.

Exige `moderation.view_journalaudit`.
"""
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from common.permissions import StrictModelPermission
from modules.moderation.filters import JournalAuditFilter
from modules.moderation.models import JournalAudit
from modules.moderation.serializers import (
    ActionAuditSerializer,
    JournalAuditSerializer,
)

TAG = "Admin - Audit"


@extend_schema_view(
    list=extend_schema(
        tags=[TAG],
        summary="Journal d'audit",
        description=(
            "Qui a fait quoi, sur quoi, quand et pourquoi. Exige "
            "`moderation.view_journalaudit`.\n\n"
            "Chaque entree porte l'etat `avant` et `apres` dans `donnees`, "
            "ce qui permet de comprendre une decision des mois plus tard.\n\n"
            "Filtres : `action`, `action_in`, `acteur`, `acteur_username` "
            "(icontains), `cible_type`, `cible_id`, `cible_libelle` "
            "(icontains), `motif` (icontains), `adresse_ip`, "
            "`created_at_gte`, `created_at_lte`, `ordering=created_at`."
        ),
    ),
    retrieve=extend_schema(tags=[TAG], summary="Detail d'une entree"),
)
class JournalAuditViewSet(
    mixins.RetrieveModelMixin, mixins.ListModelMixin, viewsets.GenericViewSet
):
    """Consultation du journal d'audit."""

    queryset = JournalAudit.objects.all()
    serializer_class = JournalAuditSerializer
    permission_classes = [IsAuthenticated, StrictModelPermission]
    filterset_class = JournalAuditFilter
    search_fields = ("acteur_username", "cible_libelle", "motif")
    ordering_fields = ("created_at", "action", "acteur_username")
    ordering = ("-created_at",)

    def get_queryset(self):
        return JournalAudit.objects.all().complet()

    @extend_schema(
        tags=[TAG],
        summary="Actions tracables",
        responses={200: ActionAuditSerializer(many=True)},
        description=(
            "Liste des valeurs possibles du champ `action`, pour construire "
            "un filtre cote client sans les coder en dur."
        ),
    )
    @action(detail=False, methods=["get"], url_path="actions")
    def actions_possibles(self, request):
        return Response(ActionAuditSerializer(ActionAuditSerializer.toutes(), many=True).data)
