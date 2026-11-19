"""Module 12 - Notifications (/notifications/).

Les notifications sont strictement PRIVEES : le queryset est toujours
restreint a `destinataire=request.user`. Il n'existe aucun endpoint qui
permette de notifier quelqu'un depuis l'API — une notification est toujours
la consequence d'un evenement metier (message, reservation, vente, avis,
stock), jamais une requete du client. C'est ce qui empeche de s'en servir
pour harceler un utilisateur.
"""
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from modules.notifications.filters import NotificationFilter
from modules.notifications.models import AppareilPush, Notification
from modules.notifications.serializers import (
    AppareilPushCreationSerializer,
    AppareilPushSerializer,
    CompteurNonLuesSerializer,
    EtatPushSerializer,
    MarquageLectureSerializer,
    NotificationSerializer,
    ResultatMarquageSerializer,
)
from modules.notifications.services import NotificationService, PushService

TAG = "Notifications"


@extend_schema_view(
    list=extend_schema(
        tags=[TAG],
        summary="Mes notifications",
        description=(
            "Historique personnel, du plus recent au plus ancien.\n\n"
            "Filtres : `non_lues=true`, `type_notification`, "
            "`type_in=MESSAGE_NOUVEAU,AVIS_NOUVEAU`, `reference_type`, "
            "`reference_id`, `titre` (icontains), `message` (icontains), "
            "`lu_le__isnull`, `created_at_gte`, `created_at_lte`, "
            "`ordering=created_at`."
        ),
    ),
    retrieve=extend_schema(tags=[TAG], summary="Detail d'une notification"),
)
class NotificationViewSet(
    mixins.RetrieveModelMixin,
    mixins.ListModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """Historique, compteur, marquage comme lu et appareils push."""

    serializer_class = NotificationSerializer
    permission_classes = [IsAuthenticated]
    filterset_class = NotificationFilter
    ordering_fields = ("created_at", "lu_le", "type_notification")
    ordering = ("-created_at",)

    def get_queryset(self):
        utilisateur = self.request.user
        if not utilisateur.is_authenticated:
            return Notification.objects.none()
        return Notification.objects.de(utilisateur)

    # ---------------------------------------------------------------- lecture
    @extend_schema(
        tags=[TAG],
        summary="Nombre de notifications non lues",
        responses={200: CompteurNonLuesSerializer},
        description="Badge global de l'application.",
    )
    @action(detail=False, methods=["get"], url_path="unread-count")
    def compteur_non_lues(self, request):
        return Response(
            CompteurNonLuesSerializer(
                {"non_lues": NotificationService.compter_non_lues(request.user)}
            ).data
        )

    @extend_schema(
        tags=[TAG],
        operation_id="notifications_marquer_toutes_lues",
        summary="Marquer comme lues",
        request=MarquageLectureSerializer,
        responses={200: ResultatMarquageSerializer},
        description=(
            "Sans corps, marque **toutes** les notifications non lues. "
            "Avec `identifiants`, seulement celles-la.\n\n"
            "Le nouveau compteur est aussi diffuse sur le WebSocket, pour "
            "que les autres appareils de l'utilisateur se mettent a jour."
        ),
    )
    @action(detail=False, methods=["post"], url_path="read")
    def marquer_lues(self, request):
        entree = MarquageLectureSerializer(data=request.data)
        entree.is_valid(raise_exception=True)

        marquees = NotificationService.marquer_comme_lues(
            request.user, entree.validated_data.get("identifiants")
        )
        return Response(
            ResultatMarquageSerializer(
                {
                    "success": True,
                    "message": f"{marquees} notification(s) marquee(s) comme lue(s).",
                    "marquees": marquees,
                    "non_lues": NotificationService.compter_non_lues(request.user),
                }
            ).data
        )

    @extend_schema(
        tags=[TAG],
        operation_id="notifications_marquer_une_lue",
        summary="Marquer une notification comme lue",
        request=None,
        responses={200: NotificationSerializer},
    )
    @action(detail=True, methods=["post"], url_path="read")
    def marquer_lue(self, request, pk=None):
        notification = self.get_object()
        notification.marquer_comme_lue()
        NotificationService._diffuser_compteur(request.user)
        return Response(
            NotificationSerializer(
                notification, context=self.get_serializer_context()
            ).data
        )

    # -------------------------------------------------------- appareils push
    @extend_schema(
        tags=[TAG],
        summary="Enregistrer / lister mes appareils push",
        request=AppareilPushCreationSerializer,
        responses={200: AppareilPushSerializer(many=True), 201: AppareilPushSerializer},
        description=(
            "GET : mes appareils enregistres.\n"
            "POST : enregistre ou reactive un jeton. Idempotent : renvoyer "
            "le meme jeton met simplement a jour l'appareil.\n\n"
            "Le push est un complement : si le serveur n'a aucune cle "
            "configuree, l'enregistrement reussit quand meme et les "
            "notifications continuent d'arriver en interne et en temps reel."
        ),
    )
    @action(detail=False, methods=["get", "post"], url_path="devices")
    def appareils(self, request):
        if request.method == "GET":
            queryset = AppareilPush.objects.filter(utilisateur=request.user)
            return Response(AppareilPushSerializer(queryset, many=True).data)

        entree = AppareilPushCreationSerializer(data=request.data)
        entree.is_valid(raise_exception=True)
        donnees = entree.validated_data

        appareil, cree = AppareilPush.objects.update_or_create(
            jeton=donnees["jeton"],
            defaults={
                "utilisateur": request.user,
                "plateforme": donnees["plateforme"],
                "libelle": donnees.get("libelle", ""),
                "actif": True,
            },
        )
        return Response(
            {
                "success": True,
                "message": (
                    "Appareil enregistre."
                    if cree
                    else "Appareil deja connu : informations mises a jour."
                ),
                "cree": cree,
                "appareil": AppareilPushSerializer(appareil).data,
            },
            status=status.HTTP_201_CREATED if cree else status.HTTP_200_OK,
        )

    @extend_schema(
        tags=[TAG],
        summary="Desinscrire un appareil push",
        request=None,
        responses={204: None, 404: None},
        description="A appeler a la deconnexion, pour ne plus rien pousser.",
    )
    @action(
        detail=False,
        methods=["delete"],
        url_path="devices/(?P<jeton>[^/]+)",
    )
    def retirer_appareil(self, request, jeton=None):
        supprimes, _ = AppareilPush.objects.filter(
            utilisateur=request.user, jeton=jeton
        ).delete()
        if not supprimes:
            return Response(
                {"success": False, "message": "Cet appareil n'est pas enregistre."},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(
        tags=[TAG],
        summary="Le push est-il operationnel ?",
        responses={200: EtatPushSerializer},
        description=(
            "Permet a l'application de savoir si elle doit proposer "
            "l'activation des notifications push, sans deviner."
        ),
    )
    @action(detail=False, methods=["get"], url_path="devices/status")
    def etat_push(self, request):
        return Response(
            EtatPushSerializer(
                {
                    "push_configure": PushService.est_configure(),
                    "appareils_actifs": AppareilPush.objects.filter(
                        utilisateur=request.user, actif=True
                    ).count(),
                }
            ).data
        )
