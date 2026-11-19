"""Module 4 - Product Discovery & Search (API publiques).

Aucune authentification : un visiteur consulte, recherche, filtre et trie.
Seules les annonces visibles sont exposees (ACTIVE et OUT_OF_STOCK) ; les
brouillons, annonces en pause, archivees, retirees ou appartenant a un compte
desactive ne sortent jamais de ce ViewSet.

Tris disponibles (`ordering=`) :
  `prix`, `-prix`                 prix croissant / decroissant
  `-publie_le`, `-created_at`     nouveautes
  `-nombre_vues`                  popularite
  `distance_km`                   proximite (avec latitude et longitude)
"""
from django.db.models import Case, F, FloatField, Prefetch, Value, When
from django.db.models.functions import ACos, Cast, Coalesce, Cos, Least, Radians, Sin
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from modules.products.models import Produit, ProduitImage
from modules.search.filters import ProduitRechercheFilter
from modules.search.serializers import (
    ProduitPublicDetailSerializer,
    ProduitPublicListeSerializer,
)

RAYON_TERRE_KM = 6371.0
# Distance attribuee aux annonces sans coordonnees, pour les releguer en fin
# de tri par proximite sans jamais l'exposer dans la reponse.
DISTANCE_INCONNUE = 1_000_000.0

PARAMETRES_PROXIMITE = [
    OpenApiParameter(
        "latitude",
        description="Latitude du client, pour le tri et le filtre par proximite.",
        required=False,
        type=float,
    ),
    OpenApiParameter(
        "longitude",
        description="Longitude du client, pour le tri et le filtre par proximite.",
        required=False,
        type=float,
    ),
    OpenApiParameter(
        "rayon_km",
        description="Ne retourne que les annonces situees dans ce rayon (km).",
        required=False,
        type=float,
    ),
]


@extend_schema_view(
    list=extend_schema(
        tags=["Public - Produits"],
        summary="Catalogue des annonces",
        description=(
            "Filtres : `q` (mots-cles), `titre`, `categorie`, "
            "`categorie_arbre` (categorie + sous-categories), `prix_min`, "
            "`prix_max`, `localisation` (texte libre, recherche par "
            "`icontains` : `localisation=taba` retourne toutes les annonces "
            "dont la localisation contient taba), `etat` (NEUF / OCCASION), "
            "`disponible`, `quantite_min`, `created_at_gte`, "
            "`created_at_lte`, `owner_username`.\n\n"
            "Tri : `ordering=prix`, `-prix`, `-publie_le`, `-nombre_vues`, "
            "`distance_km`."
        ),
        parameters=PARAMETRES_PROXIMITE,
    ),
    retrieve=extend_schema(
        tags=["Public - Produits"],
        summary="Fiche d'une annonce",
        description="Incremente le compteur de vues utilise par le tri par popularite.",
    ),
    recherche=extend_schema(
        tags=["Public - Produits"],
        summary="Recherche d'annonces",
        description=(
            "Equivalent de la liste, avec les memes filtres. Prevu pour la "
            "barre de recherche mobile (saisie differee cote Flutter)."
        ),
        parameters=PARAMETRES_PROXIMITE,
    ),
    mises_en_avant=extend_schema(
        tags=["Public - Produits"], summary="Produits mis en avant"
    ),
    dernieres=extend_schema(
        tags=["Public - Produits"], summary="Dernieres annonces publiees"
    ),
    populaires=extend_schema(
        tags=["Public - Produits"], summary="Annonces les plus consultees"
    ),
)
class ProduitPublicViewSet(
    mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet
):
    """Endpoints `/public/products/` ouverts a tous."""

    permission_classes = [AllowAny]
    authentication_classes = []
    filterset_class = ProduitRechercheFilter
    search_fields = ("titre", "description", "categorie__nom", "localisation")
    ordering_fields = (
        "prix", "created_at", "publie_le", "nombre_vues", "titre", "distance_km",
    )
    # `ordering=distance_km` trie en realite sur `distance_tri`, qui place les
    # annonces non geolocalisees en dernier sur tous les moteurs SQL.
    ordering_aliases = {"distance_km": "distance_tri"}
    ordering = ("-publie_le", "-created_at")

    def get_serializer_class(self):
        if self.action == "retrieve":
            return ProduitPublicDetailSerializer
        return ProduitPublicListeSerializer

    # ----------------------------------------------------------- queryset
    def _coordonnees_client(self):
        """Lit latitude / longitude dans la requete, si elles sont valides."""
        try:
            latitude = float(self.request.query_params["latitude"])
            longitude = float(self.request.query_params["longitude"])
        except (KeyError, TypeError, ValueError):
            return None, None
        if not (-90 <= latitude <= 90) or not (-180 <= longitude <= 180):
            return None, None
        return latitude, longitude

    def get_queryset(self):
        queryset = (
            Produit.objects.visibles()
            .select_related("categorie", "owner", "inventaire")
            .prefetch_related(Prefetch("images", queryset=ProduitImage.objects.all()))
        )

        latitude, longitude = self._coordonnees_client()
        if latitude is None:
            # `distance_km` existe toujours : le tri par proximite ne casse
            # jamais, il est simplement sans effet sans coordonnees.
            return queryset.annotate(
                distance_km=Value(None, output_field=FloatField()),
                distance_tri=Value(DISTANCE_INCONNUE, output_field=FloatField()),
            )

        # Distance orthodromique (loi des cosinus spherique). `Least(..., 1.0)`
        # evite une erreur de domaine sur ACos due aux arrondis flottants.
        lat_produit = Radians(Cast("latitude", FloatField()))
        lon_produit = Radians(Cast("longitude", FloatField()))
        lat_client = Radians(Value(latitude, output_field=FloatField()))
        lon_client = Radians(Value(longitude, output_field=FloatField()))

        cosinus = (
            Cos(lat_client) * Cos(lat_produit) * Cos(lon_produit - lon_client)
            + Sin(lat_client) * Sin(lat_produit)
        )
        distance = ACos(
            Least(cosinus, Value(1.0, output_field=FloatField()))
        ) * Value(RAYON_TERRE_KM, output_field=FloatField())

        # Le calcul n'est applique qu'aux annonces geolocalisees. Le `Case`
        # est indispensable : dans PostgreSQL, `LEAST(NULL, 1.0)` vaut 1.0
        # (les NULL sont ignores), ce qui donnerait une distance de 0 km aux
        # annonces sans coordonnees.
        distance_ou_null = Case(
            When(latitude__isnull=False, longitude__isnull=False, then=distance),
            default=Value(None, output_field=FloatField()),
            output_field=FloatField(),
        )

        return queryset.annotate(distance_km=distance_ou_null).annotate(
            # Champ de tri : les annonces sans coordonnees passent toujours en
            # dernier, quelle que soit la gestion des NULL du moteur SQL.
            distance_tri=Coalesce(
                F("distance_km"), Value(DISTANCE_INCONNUE, output_field=FloatField())
            )
        )

    # ------------------------------------------------------------- lecture
    def retrieve(self, request, *args, **kwargs):
        produit = self.get_object()
        # Compteur de vues : increment atomique en base, sans ecraser
        # d'autres modifications concurrentes.
        Produit.objects.filter(pk=produit.pk).update(nombre_vues=F("nombre_vues") + 1)
        produit.refresh_from_db(fields=["nombre_vues"])
        return Response(self.get_serializer(produit).data)

    # ------------------------------------------------------------- actions
    def _reponse_liste(self, queryset):
        page = self.paginate_queryset(queryset)
        serializer = self.get_serializer(
            page if page is not None else queryset, many=True
        )
        if page is not None:
            return self.get_paginated_response(serializer.data)
        return Response(serializer.data)

    @action(detail=False, methods=["get"], url_path="search")
    def recherche(self, request):
        return self._reponse_liste(self.filter_queryset(self.get_queryset()))

    @action(detail=False, methods=["get"], url_path="featured")
    def mises_en_avant(self, request):
        queryset = self.filter_queryset(
            self.get_queryset().filter(est_mis_en_avant=True)
        )
        return self._reponse_liste(queryset)

    @action(detail=False, methods=["get"], url_path="latest")
    def dernieres(self, request):
        queryset = self.filter_queryset(self.get_queryset()).order_by(
            F("publie_le").desc(nulls_last=True), "-created_at"
        )
        return self._reponse_liste(queryset)

    @action(detail=False, methods=["get"], url_path="popular")
    def populaires(self, request):
        queryset = self.filter_queryset(self.get_queryset()).order_by(
            "-nombre_vues", "-created_at"
        )
        return self._reponse_liste(queryset)
