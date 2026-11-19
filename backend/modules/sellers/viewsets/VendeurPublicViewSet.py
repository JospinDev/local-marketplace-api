"""Module 5 - Profils publics des vendeurs (/public/sellers/).

Ouvert aux visiteurs. L'authentification reste facultative : si un token est
fourni, le champ `est_suivi` indique si l'utilisateur connecte suit deja ce
vendeur.
"""
from django.contrib.auth import get_user_model
from django.db.models import Avg, Count, Prefetch, Q
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from modules.products.models import Produit, ProduitImage, StatutProduit
from modules.reviews.models import Evaluation, StatutEvaluation
from modules.reviews.services import EvaluationService
from modules.reviews.serializers import (
    EvaluationPubliqueSerializer,
    ReputationVendeurSerializer,
)
from modules.search.serializers import ProduitPublicListeSerializer
from modules.sellers.filters import VendeurFilter
from modules.sellers.serializers import VendeurDetailSerializer, VendeurListeSerializer

User = get_user_model()


@extend_schema_view(
    list=extend_schema(
        tags=["Public - Vendeurs"],
        summary="Liste des vendeurs",
        description=(
            "Vendeurs ayant au moins une annonce visible. Filtres : `q`, "
            "`nom_commercial`, `localisation` (icontains), `produits_min`, "
            "`abonnes_min`. Tri : `ordering=-nombre_abonnes`, "
            "`-nombre_produits_actifs`, `-date_joined`."
        ),
    ),
    retrieve=extend_schema(
        tags=["Public - Vendeurs"],
        summary="Profil public d'un vendeur",
        description=(
            "Vitrine commerciale : description, localisation, nombre de "
            "produits actifs, nombre d'abonnes, note moyenne, nombre "
            "d'evaluations, contact selon les parametres de confidentialite."
        ),
    ),
    produits=extend_schema(
        tags=["Public - Vendeurs"],
        summary="Annonces d'un vendeur",
        description="Uniquement ses annonces visibles (ACTIVE et OUT_OF_STOCK).",
    ),
    evaluations=extend_schema(
        tags=["Public - Vendeurs"],
        summary="Avis sur un vendeur",
        responses={200: EvaluationPubliqueSerializer(many=True)},
        description=(
            "Avis valides portant sur les ventes de ce vendeur, du plus "
            "recent au plus ancien, avec sa reputation dans `reputation` : "
            "note moyenne de vendeur, note moyenne de produit, nombre "
            "d'avis et repartition par etoile. "
            "Un avis masque par la moderation ou retire par son auteur "
            "n'apparait pas et n'entre dans aucune moyenne."
        ),
    ),
)
class VendeurPublicViewSet(
    mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet
):
    """Vitrine commerciale des vendeurs."""

    permission_classes = [AllowAny]
    filterset_class = VendeurFilter
    search_fields = ("nom_commercial", "nom_complet", "username", "localisation")
    ordering_fields = (
        "nombre_abonnes", "nombre_produits_actifs", "date_joined", "username",
    )
    ordering = ("-nombre_abonnes", "-nombre_produits_actifs")

    def get_serializer_class(self):
        if self.action == "retrieve":
            return VendeurDetailSerializer
        if self.action == "produits":
            return ProduitPublicListeSerializer
        return VendeurListeSerializer

    def _annoter(self, queryset):
        """Statistiques publiques du vendeur, calculees en base."""
        visibles = Q(
            produits__status__in=[StatutProduit.ACTIVE, StatutProduit.OUT_OF_STOCK]
        )
        return queryset.annotate(
            nombre_produits_actifs=Count(
                "produits",
                filter=Q(produits__status=StatutProduit.ACTIVE),
                distinct=True,
            ),
            nombre_produits_publies=Count("produits", filter=visibles, distinct=True),
            nombre_produits_en_rupture=Count(
                "produits",
                filter=Q(produits__status=StatutProduit.OUT_OF_STOCK),
                distinct=True,
            ),
            nombre_abonnes=Count("abonnes", distinct=True),
            # Module 11 : la reputation est annotee ici pour que la liste
            # des vendeurs ne declenche pas une requete par vendeur.
            note_moyenne_vendeur=Avg(
                "evaluations_recues__note_vendeur",
                filter=Q(evaluations_recues__statut=StatutEvaluation.VISIBLE),
            ),
            nombre_evaluations_valides=Count(
                "evaluations_recues",
                filter=Q(evaluations_recues__statut=StatutEvaluation.VISIBLE),
                distinct=True,
            ),
        )

    def get_queryset(self):
        queryset = User.objects.filter(is_active=True)
        if self.action == "list":
            # Une liste de vendeurs n'a de sens que pour ceux qui vendent.
            queryset = queryset.filter(
                produits__status__in=[
                    StatutProduit.ACTIVE, StatutProduit.OUT_OF_STOCK,
                ]
            ).distinct()
        return self._annoter(queryset)

    def get_serializer_context(self):
        """Pre-charge les abonnements pour eviter une requete par vendeur."""
        contexte = super().get_serializer_context()
        utilisateur = self.request.user
        if utilisateur.is_authenticated:
            from modules.sellers.models import AbonnementVendeur

            contexte["vendeurs_suivis"] = set(
                AbonnementVendeur.objects.de(utilisateur).values_list(
                    "vendeur_id", flat=True
                )
            )
        return contexte

    # ------------------------------------------------------------- actions
    @action(detail=True, methods=["get"], url_path="products")
    def produits(self, request, pk=None):
        vendeur = self.get_object()
        queryset = (
            Produit.objects.visibles()
            .filter(owner=vendeur)
            .select_related("categorie", "owner", "inventaire")
            .prefetch_related(Prefetch("images", queryset=ProduitImage.objects.all()))
            .order_by("-publie_le", "-created_at")
        )
        page = self.paginate_queryset(queryset)
        serializer = ProduitPublicListeSerializer(
            page if page is not None else queryset,
            many=True,
            context=self.get_serializer_context(),
        )
        if page is not None:
            return self.get_paginated_response(serializer.data)
        return Response(serializer.data)

    @action(detail=True, methods=["get"], url_path="reviews")
    def evaluations(self, request, pk=None):
        vendeur = self.get_object()
        queryset = Evaluation.objects.recues_par(vendeur).valides().complet()

        reputation = EvaluationService.statistiques_vendeur(vendeur)
        page = self.paginate_queryset(queryset)
        serializer = EvaluationPubliqueSerializer(
            page if page is not None else queryset,
            many=True,
            context=self.get_serializer_context(),
        )
        if page is not None:
            reponse = self.get_paginated_response(serializer.data)
            reponse.data["reputation"] = ReputationVendeurSerializer(
                reputation
            ).data
            return reponse
        return Response(
            {
                "count": len(serializer.data),
                "reputation": ReputationVendeurSerializer(reputation).data,
                "results": serializer.data,
            },
            status=status.HTTP_200_OK,
        )
