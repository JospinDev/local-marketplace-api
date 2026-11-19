"""Module 6 - Gestion des produits favoris (/favorites/products/).

Les favoris sont PRIVES : le queryset est systematiquement restreint a
`utilisateur=request.user`, personne ne peut consulter les favoris d'autrui.
"""
from django.db import IntegrityError, transaction
from django.db.models import Prefetch
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import mixins, status, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from modules.favorites.filters import FavoriFilter
from modules.favorites.models import Favori
from modules.favorites.serializers import FavoriSerializer
from modules.products.models import Produit, ProduitImage


@extend_schema_view(
    list=extend_schema(
        tags=["Mes favoris"],
        summary="Mes produits favoris",
        description=(
            "Liste privee. Chaque ligne signale si le produit est toujours "
            "disponible, si l'annonce a ete retiree et si le prix a change "
            "depuis la mise en favori.\n\n"
            "Filtres : `disponible`, `retire`, `prix_a_change`, `titre`, "
            "`categorie`, `etat`, `localisation`, `prix_min`, `prix_max`, "
            "`created_at_gte`, `created_at_lte`."
        ),
    ),
)
class FavoriViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    """Ajout, retrait et consultation de ses favoris."""

    serializer_class = FavoriSerializer
    permission_classes = [IsAuthenticated]
    filterset_class = FavoriFilter
    ordering_fields = ("created_at", "produit__prix", "produit__titre")
    ordering = ("-created_at",)

    def get_queryset(self):
        utilisateur = self.request.user
        if not utilisateur.is_authenticated:
            return Favori.objects.none()
        return (
            Favori.objects.de(utilisateur)
            .select_related(
                "produit", "produit__categorie", "produit__owner",
                "produit__inventaire",
            )
            .prefetch_related(
                Prefetch("produit__images", queryset=ProduitImage.objects.all())
            )
        )

    # ------------------------------------------------------------- actions
    @extend_schema(
        tags=["Mes favoris"],
        summary="Ajouter un produit aux favoris",
        request=None,
        responses={201: FavoriSerializer, 200: FavoriSerializer},
        description=(
            "Idempotent : un produit deja en favori renvoie 200 sans creer "
            "de doublon. Le prix du jour est enregistre pour detecter les "
            "variations ulterieures."
        ),
    )
    def ajouter(self, request, produit_id=None):
        # On ne met en favori qu'une annonce reellement visible : un
        # brouillon ou une annonce retiree n'est pas accessible.
        produit = get_object_or_404(Produit.objects.visibles(), pk=produit_id)

        try:
            with transaction.atomic():
                favori, cree = Favori.objects.get_or_create(
                    utilisateur=request.user,
                    produit=produit,
                    defaults={"prix_a_l_ajout": produit.prix},
                )
        except IntegrityError:
            favori = Favori.objects.get(utilisateur=request.user, produit=produit)
            cree = False

        favori = self.get_queryset().get(pk=favori.pk)
        return Response(
            {
                "success": True,
                "message": (
                    "Produit ajoute a vos favoris."
                    if cree
                    else "Ce produit est deja dans vos favoris."
                ),
                "cree": cree,
                "favori": FavoriSerializer(
                    favori, context=self.get_serializer_context()
                ).data,
            },
            status=status.HTTP_201_CREATED if cree else status.HTTP_200_OK,
        )

    @extend_schema(
        tags=["Mes favoris"],
        summary="Retirer un produit des favoris",
        request=None,
        responses={204: None, 404: None},
    )
    def retirer(self, request, produit_id=None):
        supprimes, _ = Favori.objects.filter(
            utilisateur=request.user, produit_id=produit_id
        ).delete()
        if not supprimes:
            return Response(
                {
                    "success": False,
                    "message": "Ce produit n'est pas dans vos favoris.",
                },
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(status=status.HTTP_204_NO_CONTENT)
