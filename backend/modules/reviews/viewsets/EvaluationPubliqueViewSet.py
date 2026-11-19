"""Module 11 - Avis publics d'un produit (/public/products/{id}/reviews/).

Ouvert aux visiteurs, sans authentification : la reputation est justement
faite pour etre consultee avant d'acheter. Seuls les avis VALIDES sont
exposes, et la representation publique ne divulgue ni l'identifiant de la
vente ni les informations de moderation.
"""
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import mixins, viewsets
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from modules.products.models import Produit
from modules.reviews.filters import EvaluationFilter
from modules.reviews.models import Evaluation
from modules.reviews.serializers import (
    EvaluationPubliqueSerializer,
    ReputationSerializer,
)

TAG = "Public - Evaluations"


@extend_schema_view(
    list=extend_schema(
        tags=[TAG],
        summary="Avis sur un produit",
        parameters=[],
        description=(
            "Avis valides portant sur cette annonce, du plus recent au plus "
            "ancien. La note moyenne du produit et celle du vendeur sont "
            "renvoyees dans `reputation`.\n\n"
            "Filtres : `note_produit`/`__gte`/`__lte`, `note_vendeur`, "
            "`avec_commentaire=true`, `created_at_gte`, `created_at_lte`, "
            "`ordering=-created_at`, `-note_produit`."
        ),
        responses={200: EvaluationPubliqueSerializer(many=True)},
    ),
)
class EvaluationProduitPubliqueViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    """Avis d'un produit, visibles par tous."""

    permission_classes = [AllowAny]
    serializer_class = EvaluationPubliqueSerializer
    filterset_class = EvaluationFilter
    ordering_fields = ("created_at", "note_produit", "note_vendeur")
    ordering = ("-created_at",)

    #: La generation du schema OpenAPI instancie la vue sans URL, donc
    #: sans `produit_id` : il lui faut un queryset de repli pour deduire le
    #: modele expose.
    queryset = Evaluation.objects.none()

    def get_queryset(self):
        produit_id = self.kwargs.get("produit_id")
        if produit_id is None:
            return Evaluation.objects.none()
        return (
            Evaluation.objects.valides().filter(produit_id=produit_id).complet()
        )

    def list(self, request, *args, **kwargs):
        # 404 si l'annonce n'existe pas ou n'est pas publique : une liste
        # vide ne doit pas laisser croire qu'un brouillon existe.
        produit = get_object_or_404(
            Produit.objects.visibles(), pk=self.kwargs["produit_id"]
        )
        queryset = self.filter_queryset(self.get_queryset())
        reputation = Evaluation.objects.du_produit(produit).moyennes()

        page = self.paginate_queryset(queryset)
        serializer = EvaluationPubliqueSerializer(
            page if page is not None else queryset,
            many=True,
            context=self.get_serializer_context(),
        )
        if page is not None:
            reponse = self.get_paginated_response(serializer.data)
            reponse.data["reputation"] = ReputationSerializer(reputation).data
            return reponse
        return Response(
            {
                "count": len(serializer.data),
                "reputation": ReputationSerializer(reputation).data,
                "results": serializer.data,
            }
        )
