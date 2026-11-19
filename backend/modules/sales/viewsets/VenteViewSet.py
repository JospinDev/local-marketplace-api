"""Module 9 - Ventes (/sales/).

Comme pour les reservations, la protection est basee sur la PROPRIETE : le
queryset ne contient que les ventes ou l'utilisateur est le vendeur ou
l'acheteur. La vente d'un autre vendeur renvoie 404.

Repartition des roles, conforme au paragraphe 8.2 du cahier des charges :

- declarer une vente : le vendeur proprietaire, uniquement ;
- confirmer le paiement recu : le vendeur ;
- confirmer la reception du produit : l'acheteur ;
- annuler : le vendeur, avec motif obligatoire.
"""
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db.models import Count, Sum
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.serializers import ValidationError

from common.permissions import IsNotSuspended
from modules.sales.filters import VenteFilter
from modules.sales.models import StatutVente, Vente
from modules.sales.serializers import (
    MotifAnnulationSerializer,
    RevenusSerializer,
    VenteCreationSerializer,
    VenteSerializer,
)
from modules.sales.services import VenteService

User = get_user_model()
TAG = "Ventes"


@extend_schema_view(
    list=extend_schema(
        tags=[TAG],
        summary="Toutes mes ventes et achats",
        description=(
            "Ventes ou vous etes vendeur ou acheteur.\n\n"
            "Filtres : `statut`, `statut_in=PAID,COMPLETED`, "
            "`comptabilisables=true`, `statut_paiement`, `moyen_paiement`, "
            "`produit`, `titre`, `categorie`, `localisation` (icontains), "
            "`montant_min`, `montant_max`, `montant_total__gte/lte`, "
            "`reservation__isnull`, `created_at_gte/lte`, "
            "`confirmee_le_gte/lte`."
        ),
    ),
    retrieve=extend_schema(tags=[TAG], summary="Detail d'une vente"),
)
class VenteViewSet(
    mixins.RetrieveModelMixin, mixins.ListModelMixin, viewsets.GenericViewSet
):
    """Declaration, confirmation et annulation des ventes."""

    permission_classes = [IsAuthenticated, IsNotSuspended]
    filterset_class = VenteFilter
    ordering_fields = ("created_at", "montant_total", "confirmee_le", "statut")
    ordering = ("-created_at",)

    serializer_classes = {
        "create": VenteCreationSerializer,
        "annuler": MotifAnnulationSerializer,
        "resume": RevenusSerializer,
    }

    def get_serializer_class(self):
        return self.serializer_classes.get(self.action, VenteSerializer)

    def get_queryset(self):
        utilisateur = self.request.user
        if not utilisateur.is_authenticated:
            return Vente.objects.none()
        return Vente.objects.de(utilisateur).complet()

    def _reponse(self, vente, message, code=status.HTTP_200_OK):
        vente = self.get_queryset().get(pk=vente.pk)
        return Response(
            {
                "success": True,
                "message": message,
                "vente": VenteSerializer(
                    vente, context=self.get_serializer_context()
                ).data,
            },
            status=code,
        )

    def _liste(self, queryset):
        queryset = self.filter_queryset(queryset)
        page = self.paginate_queryset(queryset)
        serializer = VenteSerializer(
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
        summary="Declarer une vente (vendeur)",
        responses={201: VenteSerializer},
        description=(
            "Deux usages :\n\n"
            "1. `reservation` (+ `quantite` facultative) : le client avait "
            "reserve et vient retirer. Une quantite inferieure a la quantite "
            "reservee declenche la vente partielle : le solde est libere.\n"
            "2. `produit` + `acheteur` + `quantite` : vente directe, sans "
            "reservation prealable.\n\n"
            "Le moyen de paiement est purement declaratif. La vente est "
            "creee en INITIATED : confirmez ensuite la reception du paiement "
            "avec `/sales/{id}/confirm/`."
        ),
    )
    def create(self, request, *args, **kwargs):
        entree = VenteCreationSerializer(data=request.data)
        entree.is_valid(raise_exception=True)
        donnees = entree.validated_data

        if donnees.get("reservation") is not None:
            vente = VenteService.enregistrer_depuis_reservation(
                reservation=donnees["reservation"],
                vendeur=request.user,
                quantite=donnees.get("quantite"),
                prix_unitaire=donnees.get("prix_unitaire"),
                moyen_paiement=donnees["moyen_paiement"],
                note=donnees.get("note", ""),
            )
            return self._reponse(
                vente, "Vente enregistree.", status.HTTP_201_CREATED
            )

        acheteur = User.objects.filter(pk=donnees["acheteur"]).first()
        if acheteur is None:
            raise ValidationError({"acheteur": "Ce client est introuvable."})

        vente = VenteService.enregistrer_vente_directe(
            produit=donnees["produit"],
            vendeur=request.user,
            acheteur=acheteur,
            quantite=donnees["quantite"],
            prix_unitaire=donnees.get("prix_unitaire"),
            moyen_paiement=donnees["moyen_paiement"],
            note=donnees.get("note", ""),
        )
        return self._reponse(
            vente, "Vente directe enregistree.", status.HTTP_201_CREATED
        )

    # ---------------------------------------------------------------- listes
    @extend_schema(
        tags=[TAG],
        summary="Mes ventes (en tant que vendeur)",
        responses={200: VenteSerializer(many=True)},
    )
    @action(detail=False, methods=["get"], url_path="my-sales")
    def mes_ventes(self, request):
        return self._liste(self.get_queryset().vendues_par(request.user))

    @extend_schema(
        tags=[TAG],
        summary="Mes achats (en tant qu'acheteur)",
        responses={200: VenteSerializer(many=True)},
    )
    @action(detail=False, methods=["get"], url_path="my-purchases")
    def mes_achats(self, request):
        return self._liste(self.get_queryset().achetees_par(request.user))

    @extend_schema(
        tags=[TAG],
        summary="Mes revenus declares",
        responses={200: RevenusSerializer},
        description=(
            "Chiffre d'affaires calcule UNIQUEMENT sur les ventes confirmees "
            "(PAID et COMPLETED), jamais sur les reservations, comme l'exige "
            "le cahier des charges. Chaque ligne conserve son prix d'origine, "
            "donc le total ne bouge pas quand un prix d'annonce change.\n\n"
            "Les filtres de la liste s'appliquent aussi ici : "
            "`?created_at_gte=2026-01-01` pour un revenu sur periode."
        ),
    )
    @action(detail=False, methods=["get"], url_path="summary")
    def resume(self, request):
        mes_ventes = self.filter_queryset(self.get_queryset().vendues_par(request.user))
        comptabilisables = mes_ventes.comptabilisables()

        agregats = comptabilisables.aggregate(
            chiffre_affaires=Sum("montant_total"),
            clients=Count("acheteur", distinct=True),
        )
        quantite = (
            comptabilisables.aggregate(total=Sum("lignes__quantite"))["total"] or 0
        )

        donnees = {
            "ventes_confirmees": comptabilisables.count(),
            "quantite_vendue": quantite,
            "chiffre_affaires": agregats["chiffre_affaires"] or Decimal("0"),
            "ventes_en_attente_de_confirmation": mes_ventes.filter(
                statut=StatutVente.INITIATED
            ).count(),
            "ventes_annulees": mes_ventes.filter(
                statut__in=[StatutVente.CANCELLED, StatutVente.REFUNDED]
            ).count(),
            "nombre_clients": agregats["clients"] or 0,
        }
        return Response(RevenusSerializer(donnees).data)

    # --------------------------------------------------------------- actions
    @extend_schema(
        tags=[TAG],
        summary="Confirmer le paiement recu (vendeur)",
        request=None,
        responses={200: VenteSerializer},
        description=(
            "INITIATED -> PAID. Declaration du vendeur : l'application ne "
            "verifie aucun transfert financier. C'est a partir de ce statut "
            "que la vente entre dans le chiffre d'affaires."
        ),
    )
    @action(detail=True, methods=["post"], url_path="confirm")
    def confirmer(self, request, pk=None):
        vente = VenteService.confirmer_paiement(self.get_object(), request.user)
        return self._reponse(vente, "Paiement confirme : la vente est comptabilisee.")

    @extend_schema(
        tags=[TAG],
        summary="Confirmer la reception du produit (acheteur)",
        request=None,
        responses={200: VenteSerializer},
        description=(
            "PAID -> COMPLETED. Controle recommande par le cahier des "
            "charges : il permet de detecter les ventes declarees a tort et "
            "conditionnera la fiabilite des evaluations (module 11)."
        ),
    )
    @action(detail=True, methods=["post"], url_path="buyer-confirmation")
    def confirmation_acheteur(self, request, pk=None):
        vente = VenteService.confirmer_reception(self.get_object(), request.user)
        return self._reponse(vente, "Reception confirmee : la vente est terminee.")

    @extend_schema(
        tags=[TAG],
        summary="Annuler une vente (vendeur, motif obligatoire)",
        request=MotifAnnulationSerializer,
        responses={200: VenteSerializer},
        description=(
            "Remet les quantites vendues en disponible et laisse une trace "
            "dans l'historique des mouvements de stock. Les lignes et leurs "
            "prix ne sont jamais reecrits.\n\n"
            "Si le paiement avait ete declare recu, la vente part en "
            "REFUNDED (et non CANCELLED) pour que le remboursement reste "
            "visible dans l'historique."
        ),
    )
    @action(detail=True, methods=["post"], url_path="cancel")
    def annuler(self, request, pk=None):
        entree = MotifAnnulationSerializer(data=request.data)
        entree.is_valid(raise_exception=True)
        vente = VenteService.annuler(
            self.get_object(), request.user, entree.validated_data["motif"]
        )
        return self._reponse(
            vente,
            "Vente annulee : les quantites sont de nouveau disponibles."
            if vente.statut == StatutVente.CANCELLED
            else "Vente remboursee : les quantites sont de nouveau disponibles.",
        )
