"""Module 11 - Moderation des avis (/admin/reviews/).

Contrairement aux endpoints prives, la protection repose ici sur les
PERMISSIONS DE GROUPE, avec la regle stricte du projet : un groupe ne peut
faire que ce que ses permissions autorisent.

- lister les avis et les signalements exige `reviews.view_evaluation` ;
- masquer ou reafficher un avis exige `reviews.change_evaluation`.

Un groupe qui ne contient que `view_evaluation` peut donc consulter les
signalements mais recoit 403 sur `/moderate/`.
"""
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from common.permissions import StrictModelPermission
from modules.reviews.filters import EvaluationFilter
from modules.reviews.models import Evaluation, SignalementEvaluation
from modules.reviews.serializers import (
    EvaluationSerializer,
    ModerationEvaluationSerializer,
    SignalementEvaluationSerializer,
)
from modules.reviews.services import EvaluationService

TAG = "Admin - Evaluations"


@extend_schema_view(
    list=extend_schema(
        tags=[TAG],
        summary="Tous les avis (moderation)",
        description=(
            "Exige `reviews.view_evaluation`. Filtres utiles pour la "
            "moderation : `signalees=true`, `statut`, `note_vendeur__lte=2`, "
            "`commentaire` (icontains), `vendeur_username`, "
            "`created_at_gte`."
        ),
    ),
    retrieve=extend_schema(tags=[TAG], summary="Detail d'un avis (moderation)"),
)
class EvaluationModerationViewSet(
    mixins.RetrieveModelMixin, mixins.ListModelMixin, viewsets.GenericViewSet
):
    """Consultation et moderation des avis par les groupes autorises."""

    queryset = Evaluation.objects.all()
    serializer_class = EvaluationSerializer
    permission_classes = [IsAuthenticated, StrictModelPermission]
    filterset_class = EvaluationFilter
    ordering_fields = ("created_at", "note_produit", "note_vendeur", "statut")
    ordering = ("-created_at",)

    #: `moderate` est un POST, mais son effet reel est une MODIFICATION :
    #: il doit donc exiger `change_evaluation` et non `add_evaluation`.
    action_permissions = {
        "moderer": ["%(app_label)s.change_%(model_name)s"],
        "signalements": ["%(app_label)s.view_%(model_name)s"],
    }

    def get_queryset(self):
        return Evaluation.objects.all().complet()

    @extend_schema(
        tags=[TAG],
        summary="Masquer ou reafficher un avis",
        request=ModerationEvaluationSerializer,
        responses={200: EvaluationSerializer},
        description=(
            "Exige `reviews.change_evaluation`.\n\n"
            "`MASQUEE` retire l'avis des moyennes et des listes publiques "
            "sans l'effacer ; `VISIBLE` le remet. Les signalements en "
            "attente sur cet avis sont marques comme traites, et le motif "
            "est conserve : une decision de moderation doit rester "
            "explicable."
        ),
    )
    @action(detail=True, methods=["post"], url_path="moderate")
    def moderer(self, request, pk=None):
        evaluation = self.get_object()
        entree = ModerationEvaluationSerializer(data=request.data)
        entree.is_valid(raise_exception=True)
        statut_avant = evaluation.statut

        evaluation = EvaluationService.moderer(
            evaluation,
            request.user,
            entree.validated_data["statut"],
            entree.validated_data.get("motif", ""),
        )

        # Modules 14 et 12 : trace d'audit, et l'auteur est prevenu.
        from modules.moderation.services import AuditService
        from modules.notifications.services import NotificationService

        motif = entree.validated_data.get("motif", "")
        AuditService.moderation_avis(
            request.user, evaluation, statut_avant, motif, request
        )
        NotificationService.avis_modere(evaluation, motif)

        return Response(
            {
                "success": True,
                "message": f"Avis passe en {evaluation.statut}.",
                "evaluation": EvaluationSerializer(
                    evaluation, context=self.get_serializer_context()
                ).data,
            }
        )

    @extend_schema(
        tags=[TAG],
        summary="Signalements en attente",
        responses={200: SignalementEvaluationSerializer(many=True)},
        description=(
            "Exige `reviews.view_evaluation`. Par defaut, uniquement les "
            "signalements non traites ; ajoutez `?tous=true` pour l'historique."
        ),
    )
    @action(detail=False, methods=["get"], url_path="reports")
    def signalements(self, request):
        queryset = SignalementEvaluation.objects.select_related(
            "evaluation", "signale_par"
        )
        if request.query_params.get("tous", "").lower() not in ("true", "1"):
            queryset = queryset.filter(traite_le__isnull=True)

        page = self.paginate_queryset(queryset)
        serializer = SignalementEvaluationSerializer(
            page if page is not None else queryset, many=True
        )
        if page is not None:
            return self.get_paginated_response(serializer.data)
        return Response(serializer.data)
