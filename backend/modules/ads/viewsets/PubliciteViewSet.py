"""Publicites : une route publique en lecture, une route d'administration.

Separation volontaire, comme ailleurs dans le projet : la route publique
n'exige aucun compte et ne montre que les publicites diffusables ; la route
d'administration exige les permissions Django du modele et montre tout,
compteurs inclus.
"""
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from common.permissions import StrictModelPermission
from modules.ads.filters import PubliciteFilter
from modules.ads.models import Publicite
from modules.ads.serializers import (
    EtatBandeauSerializer,
    InterrupteurSerializer,
    PubliciteAdminSerializer,
    PubliciteSerializer,
)
from modules.ads.services import PubliciteService

TAG = "Publicites"


@extend_schema_view(
    list=extend_schema(
        tags=[TAG],
        summary="Bandeau publicitaire a afficher",
        description=(
            "Renvoie les publicites diffusables, dans l'ordre d'affichage. "
            "La liste est VIDE quand l'interrupteur global est coupe ou "
            "qu'aucune publicite n'est active : le client doit alors faire "
            "disparaitre l'emplacement, et non afficher un bandeau vide."
        ),
        responses={200: PubliciteSerializer(many=True)},
    ),
)
class PublicitePubliqueViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    """`/api/v1/public/ads/` — lecture seule, sans compte."""

    serializer_class = PubliciteSerializer
    permission_classes = [AllowAny]
    pagination_class = None

    def get_queryset(self):
        return PubliciteService.diffusables()

    def list(self, request, *args, **kwargs):
        publicites = list(self.get_queryset())
        serializer = self.get_serializer(publicites, many=True)

        # Compteur indicatif, isole : il ne doit jamais faire echouer
        # l'affichage du bandeau.
        PubliciteService.compter_affichages([p.pk for p in publicites])

        return Response(serializer.data)

    @extend_schema(
        tags=[TAG],
        summary="Etat du bandeau",
        description=(
            "Permet au client de savoir s'il doit reserver l'emplacement, "
            "sans telecharger les images."
        ),
        responses={200: EtatBandeauSerializer},
    )
    @action(detail=False, methods=["get"], url_path="state")
    def etat(self, request):
        actif = PubliciteService.bandeau_actif()
        return Response(
            EtatBandeauSerializer(
                {
                    "actives": actif,
                    "nombre_diffusables": (
                        Publicite.objects.diffusables().count() if actif else 0
                    ),
                }
            ).data
        )

    @extend_schema(
        tags=[TAG],
        summary="Signaler un clic",
        description="Compteur indicatif. Repond 204 meme si rien n'a change.",
        request=None,
        responses={204: None},
    )
    @action(detail=True, methods=["post"], url_path="click")
    def clic(self, request, pk=None):
        PubliciteService.compter_clic(pk)
        return Response(status=status.HTTP_204_NO_CONTENT)


@extend_schema_view(
    list=extend_schema(tags=[TAG], summary="Toutes les publicites (administration)"),
    retrieve=extend_schema(tags=[TAG], summary="Une publicite (administration)"),
    create=extend_schema(tags=[TAG], summary="Creer une publicite"),
    update=extend_schema(tags=[TAG], summary="Modifier une publicite"),
    partial_update=extend_schema(tags=[TAG], summary="Modifier une publicite"),
    destroy=extend_schema(tags=[TAG], summary="Supprimer une publicite"),
)
class PubliciteAdminViewSet(viewsets.ModelViewSet):
    """`/api/v1/admin/ads/` — reserve aux permissions `ads.*_publicite`.

    Un groupe qui ne contient que `ads.view_publicite` peut consulter et
    rien d'autre : c'est la regle stricte du projet, assuree par
    `StrictModelPermission`.
    """

    queryset = Publicite.objects.all().select_related("cree_par")
    serializer_class = PubliciteAdminSerializer
    permission_classes = [IsAuthenticated, StrictModelPermission]
    filterset_class = PubliciteFilter
    ordering_fields = ("ordre", "created_at", "nombre_clics", "nombre_affichages")
    ordering = ("ordre", "-created_at")

    #: `basculer` et `reordonner` modifient l'affichage : ce sont des
    #: changements, pas des creations, malgre le POST.
    #:
    #: La lecture de l'etat et son basculement sont DEUX actions, et non
    #: une seule action a deux methodes : `action_permissions` est indexe
    #: par nom d'action, donc une action acceptant GET et POST ne pourrait
    #: pas exiger `view` pour l'une et `change` pour l'autre. Un compte en
    #: lecture seule aurait alors pu couper tout le bandeau.
    action_permissions = {
        "basculer": ["%(app_label)s.change_%(model_name)s"],
        "reordonner": ["%(app_label)s.change_%(model_name)s"],
        "etat": ["%(app_label)s.view_%(model_name)s"],
    }

    def perform_create(self, serializer):
        serializer.save(cree_par=self.request.user)

    def _etat(self, actif):
        return Response(
            EtatBandeauSerializer(
                {
                    "actives": actif,
                    "nombre_diffusables": Publicite.objects.diffusables().count(),
                }
            ).data
        )

    @extend_schema(
        tags=[TAG],
        summary="Etat de l'interrupteur global",
        responses={200: EtatBandeauSerializer},
    )
    @action(detail=False, methods=["get"], url_path="state")
    def etat(self, request):
        return self._etat(PubliciteService.bandeau_actif())

    @extend_schema(
        tags=[TAG],
        summary="Allumer ou couper tout le bandeau",
        description=(
            "Interrupteur global. Coupe, la route publique renvoie une "
            "liste vide et l'emplacement disparait cote mobile, sans qu'il "
            "faille desactiver les publicites une par une. "
            "Route distincte de la lecture, et exigeant `change_publicite` : "
            "un compte qui ne peut que consulter ne doit pas pouvoir "
            "eteindre le bandeau."
        ),
        request=InterrupteurSerializer,
        responses={200: EtatBandeauSerializer},
    )
    @action(detail=False, methods=["post"], url_path="toggle")
    def basculer(self, request):
        entree = InterrupteurSerializer(data=request.data)
        entree.is_valid(raise_exception=True)
        return self._etat(
            PubliciteService.basculer(
                entree.validated_data["actives"], request.user
            )
        )

    @extend_schema(
        tags=[TAG],
        summary="Reordonner le bandeau",
        description=(
            "Attend `{\"identifiants\": [3, 1, 7]}` : l'ordre de la liste "
            "devient l'ordre d'affichage."
        ),
        request=None,
        responses={200: PubliciteAdminSerializer(many=True)},
    )
    @action(detail=False, methods=["post"], url_path="reorder")
    def reordonner(self, request):
        identifiants = request.data.get("identifiants")
        if not isinstance(identifiants, list) or not identifiants:
            return Response(
                {
                    "success": False,
                    "message": "Fournissez `identifiants`, une liste non vide.",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        connues = {
            p.pk: p for p in Publicite.objects.filter(id__in=identifiants)
        }
        a_enregistrer = []
        for position, identifiant in enumerate(identifiants):
            publicite = connues.get(identifiant)
            if publicite is None:
                continue
            publicite.ordre = position
            a_enregistrer.append(publicite)

        if a_enregistrer:
            Publicite.objects.bulk_update(a_enregistrer, ["ordre"])

        queryset = self.filter_queryset(self.get_queryset())
        return Response(self.get_serializer(queryset, many=True).data)
