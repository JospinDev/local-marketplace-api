"""Module 11 - Evaluations (/reviews/).

Securite basee sur la PROPRIETE, comme pour les reservations et les ventes :
le queryset contient les avis que l'utilisateur a ecrits ET ceux qu'il a
recus en tant que vendeur. Il peut donc lire les avis le concernant, mais
seul l'auteur modifie ou retire le sien.

La moderation vit sur `/admin/reviews/` et repose, elle, sur les permissions
de groupe (`reviews.view_evaluation`, `reviews.change_evaluation`).
"""
from django.db.models import Q
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from common.permissions import IsNotSuspended
from modules.reviews.filters import EvaluationFilter
from modules.reviews.models import Evaluation
from modules.reviews.serializers import (
    EvaluationCreationSerializer,
    EvaluationModificationSerializer,
    EvaluationSerializer,
    ReputationSerializer,
    SignalementCreationSerializer,
    SignalementEvaluationSerializer,
)
from modules.reviews.services import EvaluationService

TAG = "Evaluations"


@extend_schema_view(
    list=extend_schema(
        tags=[TAG],
        summary="Les avis qui me concernent",
        description=(
            "Avis que j'ai ecrits et avis recus sur mes ventes.\n\n"
            "Filtres : `statut`, `statut_in`, `signalees`, `auteur`, "
            "`vendeur`, `produit`, `produit_slug`, `titre` (icontains), "
            "`categorie`, `localisation` (icontains), `commentaire` "
            "(icontains), `avec_commentaire`, `note_produit`/`__gte`/`__lte`, "
            "`note_vendeur`/`__gte`/`__lte`, `vente`, `created_at_gte/_lte`."
        ),
    ),
    retrieve=extend_schema(tags=[TAG], summary="Detail d'un avis"),
)
class EvaluationViewSet(
    mixins.RetrieveModelMixin, mixins.ListModelMixin, viewsets.GenericViewSet
):
    """Deposer, consulter, corriger, retirer et signaler un avis."""

    permission_classes = [IsAuthenticated, IsNotSuspended]
    filterset_class = EvaluationFilter
    ordering_fields = ("created_at", "note_produit", "note_vendeur")
    ordering = ("-created_at",)

    serializer_classes = {
        "create": EvaluationCreationSerializer,
        "partial_update": EvaluationModificationSerializer,
        "signaler": SignalementCreationSerializer,
        "ma_reputation": ReputationSerializer,
    }

    def get_serializer_class(self):
        return self.serializer_classes.get(self.action, EvaluationSerializer)

    def get_queryset(self):
        utilisateur = self.request.user
        if not utilisateur.is_authenticated:
            return Evaluation.objects.none()
        return (
            Evaluation.objects.filter(
                Q(auteur=utilisateur) | Q(vendeur=utilisateur)
            )
            .complet()
            .distinct()
        )

    def _reponse(self, evaluation, message, code=status.HTTP_200_OK):
        evaluation = self.get_queryset().get(pk=evaluation.pk)
        return Response(
            {
                "success": True,
                "message": message,
                "evaluation": EvaluationSerializer(
                    evaluation, context=self.get_serializer_context()
                ).data,
            },
            status=code,
        )

    def _liste(self, queryset):
        queryset = self.filter_queryset(queryset)
        page = self.paginate_queryset(queryset)
        serializer = EvaluationSerializer(
            page if page is not None else queryset,
            many=True,
            context=self.get_serializer_context(),
        )
        if page is not None:
            return self.get_paginated_response(serializer.data)
        return Response(serializer.data)

    # ------------------------------------------------------------- creation
    @extend_schema(
        tags=[TAG],
        summary="Deposer un avis",
        responses={201: EvaluationSerializer},
        description=(
            "Deux notes de 1 a 5 : `note_produit` (qualite du produit) et "
            "`note_vendeur` (qualite du vendeur).\n\n"
            "L'avis doit porter sur une vente **terminee** : le vendeur a "
            "confirme le paiement et l'acheteur a confirme la reception. "
            "C'est ce qui empeche un vendeur de se fabriquer des notes avec "
            "de fausses ventes. Le produit et le vendeur sont deduits de la "
            "vente, et un acheteur ne peut evaluer qu'une fois la meme vente."
        ),
    )
    def create(self, request, *args, **kwargs):
        entree = EvaluationCreationSerializer(data=request.data)
        entree.is_valid(raise_exception=True)
        donnees = entree.validated_data

        evaluation = EvaluationService.creer(
            vente=donnees["vente"],
            auteur=request.user,
            note_produit=donnees["note_produit"],
            note_vendeur=donnees["note_vendeur"],
            commentaire=donnees.get("commentaire", ""),
        )
        return self._reponse(evaluation, "Merci, votre avis est publie.", status.HTTP_201_CREATED)

    # --------------------------------------------------------- modification
    @extend_schema(
        tags=[TAG],
        summary="Corriger mon avis",
        request=EvaluationModificationSerializer,
        responses={200: EvaluationSerializer},
        description=(
            "Reserve a l'auteur, dans le delai configure "
            "(`EVALUATION_DELAI_MODIFICATION_HEURES`, 48 h par defaut). "
            "Passe ce delai l'avis est definitif : une reputation ne doit pas "
            "pouvoir etre reecrite des mois plus tard, par exemple sous la "
            "pression du vendeur. Un avis masque par la moderation n'est plus "
            "modifiable."
        ),
    )
    def partial_update(self, request, *args, **kwargs):
        evaluation = self.get_object()
        entree = EvaluationModificationSerializer(data=request.data, partial=True)
        entree.is_valid(raise_exception=True)

        evaluation = EvaluationService.modifier(
            evaluation, request.user, entree.validated_data
        )
        return self._reponse(evaluation, "Avis mis a jour.")

    @extend_schema(
        tags=[TAG],
        summary="Retirer mon avis",
        responses={200: EvaluationSerializer},
        description=(
            "Suppression douce : l'avis sort des moyennes et des listes "
            "publiques mais reste en base. Effacer la ligne rendrait "
            "l'historique d'une reputation inverifiable, et permettrait de "
            "faire disparaitre un mauvais avis en obtenant son retrait."
        ),
    )
    def destroy(self, request, *args, **kwargs):
        evaluation = self.get_object()
        evaluation = EvaluationService.retirer(evaluation, request.user)
        return self._reponse(evaluation, "Avis retire.")

    # ---------------------------------------------------------------- listes
    @extend_schema(
        tags=[TAG],
        summary="Mes avis (ceux que j'ai ecrits)",
        responses={200: EvaluationSerializer(many=True)},
    )
    @action(detail=False, methods=["get"], url_path="my-reviews")
    def mes_avis(self, request):
        return self._liste(Evaluation.objects.de(request.user).complet())

    @extend_schema(
        tags=[TAG],
        summary="Avis recus sur mes ventes",
        responses={200: EvaluationSerializer(many=True)},
    )
    @action(detail=False, methods=["get"], url_path="received")
    def avis_recus(self, request):
        return self._liste(Evaluation.objects.recues_par(request.user).complet())

    @extend_schema(
        tags=[TAG],
        summary="Ma reputation de vendeur",
        responses={200: ReputationSerializer},
        description=(
            "Moyennes calculees sur mes avis **valides** uniquement : un avis "
            "masque par la moderation ou retire par son auteur n'entre dans "
            "aucune moyenne."
        ),
    )
    @action(detail=False, methods=["get"], url_path="my-rating")
    def ma_reputation(self, request):
        donnees = Evaluation.objects.recues_par(request.user).moyennes()
        return Response(ReputationSerializer(donnees).data)

    # --------------------------------------------------------------- actions
    @extend_schema(
        tags=[TAG],
        summary="Signaler un avis abusif",
        request=SignalementCreationSerializer,
        responses={201: SignalementEvaluationSerializer},
        description=(
            "Motifs : `INSULTE`, `FAUX`, `HORS_SUJET`, `SPAM`, `AUTRE`. "
            "Ouvert a tout utilisateur connecte, sauf a l'auteur de l'avis. "
            "Un meme avis ne peut etre signale qu'une fois par personne tant "
            "que la moderation n'a pas tranche."
        ),
    )
    @action(detail=True, methods=["post"], url_path="report")
    def signaler(self, request, pk=None):
        # Un signalement n'est pas reserve aux parties prenantes : un avis
        # insultant nuit a toute la plateforme, et n'importe qui peut le lire
        # sur la vitrine du vendeur. La recherche se fait donc sur les avis
        # publiquement visibles, pas sur le queryset restreint de la vue.
        evaluation = get_object_or_404(Evaluation.objects.valides(), pk=pk)
        entree = SignalementCreationSerializer(data=request.data)
        entree.is_valid(raise_exception=True)

        signalement = EvaluationService.signaler(
            evaluation,
            request.user,
            entree.validated_data["motif"],
            entree.validated_data.get("description", ""),
        )
        return Response(
            {
                "success": True,
                "message": "Avis signale : la moderation va l'examiner.",
                "signalement": SignalementEvaluationSerializer(signalement).data,
            },
            status=status.HTTP_201_CREATED,
        )
