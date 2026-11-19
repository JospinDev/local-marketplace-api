"""Module 5 - Suivre / ne plus suivre un vendeur (/following/).

Protection par propriete : chacun ne gere que ses propres abonnements.
Aucune permission de groupe n'intervient, tout compte authentifie peut
suivre un vendeur.
"""
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.db.models import Count, Prefetch, Q
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import mixins, status, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from common.permissions import IsNotSuspended
from modules.products.models import Produit, ProduitImage, StatutProduit
from modules.search.serializers import ProduitPublicListeSerializer
from modules.sellers.models import AbonnementVendeur
from modules.sellers.serializers import AbonnementSerializer, VendeurListeSerializer

User = get_user_model()


@extend_schema_view(
    list=extend_schema(
        tags=["Mes vendeurs suivis"],
        summary="Mes vendeurs suivis",
    ),
)
class AbonnementViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    """Gestion de ses abonnements aux vendeurs."""

    serializer_class = AbonnementSerializer
    permission_classes = [IsAuthenticated, IsNotSuspended]
    ordering = ("-created_at",)

    def get_queryset(self):
        utilisateur = self.request.user
        if not utilisateur.is_authenticated:
            return AbonnementVendeur.objects.none()
        # Le vendeur est precharge via un Prefetch (et non un select_related)
        # pour que ses statistiques soient reellement annotees : sans cela,
        # `nombre_produits_actifs` et `nombre_abonnes` retomberaient a 0 dans
        # le serializer imbrique.
        return AbonnementVendeur.objects.de(utilisateur).prefetch_related(
            Prefetch("vendeur", queryset=self._vendeurs_annotes())
        )

    @staticmethod
    def _vendeurs_annotes():
        """Vendeurs accompagnes de leurs statistiques publiques."""
        return User.objects.annotate(
            nombre_produits_actifs=Count(
                "produits",
                filter=Q(produits__status=StatutProduit.ACTIVE),
                distinct=True,
            ),
            nombre_abonnes=Count("abonnes", distinct=True),
        )

    def _vendeur_annote(self, vendeur_id):
        """Vendeur cible, avec ses statistiques publiques."""
        return get_object_or_404(
            self._vendeurs_annotes().filter(is_active=True), pk=vendeur_id
        )

    # ------------------------------------------------------------- actions
    @extend_schema(
        tags=["Mes vendeurs suivis"],
        summary="Suivre un vendeur",
        request=None,
        responses={201: VendeurListeSerializer, 200: VendeurListeSerializer},
        description=(
            "Idempotent : suivre un vendeur deja suivi renvoie 200 sans "
            "creer de doublon. On ne peut pas se suivre soi-meme."
        ),
    )
    def suivre(self, request, vendeur_id=None):
        vendeur = self._vendeur_annote(vendeur_id)

        if vendeur == request.user:
            return Response(
                {
                    "success": False,
                    "message": "Vous ne pouvez pas vous suivre vous-meme.",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            with transaction.atomic():
                _, cree = AbonnementVendeur.objects.get_or_create(
                    abonne=request.user, vendeur=vendeur
                )
        except IntegrityError:
            cree = False

        # Les statistiques changent apres la creation de l'abonnement.
        vendeur = self._vendeur_annote(vendeur_id)
        return Response(
            {
                "success": True,
                "message": (
                    f"Vous suivez desormais {vendeur.username}."
                    if cree
                    else f"Vous suiviez deja {vendeur.username}."
                ),
                "cree": cree,
                "vendeur": VendeurListeSerializer(
                    vendeur, context=self.get_serializer_context()
                ).data,
            },
            status=status.HTTP_201_CREATED if cree else status.HTTP_200_OK,
        )

    @extend_schema(
        tags=["Mes vendeurs suivis"],
        summary="Ne plus suivre un vendeur",
        request=None,
        responses={204: None, 404: None},
    )
    def ne_plus_suivre(self, request, vendeur_id=None):
        supprimes, _ = AbonnementVendeur.objects.filter(
            abonne=request.user, vendeur_id=vendeur_id
        ).delete()
        if not supprimes:
            return Response(
                {"success": False, "message": "Vous ne suivez pas ce vendeur."},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(status=status.HTTP_204_NO_CONTENT)

    def get_serializer_context(self):
        contexte = super().get_serializer_context()
        utilisateur = self.request.user
        if utilisateur.is_authenticated:
            contexte["vendeurs_suivis"] = set(
                AbonnementVendeur.objects.de(utilisateur).values_list(
                    "vendeur_id", flat=True
                )
            )
        return contexte


@extend_schema_view(
    list=extend_schema(
        tags=["Mes vendeurs suivis"],
        summary="Produits de mes vendeurs suivis",
        description=(
            "Section \"Mes vendeurs preferes\". Cette liste s'ajoute au "
            "catalogue general : elle ne retire aucun produit des autres "
            "listes et ne modifie pas le classement general des recherches."
        ),
    ),
)
class ProduitsSuivisViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    """Annonces publiees par les vendeurs que l'utilisateur suit."""

    serializer_class = ProduitPublicListeSerializer
    permission_classes = [IsAuthenticated]
    ordering_fields = ("publie_le", "created_at", "prix", "nombre_vues")
    ordering = ("-publie_le", "-created_at")

    def get_queryset(self):
        utilisateur = self.request.user
        if not utilisateur.is_authenticated:
            return Produit.objects.none()

        vendeurs_suivis = AbonnementVendeur.objects.de(utilisateur).values_list(
            "vendeur_id", flat=True
        )
        return (
            Produit.objects.visibles()
            .filter(owner_id__in=vendeurs_suivis)
            .select_related("categorie", "owner", "inventaire")
            .prefetch_related(Prefetch("images", queryset=ProduitImage.objects.all()))
        )
