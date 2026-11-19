"""Module 8 - Reservations (/reservations/).

Securite : le queryset est restreint aux reservations dont l'utilisateur
connecte est l'acheteur OU le vendeur. La reservation d'autrui renvoie 404 :
la protection ne repose pas sur un groupe de permissions mais sur la
PROPRIETE de la ressource, comme pour les annonces du module 3. Un
moderateur n'a pas a arbitrer les transactions entre deux particuliers.

Chaque action verifie en plus le ROLE : accepter et refuser sont reserves au
vendeur, annuler est ouvert aux deux parties. Ces controles sont dans le
service, pour que la regle soit la meme quelle que soit la porte d'entree.
"""
from django.db.models import Prefetch, Sum
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from common.permissions import IsNotSuspended
from modules.products.models import ProduitImage
from modules.reservations.filters import ReservationFilter
from modules.reservations.models import Reservation, StatutReservation
from modules.reservations.serializers import (
    MotifSerializer,
    QuantiteSerializer,
    ReservationCreationSerializer,
    ReservationSerializer,
    StatistiquesReservationSerializer,
    VenteDepuisReservationSerializer,
)
from modules.reservations.services import ReservationService
from modules.sales.serializers import VenteSerializer
from modules.sales.services import VenteService

TAG = "Reservations"


@extend_schema_view(
    list=extend_schema(
        tags=[TAG],
        summary="Toutes mes reservations (achats et ventes)",
        description=(
            "Reservations ou vous etes acheteur ou vendeur.\n\n"
            "Filtres : `statut`, `statut_in=PENDING,CONFIRMED`, `actives`, "
            "`expirees`, `produit`, `titre`, `categorie`, `etat`, "
            "`localisation` (icontains), `prix_min`, `prix_max`, "
            "`quantite_demandee__gte/lte`, `created_at_gte/lte`, "
            "`expire_le_gte/lte`."
        ),
    ),
    retrieve=extend_schema(tags=[TAG], summary="Detail d'une reservation"),
)
class ReservationViewSet(
    mixins.RetrieveModelMixin, mixins.ListModelMixin, viewsets.GenericViewSet
):
    """Demande, acceptation, refus, annulation et transformation en vente."""

    permission_classes = [IsAuthenticated, IsNotSuspended]
    filterset_class = ReservationFilter
    ordering_fields = ("created_at", "expire_le", "quantite_demandee", "statut")
    ordering = ("-created_at",)

    serializer_classes = {
        "create": ReservationCreationSerializer,
        "accepter": QuantiteSerializer,
        "modifier_quantite": QuantiteSerializer,
        "refuser": MotifSerializer,
        "annuler": MotifSerializer,
        "completer": VenteDepuisReservationSerializer,
        "resume": StatistiquesReservationSerializer,
    }

    def get_serializer_class(self):
        return self.serializer_classes.get(self.action, ReservationSerializer)

    def get_queryset(self):
        utilisateur = self.request.user
        if not utilisateur.is_authenticated:
            return Reservation.objects.none()
        return (
            Reservation.objects.de(utilisateur)
            .complet()
            .prefetch_related(
                Prefetch("produit__images", queryset=ProduitImage.objects.all())
            )
        )

    def _reponse(self, reservation, message, code=status.HTTP_200_OK):
        """Reponse uniforme : la reservation est toujours relue annotee."""
        reservation = self.get_queryset().get(pk=reservation.pk)
        return Response(
            {
                "success": True,
                "message": message,
                "reservation": ReservationSerializer(
                    reservation, context=self.get_serializer_context()
                ).data,
            },
            status=code,
        )

    # ------------------------------------------------------------- creation
    @extend_schema(
        tags=[TAG],
        summary="Demander une reservation",
        responses={201: ReservationSerializer},
        description=(
            "L'acheteur demande une quantite. La demande est verifiee contre "
            "le stock disponible mais ne l'immobilise pas encore : seule "
            "l'acceptation du vendeur met la quantite de cote.\n\n"
            "Refuse (400) si l'annonce n'est pas active, si la quantite "
            "depasse le disponible, s'il s'agit de votre propre annonce ou "
            "si vous avez deja une reservation en cours sur ce produit."
        ),
    )
    def create(self, request, *args, **kwargs):
        entree = ReservationCreationSerializer(data=request.data)
        entree.is_valid(raise_exception=True)
        donnees = entree.validated_data

        reservation = ReservationService.demander(
            produit=donnees["produit"],
            acheteur=request.user,
            quantite=donnees["quantite_demandee"],
            message=donnees.get("message", ""),
        )
        return self._reponse(
            reservation,
            "Demande de reservation envoyee au vendeur.",
            status.HTTP_201_CREATED,
        )

    # ---------------------------------------------------------------- listes
    @extend_schema(
        tags=[TAG],
        summary="Mes demandes (en tant qu'acheteur)",
        responses={200: ReservationSerializer(many=True)},
    )
    @action(detail=False, methods=["get"], url_path="my-requests")
    def mes_demandes(self, request):
        ReservationService.expirer_les_depassees()
        queryset = self.filter_queryset(
            self.get_queryset().demandees_par(request.user)
        )
        page = self.paginate_queryset(queryset)
        serializer = ReservationSerializer(
            page if page is not None else queryset,
            many=True,
            context=self.get_serializer_context(),
        )
        if page is not None:
            return self.get_paginated_response(serializer.data)
        return Response(serializer.data)

    @extend_schema(
        tags=[TAG],
        summary="Reservations recues sur mes annonces (en tant que vendeur)",
        responses={200: ReservationSerializer(many=True)},
        description=(
            "Les demandes a traiter remontent en premier : triez avec "
            "`?statut=PENDING&ordering=created_at`."
        ),
    )
    @action(detail=False, methods=["get"], url_path="my-sales")
    def mes_reservations_recues(self, request):
        ReservationService.expirer_les_depassees()
        queryset = self.filter_queryset(self.get_queryset().recues_par(request.user))
        page = self.paginate_queryset(queryset)
        serializer = ReservationSerializer(
            page if page is not None else queryset,
            many=True,
            context=self.get_serializer_context(),
        )
        if page is not None:
            return self.get_paginated_response(serializer.data)
        return Response(serializer.data)

    @extend_schema(
        tags=[TAG],
        summary="Compteurs de mes reservations",
        responses={200: StatistiquesReservationSerializer},
    )
    @action(detail=False, methods=["get"], url_path="summary")
    def resume(self, request):
        ReservationService.expirer_les_depassees()
        mes_demandes = Reservation.objects.demandees_par(request.user)
        mes_recues = Reservation.objects.recues_par(request.user)

        immobilisee = (
            mes_recues.filter(statut=StatutReservation.CONFIRMED).aggregate(
                total=Sum("quantite_confirmee")
            )["total"]
            or 0
        )

        donnees = {
            "demandes_en_attente": mes_demandes.filter(
                statut=StatutReservation.PENDING
            ).count(),
            "demandes_acceptees": mes_demandes.filter(
                statut=StatutReservation.CONFIRMED
            ).count(),
            "a_traiter": mes_recues.filter(statut=StatutReservation.PENDING).count(),
            "reservations_acceptees_recues": mes_recues.filter(
                statut=StatutReservation.CONFIRMED
            ).count(),
            "quantite_immobilisee": immobilisee,
        }
        return Response(StatistiquesReservationSerializer(donnees).data)

    # --------------------------------------------------------------- actions
    @extend_schema(
        tags=[TAG],
        summary="Accepter une reservation (vendeur)",
        request=QuantiteSerializer,
        responses={200: ReservationSerializer},
        description=(
            "C'est ici que le stock est immobilise, sous verrou de ligne "
            "PostgreSQL : deux acceptations simultanees ne peuvent pas "
            "depasser le stock disponible.\n\n"
            "`quantite` permet d'accepter moins que demande (il ne reste que "
            "2 unites sur les 3 souhaitees). Sans ce champ, toute la "
            "quantite demandee est acceptee."
        ),
    )
    @action(detail=True, methods=["post"], url_path="accept")
    def accepter(self, request, pk=None):
        reservation = self.get_object()
        entree = QuantiteSerializer(data=request.data)
        entree.is_valid(raise_exception=True)

        reservation = ReservationService.accepter(
            reservation, request.user, entree.validated_data.get("quantite")
        )
        return self._reponse(
            reservation,
            f"Reservation acceptee : {reservation.quantite_confirmee} unite(s) "
            "mise(s) de cote.",
        )

    @extend_schema(
        tags=[TAG],
        summary="Refuser une demande (vendeur)",
        request=MotifSerializer,
        responses={200: ReservationSerializer},
        description=(
            "Ne libere aucun stock : une demande en attente n'en immobilisait "
            "pas. La reservation passe en CANCELLED avec le motif indique."
        ),
    )
    @action(detail=True, methods=["post"], url_path="reject")
    def refuser(self, request, pk=None):
        reservation = self.get_object()
        entree = MotifSerializer(data=request.data)
        entree.is_valid(raise_exception=True)

        reservation = ReservationService.refuser(
            reservation, request.user, entree.validated_data.get("motif", "")
        )
        return self._reponse(reservation, "Demande refusee.")

    @extend_schema(
        tags=[TAG],
        summary="Annuler une reservation (acheteur ou vendeur)",
        request=MotifSerializer,
        responses={200: ReservationSerializer},
        description=(
            "Libere immediatement la quantite mise de cote, qui redevient "
            "disponible pour les autres acheteurs. N'affecte jamais la "
            "quantite vendue."
        ),
    )
    @action(detail=True, methods=["post"], url_path="cancel")
    def annuler(self, request, pk=None):
        reservation = self.get_object()
        entree = MotifSerializer(data=request.data)
        entree.is_valid(raise_exception=True)

        reservation = ReservationService.annuler(
            reservation, request.user, entree.validated_data.get("motif", "")
        )
        libere = reservation.produit.quantite_disponible
        return self._reponse(
            reservation,
            f"Reservation annulee. Stock disponible : {libere} unite(s).",
        )

    @extend_schema(
        tags=[TAG],
        summary="Modifier la quantite",
        request=QuantiteSerializer,
        responses={200: ReservationSerializer},
        description=(
            "Tant que la demande est en attente, l'ACHETEUR ajuste la "
            "quantite souhaitee. Une fois la reservation acceptee, c'est le "
            "VENDEUR qui ajuste la quantite mise de cote, puisque c'est son "
            "stock qui est engage ; l'acheteur garde la possibilite "
            "d'annuler. La negociation se fait dans la messagerie."
        ),
    )
    @action(detail=True, methods=["post"], url_path="quantity")
    def modifier_quantite(self, request, pk=None):
        reservation = self.get_object()
        entree = QuantiteSerializer(data=request.data)
        entree.is_valid(raise_exception=True)
        quantite = entree.validated_data.get("quantite")
        if quantite is None:
            return Response(
                {
                    "success": False,
                    "message": "Donnees invalides.",
                    "errors": {"quantite": ["Ce champ est obligatoire."]},
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        reservation = ReservationService.modifier_quantite(
            reservation, request.user, quantite
        )
        return self._reponse(reservation, "Quantite mise a jour.")

    @extend_schema(
        tags=[TAG],
        summary="Transformer la reservation en vente (vendeur)",
        request=VenteDepuisReservationSerializer,
        responses={201: VenteSerializer},
        description=(
            "Scenario central du cahier des charges. Le client a reserve 3 "
            "pantalons et vient en chercher 2 : indiquez `quantite: 2`.\n\n"
            "Le serveur, dans une seule transaction : enregistre la vente de "
            "2 unites au prix convenu, deduit 2 unites du stock physique, "
            "libere les 3 unites reservees et rend la 3e disponible. La "
            "reservation passe en FULFILLED.\n\n"
            "Le prix unitaire est fige dans la ligne de vente : changer le "
            "prix de l'annonce ensuite ne modifie aucun revenu passe."
        ),
    )
    @action(detail=True, methods=["post"], url_path="complete")
    def completer(self, request, pk=None):
        reservation = self.get_object()
        entree = VenteDepuisReservationSerializer(data=request.data)
        entree.is_valid(raise_exception=True)
        donnees = entree.validated_data

        vente = VenteService.enregistrer_depuis_reservation(
            reservation=reservation,
            vendeur=request.user,
            quantite=donnees.get("quantite"),
            prix_unitaire=donnees.get("prix_unitaire"),
            moyen_paiement=donnees.get("moyen_paiement", "CASH"),
            note=donnees.get("note", ""),
        )
        reservation.refresh_from_db()
        return Response(
            {
                "success": True,
                "message": (
                    "Vente enregistree."
                    if reservation.quantite_non_achetee == 0
                    else (
                        f"Vente partielle enregistree : "
                        f"{reservation.quantite_non_achetee} unite(s) "
                        "liberee(s) et de nouveau disponible(s)."
                    )
                ),
                "vente": VenteSerializer(
                    vente, context=self.get_serializer_context()
                ).data,
                "reservation": ReservationSerializer(
                    self.get_queryset().get(pk=reservation.pk),
                    context=self.get_serializer_context(),
                ).data,
            },
            status=status.HTTP_201_CREATED,
        )
