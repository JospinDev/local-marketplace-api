"""Module 2 - Catalogue public des categories (visiteur non connecte).

Lecture seule : seules les categories actives sont exposees.
"""
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from modules.categories.filters import CategorieFilter
from modules.categories.models import Categorie
from modules.categories.serializers import CategorieSerializer, CategorieTreeSerializer


@extend_schema_view(
    list=extend_schema(
        tags=["Public - Categories"],
        summary="Liste des categories actives",
        description=(
            "Filtres : `nom` (icontains), `recherche`, `parent`, `parent_slug`, "
            "`racines=true`, `ordre_gte`, `ordre_lte`, `created_at_gte`, "
            "`created_at_lte`. Tri : `ordering=nom,-ordre,created_at`."
        ),
    ),
    retrieve=extend_schema(
        tags=["Public - Categories"], summary="Detail d'une categorie"
    ),
    arborescence=extend_schema(
        tags=["Public - Categories"],
        summary="Arborescence complete",
        description="Categories racines avec leurs sous-categories actives.",
    ),
    sous_categories=extend_schema(
        tags=["Public - Categories"], summary="Sous-categories d'une categorie"
    ),
)
class CategoriePublicViewSet(
    mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet
):
    """Endpoints `/public/categories/` ouverts a tous."""

    serializer_class = CategorieSerializer
    permission_classes = [AllowAny]
    authentication_classes = []
    filterset_class = CategorieFilter
    search_fields = ("nom", "description")
    ordering_fields = ("ordre", "nom", "created_at")
    ordering = ("ordre", "nom")
    lookup_field = "pk"

    def get_queryset(self):
        return (
            Categorie.objects.filter(is_active=True)
            .select_related("parent")
            .prefetch_related("sous_categories")
        )

    @action(detail=False, methods=["get"], url_path="tree")
    def arborescence(self, request):
        racines = (
            self.get_queryset().filter(parent__isnull=True).order_by("ordre", "nom")
        )
        serializer = CategorieTreeSerializer(
            racines, many=True, context=self.get_serializer_context()
        )
        return Response(serializer.data)

    @action(detail=True, methods=["get"], url_path="children")
    def sous_categories(self, request, pk=None):
        categorie = self.get_object()
        enfants = categorie.sous_categories.filter(is_active=True).order_by(
            "ordre", "nom"
        )
        page = self.paginate_queryset(enfants)
        serializer = self.get_serializer(page if page is not None else enfants, many=True)
        if page is not None:
            return self.get_paginated_response(serializer.data)
        return Response(serializer.data)
