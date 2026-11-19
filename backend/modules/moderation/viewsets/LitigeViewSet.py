"""Module 14 - Consultation en cas de litige.

    "Les administrateurs doivent pouvoir consulter l'historique des
     modifications de stock et des ventes en cas de litige."

Trois vues en LECTURE SEULE, chacune bornee par la permission du modele
qu'elle expose. L'administration constate, elle n'agit pas a la place du
vendeur : il n'y a volontairement aucune action d'ecriture ici, car le
cahier des charges interdit de modifier silencieusement une vente
confirmee. Corriger une vente reste l'affaire de son vendeur, via
`/sales/{id}/cancel/` et son motif obligatoire.

- `/admin/stock-movements/` exige `products.view_mouvementstock`
- `/admin/sales/`           exige `sales.view_vente`
- `/admin/reservations/`    exige `reservations.view_reservation`
"""
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import mixins, viewsets
from rest_framework.permissions import IsAuthenticated

from common.permissions import StrictModelPermission
from modules.moderation.filters import MouvementStockFilter
from modules.moderation.serializers import MouvementStockSerializer
from modules.products.models import MouvementStock
from modules.reservations.filters import ReservationFilter
from modules.reservations.models import Reservation
from modules.reservations.serializers import ReservationSerializer
from modules.sales.filters import VenteFilter
from modules.sales.models import Vente
from modules.sales.serializers import VenteSerializer

TAG = "Admin - Litiges"


@extend_schema_view(
    list=extend_schema(
        tags=[TAG],
        summary="Historique des mouvements de stock",
        description=(
            "Toute variation de quantite, avec sa raison, son auteur, sa "
            "reference et une photographie du stock resultant. Exige "
            "`products.view_mouvementstock`.\n\n"
            "C'est la vue a ouvrir devant un litige : elle explique "
            "pourquoi une quantite a bouge, sans rien recalculer.\n\n"
            "Filtres : `produit`, `titre` (icontains), `owner`, "
            "`owner_username` (icontains), `type_mouvement`, `type_in`, "
            "`reference_type`, `reference_id`, `effectue_par`, "
            "`quantite__gte`/`__lte`, `created_at_gte`, `created_at_lte`."
        ),
    ),
    retrieve=extend_schema(tags=[TAG], summary="Detail d'un mouvement"),
)
class MouvementStockAdminViewSet(
    mixins.RetrieveModelMixin, mixins.ListModelMixin, viewsets.GenericViewSet
):
    """Historique du stock, pour arbitrer un litige."""

    queryset = MouvementStock.objects.all()
    serializer_class = MouvementStockSerializer
    permission_classes = [IsAuthenticated, StrictModelPermission]
    filterset_class = MouvementStockFilter
    ordering_fields = ("created_at", "quantite", "type_mouvement")
    ordering = ("-created_at",)

    def get_queryset(self):
        return MouvementStock.objects.select_related(
            "produit", "produit__owner", "effectue_par"
        )


@extend_schema_view(
    list=extend_schema(
        tags=[TAG],
        summary="Toutes les ventes de la plateforme",
        description=(
            "Lecture seule. Exige `sales.view_vente`. Memes filtres que "
            "`/sales/`, avec `vendeur`, `acheteur`, `statut`, "
            "`comptabilisables`, `montant_min`, `created_at_gte`.\n\n"
            "Aucune action d'ecriture : le cahier des charges interdit de "
            "modifier silencieusement une vente confirmee. L'annulation "
            "reste l'affaire du vendeur, avec un motif obligatoire."
        ),
    ),
    retrieve=extend_schema(tags=[TAG], summary="Detail d'une vente"),
)
class VenteAdminViewSet(
    mixins.RetrieveModelMixin, mixins.ListModelMixin, viewsets.GenericViewSet
):
    """Supervision des ventes."""

    queryset = Vente.objects.all()
    serializer_class = VenteSerializer
    permission_classes = [IsAuthenticated, StrictModelPermission]
    filterset_class = VenteFilter
    ordering_fields = ("created_at", "montant_total", "confirmee_le", "statut")
    ordering = ("-created_at",)

    def get_queryset(self):
        return Vente.objects.all().complet()


@extend_schema_view(
    list=extend_schema(
        tags=[TAG],
        summary="Toutes les reservations de la plateforme",
        description=(
            "Lecture seule. Exige `reservations.view_reservation`. Memes "
            "filtres que `/reservations/`, avec `statut`, `actives`, "
            "`expirees`, `acheteur`, `vendeur`, `produit`, `localisation`."
        ),
    ),
    retrieve=extend_schema(tags=[TAG], summary="Detail d'une reservation"),
)
class ReservationAdminViewSet(
    mixins.RetrieveModelMixin, mixins.ListModelMixin, viewsets.GenericViewSet
):
    """Supervision des reservations."""

    queryset = Reservation.objects.all()
    serializer_class = ReservationSerializer
    permission_classes = [IsAuthenticated, StrictModelPermission]
    filterset_class = ReservationFilter
    ordering_fields = ("created_at", "expire_le", "quantite_demandee", "statut")
    ordering = ("-created_at",)

    def get_queryset(self):
        return Reservation.objects.all().complet()
