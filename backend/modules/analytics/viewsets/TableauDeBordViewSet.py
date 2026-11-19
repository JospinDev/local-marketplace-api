"""Module 10 - Tableau de bord vendeur (/seller-dashboard/).

Il n'y a rien a proteger par groupe ici : chaque vendeur ne voit QUE ses
propres chiffres. Tous les calculs partent de `request.user`, jamais d'un
identifiant fourni par le client, ce qui rend l'acces aux donnees d'un autre
vendeur impossible par construction (il n'y a pas de parametre a falsifier).

Le module n'a ni modele ni migration : c'est une vue de lecture sur les
modules 3, 7, 8, 9 et 11.
"""
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from modules.analytics.serializers import (
    CompteursReservationsSerializer,
    ProduitsPopulairesSerializer,
    TableauDeBordRevenusSerializer,
    StocksSerializer,
    VueGeneraleSerializer,
)
from modules.analytics.services import TableauDeBordService
from modules.reservations.filters import ReservationFilter
from modules.reservations.models import Reservation
from modules.reservations.serializers import ReservationSerializer
from modules.reservations.services import ReservationService
from modules.sales.filters import VenteFilter
from modules.sales.models import Vente
from modules.sales.serializers import VenteSerializer

TAG = "Tableau de bord vendeur"


@extend_schema_view(
    vue_generale=extend_schema(
        tags=[TAG],
        summary="Vue generale",
        responses={200: VueGeneraleSerializer},
        description=(
            "Section A du cahier des charges : produits publies, "
            "disponibles, en rupture, reservations en cours, ventes "
            "confirmees, clients, conversations, et votre note moyenne."
        ),
    ),
    revenus=extend_schema(
        tags=[TAG],
        summary="Revenus",
        responses={200: TableauDeBordRevenusSerializer},
        description=(
            "Section B. Le chiffre d'affaires ne compte **que les ventes "
            "confirmees** (`PAID` et `COMPLETED`), conformement au "
            "paragraphe E du cahier des charges : 5 reservations a "
            "250 000 BIF et 3 ventes confirmees a 150 000 BIF donnent un "
            "revenu declare de 150 000 BIF.\n\n"
            "La valeur des reservations en cours est renvoyee a part, dans "
            "`valeur_reservations_en_cours`, et n'entre dans aucun total.\n\n"
            "Les periodes (jour, semaine depuis lundi, mois) se mesurent sur "
            "la date de confirmation du paiement : le moment ou l'argent est "
            "entre, pas celui ou la vente a ete saisie."
        ),
    ),
    ventes=extend_schema(
        tags=[TAG],
        summary="Historique des ventes",
        responses={200: VenteSerializer(many=True)},
        description=(
            "Toutes mes ventes, paginees. Accepte les memes filtres que "
            "`/sales/` : `statut`, `comptabilisables=true`, `moyen_paiement`, "
            "`titre`, `montant_min`, `created_at_gte`, `ordering=`."
        ),
    ),
    stocks=extend_schema(
        tags=[TAG],
        summary="Etat des stocks",
        responses={200: StocksSerializer},
        description=(
            "Section C : stock total, quantite reservee, quantite vendue et "
            "disponible, en total et ligne par ligne, avec la valeur du "
            "stock disponible au prix actuel des annonces."
        ),
    ),
    reservations=extend_schema(
        tags=[TAG],
        summary="Reservations",
        responses={200: CompteursReservationsSerializer},
        description=(
            "Section D : combien de demandes en attente, acceptees, "
            "annulees, expirees, transformees en vente, plus le taux de "
            "transformation.\n\n"
            "Ajoutez `?liste=true` pour obtenir a la place la liste paginee "
            "des reservations recues (memes filtres que `/reservations/`)."
        ),
    ),
    produits_populaires=extend_schema(
        tags=[TAG],
        summary="Produits populaires",
        responses={200: ProduitsPopulairesSerializer},
        description=(
            "Section D : les plus vendus (par quantite reellement vendue) et "
            "les plus consultes (par nombre de vues). `?limite=5` pour "
            "raccourcir chaque palmares (1 a 50, 10 par defaut)."
        ),
    ),
)
class TableauDeBordViewSet(viewsets.GenericViewSet):
    """Indicateurs commerciaux et financiers du vendeur connecte."""

    permission_classes = [IsAuthenticated]
    serializer_class = VueGeneraleSerializer

    def get_queryset(self):
        # Aucun modele propre : le ViewSet n'expose que des agregats.
        return Vente.objects.none()

    def _limite(self, defaut=10, maximum=50) -> int:
        brut = self.request.query_params.get("limite")
        if brut is None:
            return defaut
        try:
            valeur = int(brut)
        except (TypeError, ValueError):
            return defaut
        return max(1, min(valeur, maximum))

    def _liste(self, queryset, serializer_class, filterset_class):
        filtre = filterset_class(
            self.request.query_params, queryset=queryset, request=self.request
        )
        queryset = filtre.qs
        page = self.paginate_queryset(queryset)
        serializer = serializer_class(
            page if page is not None else queryset,
            many=True,
            context=self.get_serializer_context(),
        )
        if page is not None:
            return self.get_paginated_response(serializer.data)
        return Response(serializer.data)

    # ------------------------------------------------------------- A. apercu
    @action(detail=False, methods=["get"], url_path="overview")
    def vue_generale(self, request):
        donnees = TableauDeBordService.vue_generale(request.user)
        return Response(VueGeneraleSerializer(donnees).data)

    # ---------------------------------------------------------- B. financier
    @action(detail=False, methods=["get"], url_path="revenue")
    def revenus(self, request):
        donnees = TableauDeBordService.revenus(request.user)
        return Response(TableauDeBordRevenusSerializer(donnees).data)

    @action(detail=False, methods=["get"], url_path="sales")
    def ventes(self, request):
        return self._liste(
            Vente.objects.vendues_par(request.user).complet(),
            VenteSerializer,
            VenteFilter,
        )

    # -------------------------------------------------------------- C. stocks
    @action(detail=False, methods=["get"], url_path="inventory")
    def stocks(self, request):
        donnees = TableauDeBordService.stocks(request.user)
        return Response(StocksSerializer(donnees).data)

    # --------------------------------------------------------- D. historiques
    @action(detail=False, methods=["get"], url_path="reservations")
    def reservations(self, request):
        # Les reservations perimees sont liberees avant de compter : un
        # tableau de bord ne doit pas afficher du stock immobilise a tort.
        ReservationService.expirer_les_depassees()

        if request.query_params.get("liste", "").lower() in ("true", "1"):
            return self._liste(
                Reservation.objects.recues_par(request.user).complet(),
                ReservationSerializer,
                ReservationFilter,
            )

        donnees = TableauDeBordService.compteurs_reservations(request.user)
        donnees["taux_de_transformation"] = (
            TableauDeBordService.taux_de_transformation(request.user)
        )
        return Response(CompteursReservationsSerializer(donnees).data)

    @action(detail=False, methods=["get"], url_path="top-products")
    def produits_populaires(self, request):
        limite = self._limite()
        donnees = {
            "les_plus_vendus": TableauDeBordService.produits_les_plus_vendus(
                request.user, limite
            ),
            "les_plus_consultes": TableauDeBordService.produits_les_plus_consultes(
                request.user, limite
            ),
        }
        return Response(ProduitsPopulairesSerializer(donnees).data)
