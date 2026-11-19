"""Module 14 - Configuration de la plateforme (/admin/settings/).

Les reglages metier (duree d'une reservation, delai de modification d'un
avis, seuil d'alerte de stock) deviennent modifiables sans redeploiement.

Garde-fou important : la table peut rester vide. Le code lit chaque reglage
avec `ParametrePlateforme.valeur_de(cle)`, qui retombe sur le `.env` puis
sur la valeur par defaut du code. Une plateforme neuve se comporte donc
exactement comme avant l'existence de ce module, et une valeur mal saisie
est ignoree plutot que de casser une operation metier.

Permissions : `moderation.view_parametreplateforme` pour lire,
`add_` / `change_` / `delete_` pour ecrire. Un groupe limite a la lecture
consulte la configuration sans pouvoir y toucher.
"""
from django.conf import settings
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from common.permissions import StrictModelPermission
from modules.moderation.models import ParametrePlateforme
from modules.moderation.serializers import (
    ClesConnuesSerializer,
    ParametrePlateformeSerializer,
)
from modules.moderation.services import AuditService

TAG = "Admin - Configuration"


@extend_schema_view(
    list=extend_schema(
        tags=[TAG],
        summary="Parametres de la plateforme",
        description="Exige `moderation.view_parametreplateforme`.",
    ),
    retrieve=extend_schema(tags=[TAG], summary="Detail d'un parametre"),
    create=extend_schema(
        tags=[TAG],
        summary="Definir un parametre",
        description=(
            "Exige `moderation.add_parametreplateforme`. Une valeur "
            "incompatible avec le type annonce est refusee (400) plutot "
            "qu'acceptee puis ignoree."
        ),
    ),
    update=extend_schema(tags=[TAG], summary="Remplacer un parametre"),
    partial_update=extend_schema(tags=[TAG], summary="Modifier un parametre"),
    destroy=extend_schema(
        tags=[TAG],
        summary="Supprimer un parametre",
        description=(
            "Le reglage retombe alors sur la valeur du `.env` ou du code. "
            "Exige `moderation.delete_parametreplateforme`."
        ),
    ),
)
class ParametrePlateformeViewSet(viewsets.ModelViewSet):
    """Configuration modifiable de la plateforme."""

    queryset = ParametrePlateforme.objects.all().select_related("modifie_par")
    serializer_class = ParametrePlateformeSerializer
    permission_classes = [IsAuthenticated, StrictModelPermission]
    lookup_field = "pk"
    search_fields = ("cle", "description")
    ordering_fields = ("cle", "updated_at")
    ordering = ("cle",)

    action_permissions = {
        "cles_connues": ["%(app_label)s.view_%(model_name)s"],
    }

    def perform_create(self, serializer):
        parametre = serializer.save(modifie_par=self.request.user)
        AuditService.modification_parametre(
            self.request.user, parametre, valeur_avant=None, requete=self.request
        )

    def perform_update(self, serializer):
        valeur_avant = serializer.instance.valeur
        parametre = serializer.save(modifie_par=self.request.user)
        AuditService.modification_parametre(
            self.request.user, parametre, valeur_avant, requete=self.request
        )

    def perform_destroy(self, instance):
        AuditService.modification_parametre(
            self.request.user, instance, instance.valeur, requete=self.request
        )
        instance.delete()

    @extend_schema(
        tags=[TAG],
        summary="Parametres reconnus par le code",
        responses={200: ClesConnuesSerializer(many=True)},
        description=(
            "Les cles que le serveur sait reellement lire, avec leur type, "
            "leur description, la valeur actuellement utilisee et si elle "
            "vient de la base ou du `.env`.\n\n"
            "Une cle absente de cette liste peut etre creee, mais aucun code "
            "ne la consultera : c'est la pour eviter les reglages fantomes."
        ),
    )
    @action(detail=False, methods=["get"], url_path="known-keys")
    def cles_connues(self, request):
        definies = {
            parametre.cle: parametre
            for parametre in ParametrePlateforme.objects.all()
        }
        lignes = []
        for cle, (type_valeur, description) in (
            ParametrePlateforme.CLES_CONNUES.items()
        ):
            parametre = definies.get(cle)
            active = ParametrePlateforme.valeur_de(cle, getattr(settings, cle, ""))
            lignes.append(
                {
                    "cle": cle,
                    "type_valeur": type_valeur,
                    "description": description,
                    "valeur_active": str(active),
                    "definie_en_base": parametre is not None,
                }
            )
        return Response(ClesConnuesSerializer(lignes, many=True).data)
