"""Module 14 - Statistiques globales (/admin/statistics/).

Point de vue de la PLATEFORME, a ne pas confondre avec le tableau de bord du
module 10 qui est le point de vue d'un vendeur sur ses propres chiffres. Les
deux appliquent la meme regle : le chiffre d'affaires ne compte que les
ventes confirmees.

Permission : `moderation.consulter_statistiques`, declaree sur
`ParametrePlateforme` faute de modele propre aux statistiques (elles n'en
ont pas : ce sont des agregats). Un groupe peut donc donner acces aux
chiffres globaux sans donner acces a la configuration ni au journal.
"""
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from common.permissions import StrictModelPermission
from modules.moderation.models import ParametrePlateforme
from modules.moderation.serializers import StatistiquesGlobalesSerializer
from modules.moderation.services import StatistiquesService

TAG = "Admin - Statistiques"


@extend_schema_view(
    list=extend_schema(
        tags=[TAG],
        summary="Statistiques globales de la plateforme",
        responses={200: StatistiquesGlobalesSerializer},
        description=(
            "Exige `moderation.consulter_statistiques`.\n\n"
            "Couvre les indicateurs de suivi du chapitre 11 du cahier des "
            "charges : utilisateurs (dont comptes suspendus et vendeurs "
            "reels), annonces par statut, reservations avec leur taux de "
            "transformation, ventes et chiffre d'affaires declare, "
            "messagerie, evaluations et file de moderation.\n\n"
            "Le chiffre d'affaires ne compte que les ventes `PAID` et "
            "`COMPLETED` : jamais les reservations."
        ),
    ),
)
class StatistiquesViewSet(viewsets.GenericViewSet):
    """Agregats a l'echelle de la plateforme."""

    # Pas de modele propre : le queryset ne sert qu'a resoudre l'application
    # dont les permissions sont exigees.
    queryset = ParametrePlateforme.objects.none()
    serializer_class = StatistiquesGlobalesSerializer
    permission_classes = [IsAuthenticated, StrictModelPermission]

    action_permissions = {
        "list": ["%(app_label)s.consulter_statistiques"],
    }

    def list(self, request, *args, **kwargs):
        return Response(
            StatistiquesGlobalesSerializer(StatistiquesService.globales()).data
        )
