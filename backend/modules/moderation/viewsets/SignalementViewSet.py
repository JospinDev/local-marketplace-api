"""Module 14 - Gestion des signalements (/admin/reports/).

La plateforme a deux sortes de signalements, sur deux modeles distincts :
les conversations (module 7) et les avis (module 11). Ils ne sont PAS
fusionnes dans une liste unique, et c'est un choix : une fusion imposerait
soit une table polymorphe, soit un tri en memoire sur deux requetes, qui
tiendrait mal la montee en charge et mentirait sur la pagination.

L'API expose donc un resume commun, puis une liste par sorte :

    GET  /admin/reports/                        combien de chaque, en attente
    GET  /admin/reports/conversations/          liste paginee
    GET  /admin/reports/reviews/                liste paginee
    POST /admin/reports/conversations/{id}/resolve/
    POST /admin/reports/reviews/{id}/resolve/

Permissions, par sorte de signalement :

- conversations : `messaging.view_signalementconversation` pour lire,
  `messaging.change_signalementconversation` pour classer ;
- avis : `reviews.view_evaluation` pour lire,
  `reviews.change_evaluation` pour classer.
"""
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from common.permissions import StrictModelPermission
from modules.messaging.models import SignalementConversation
from modules.messaging.serializers import SignalementSerializer
from modules.moderation.serializers import ResumeSignalementsSerializer
from modules.moderation.services import AuditService
from modules.reviews.models import SignalementEvaluation
from modules.reviews.serializers import SignalementEvaluationSerializer

TAG = "Admin - Signalements"


@extend_schema_view(
    list=extend_schema(
        tags=[TAG],
        summary="Resume des signalements",
        responses={200: ResumeSignalementsSerializer},
        description=(
            "Combien de signalements attendent un traitement, par sorte. "
            "Exige `messaging.view_signalementconversation`."
        ),
    ),
)
class SignalementViewSet(viewsets.GenericViewSet):
    """File de moderation des signalements."""

    queryset = SignalementConversation.objects.none()
    serializer_class = ResumeSignalementsSerializer
    permission_classes = [IsAuthenticated, StrictModelPermission]

    #: Chaque action declare la permission qui correspond a son effet reel.
    #: Les chaines sans marqueur sont utilisees telles quelles, ce qui
    #: permet de viser une autre application que celle du queryset.
    action_permissions = {
        "list": ["messaging.view_signalementconversation"],
        "conversations": ["messaging.view_signalementconversation"],
        "resoudre_conversation": ["messaging.change_signalementconversation"],
        "avis": ["reviews.view_evaluation"],
        "resoudre_avis": ["reviews.change_evaluation"],
    }

    def _en_attente(self, demande) -> bool:
        """`?traites=true` bascule sur l'historique."""
        return demande.query_params.get("traites", "").lower() not in ("true", "1")

    def _liste(self, queryset, serializer_class):
        page = self.paginate_queryset(queryset)
        serializer = serializer_class(
            page if page is not None else queryset, many=True
        )
        if page is not None:
            return self.get_paginated_response(serializer.data)
        return Response(serializer.data)

    # ---------------------------------------------------------------- resume
    def list(self, request, *args, **kwargs):
        conversations = SignalementConversation.objects.all()
        avis = SignalementEvaluation.objects.all()
        return Response(
            ResumeSignalementsSerializer(
                {
                    "conversations_en_attente": conversations.filter(
                        traite_le__isnull=True
                    ).count(),
                    "avis_en_attente": avis.filter(traite_le__isnull=True).count(),
                    "conversations_traitees": conversations.filter(
                        traite_le__isnull=False
                    ).count(),
                    "avis_traites": avis.filter(traite_le__isnull=False).count(),
                }
            ).data
        )

    # -------------------------------------------------------- conversations
    @extend_schema(
        tags=[TAG],
        summary="Signalements de conversations",
        responses={200: SignalementSerializer(many=True)},
        description=(
            "Par defaut, uniquement ceux en attente ; `?traites=true` pour "
            "l'historique. Exige `messaging.view_signalementconversation`."
        ),
    )
    @action(detail=False, methods=["get"], url_path="conversations")
    def conversations(self, request):
        queryset = SignalementConversation.objects.select_related(
            "conversation", "signale_par"
        ).order_by("-created_at")
        if self._en_attente(request):
            queryset = queryset.filter(traite_le__isnull=True)
        return self._liste(queryset, SignalementSerializer)

    @extend_schema(
        tags=[TAG],
        summary="Classer un signalement de conversation",
        request=None,
        responses={200: SignalementSerializer},
        description=(
            "Marque le signalement comme traite, ce qui le sort de la file "
            "et autorise un nouveau signalement de la meme conversation. "
            "La decision est inscrite au journal d'audit. Exige "
            "`messaging.change_signalementconversation`."
        ),
    )
    @action(
        detail=False,
        methods=["post"],
        url_path=r"conversations/(?P<identifiant>\d+)/resolve",
    )
    def resoudre_conversation(self, request, identifiant=None):
        signalement = get_object_or_404(
            SignalementConversation, pk=identifiant
        )
        if signalement.traite_le is None:
            signalement.traite_le = timezone.now()
            signalement.save(update_fields=["traite_le", "updated_at"])
            AuditService.traitement_signalement(
                request.user, signalement, "conversation", requete=request
            )
        return Response(
            {
                "success": True,
                "message": "Signalement classe.",
                "signalement": SignalementSerializer(signalement).data,
            }
        )

    # ------------------------------------------------------------------ avis
    @extend_schema(
        tags=[TAG],
        summary="Signalements d'avis",
        responses={200: SignalementEvaluationSerializer(many=True)},
        description=(
            "Par defaut, uniquement ceux en attente ; `?traites=true` pour "
            "l'historique. Exige `reviews.view_evaluation`.\n\n"
            "Pour agir sur l'avis lui-meme, utilisez "
            "`/admin/reviews/{id}/moderate/`, qui classe aussi les "
            "signalements en attente."
        ),
    )
    @action(detail=False, methods=["get"], url_path="reviews")
    def avis(self, request):
        queryset = SignalementEvaluation.objects.select_related(
            "evaluation", "signale_par"
        ).order_by("-created_at")
        if self._en_attente(request):
            queryset = queryset.filter(traite_le__isnull=True)
        return self._liste(queryset, SignalementEvaluationSerializer)

    @extend_schema(
        tags=[TAG],
        summary="Classer un signalement d'avis",
        request=None,
        responses={200: SignalementEvaluationSerializer},
        description=(
            "Classe le signalement sans toucher a l'avis : a utiliser quand "
            "le signalement est infonde. Exige `reviews.change_evaluation`."
        ),
    )
    @action(
        detail=False,
        methods=["post"],
        url_path=r"reviews/(?P<identifiant>\d+)/resolve",
    )
    def resoudre_avis(self, request, identifiant=None):
        signalement = get_object_or_404(SignalementEvaluation, pk=identifiant)
        if signalement.traite_le is None:
            signalement.traite_le = timezone.now()
            signalement.save(update_fields=["traite_le", "updated_at"])
            AuditService.traitement_signalement(
                request.user, signalement, "avis", requete=request
            )
        return Response(
            {
                "success": True,
                "message": "Signalement classe.",
                "signalement": SignalementEvaluationSerializer(signalement).data,
            }
        )
