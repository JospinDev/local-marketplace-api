"""Module 7 - Conversations et messages (/conversations/).

Securite : le queryset est restreint aux conversations dont l'utilisateur est
l'un des deux participants. Toute tentative d'acces a la discussion d'autrui
renvoie 404 ; les permissions sont verifiees avant chaque operation, y
compris sur les actions personnalisees.
"""
from django.db.models import Count, Prefetch, Q
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from common.permissions import IsNotSuspended
from modules.messaging.filters import ConversationFilter, MessageFilter
from modules.messaging.models import Conversation, Message, SignalementConversation
from modules.messaging.serializers import (
    BlocageSerializer,
    ConversationCreationSerializer,
    ConversationSerializer,
    MessageEnvoiSerializer,
    MessageSerializer,
    SignalementSerializer,
)
from modules.messaging.services import MessagerieService
from modules.products.models import ProduitImage


@extend_schema_view(
    list=extend_schema(
        tags=["Messagerie"],
        summary="Mes conversations",
        description=(
            "Uniquement les conversations de l'utilisateur connecte, triees "
            "par dernier message. Filtres : `produit`, `interlocuteur`, "
            "`titre_produit`, `non_lues=true`, `bloquees=true`, "
            "`dernier_message_le_gte`, `dernier_message_le_lte`."
        ),
    ),
    retrieve=extend_schema(tags=["Messagerie"], summary="Detail d'une conversation"),
    create=extend_schema(
        tags=["Messagerie"],
        summary="Creer ou retrouver une conversation",
        description=(
            "Idempotent : si une discussion existe deja pour le meme couple "
            "d'utilisateurs et la meme annonce, elle est retournee telle "
            "quelle (200) au lieu d'etre dupliquee. Le prix affiche au "
            "demarrage est fige dans `prix_initial`."
        ),
    ),
    messages=extend_schema(
        tags=["Messagerie"],
        summary="Historique / envoi de messages",
        description=(
            "GET : historique pagine, du plus ancien au plus recent.\n"
            "POST : envoie un message (texte, image ou les deux) et le "
            "diffuse en temps reel aux sockets ouverts sur la conversation."
        ),
    ),
    marquer_lu=extend_schema(
        tags=["Messagerie"],
        summary="Marquer les messages comme lus",
        request=None,
    ),
    bloquer=extend_schema(
        tags=["Messagerie"],
        summary="Bloquer / debloquer l'interlocuteur",
        description=(
            "POST bloque la conversation : plus aucun message ne peut y etre "
            "envoye, par l'un comme par l'autre, mais l'historique reste "
            "lisible. DELETE debloque, et seul l'auteur du blocage peut le "
            "lever."
        ),
    ),
    signaler=extend_schema(tags=["Messagerie"], summary="Signaler une conversation"),
    non_lus=extend_schema(
        tags=["Messagerie"],
        summary="Nombre total de messages non lus",
        description="Pour afficher un badge sur l'onglet Messages.",
    ),
)
class ConversationViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    viewsets.GenericViewSet,
):
    """Messagerie entre acheteurs et vendeurs."""

    permission_classes = [IsAuthenticated, IsNotSuspended]
    parser_classes = [JSONParser, MultiPartParser, FormParser]
    filterset_class = ConversationFilter
    ordering_fields = ("dernier_message_le", "created_at")
    ordering = ("-dernier_message_le", "-created_at")

    def get_queryset(self):
        utilisateur = self.request.user
        if not utilisateur.is_authenticated:
            return Conversation.objects.none()

        return (
            Conversation.objects.de(utilisateur)
            .select_related("acheteur", "vendeur", "produit", "bloquee_par")
            .prefetch_related(
                Prefetch(
                    "produit__images", queryset=ProduitImage.objects.all()
                ),
                # Le dernier message est lu depuis ce prefetch, sans requete
                # supplementaire par conversation.
                Prefetch(
                    "messages",
                    queryset=Message.objects.select_related("expediteur").order_by(
                        "created_at"
                    ),
                ),
            )
            .annotate(
                nombre_non_lus=Count(
                    "messages",
                    filter=Q(messages__lu_le__isnull=True)
                    & ~Q(messages__expediteur=utilisateur),
                    distinct=True,
                )
            )
        )

    def get_serializer_class(self):
        if self.action == "create":
            return ConversationCreationSerializer
        if self.action == "messages":
            return (
                MessageEnvoiSerializer
                if self.request.method == "POST"
                else MessageSerializer
            )
        if self.action == "bloquer":
            return BlocageSerializer
        if self.action == "signaler":
            return SignalementSerializer
        return ConversationSerializer

    # -------------------------------------------------------------- creation
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        donnees = serializer.validated_data

        # Les roles sont determines par le serializer : le proprietaire de
        # l'annonce est le vendeur, quel que soit celui qui ecrit le premier.
        conversation, cree = MessagerieService.obtenir_ou_creer_conversation(
            acheteur=donnees["acheteur"],
            vendeur=donnees["vendeur"],
            produit=donnees.get("produit"),
        )

        premier_message = (donnees.get("message") or "").strip()
        if premier_message:
            MessagerieService.envoyer_message(
                conversation, request.user, contenu=premier_message
            )

        conversation = self.get_queryset().get(pk=conversation.pk)
        return Response(
            {
                "success": True,
                "cree": cree,
                "message": (
                    "Conversation creee."
                    if cree
                    else "Conversation existante retournee."
                ),
                "conversation": ConversationSerializer(
                    conversation, context=self.get_serializer_context()
                ).data,
            },
            status=status.HTTP_201_CREATED if cree else status.HTTP_200_OK,
        )

    # --------------------------------------------------------------- actions
    @action(detail=True, methods=["get", "post"], url_path="messages")
    def messages(self, request, pk=None):
        conversation = self.get_object()

        if request.method == "GET":
            queryset = conversation.messages.select_related("expediteur").order_by(
                "created_at"
            )
            queryset = MessageFilter(
                request.query_params, queryset=queryset, request=request
            ).qs
            page = self.paginate_queryset(queryset)
            serializer = MessageSerializer(
                page if page is not None else queryset,
                many=True,
                context=self.get_serializer_context(),
            )
            if page is not None:
                return self.get_paginated_response(serializer.data)
            return Response(serializer.data)

        serializer = MessageEnvoiSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        message = MessagerieService.envoyer_message(
            conversation,
            request.user,
            contenu=serializer.validated_data.get("contenu", ""),
            image=serializer.validated_data.get("image"),
        )
        return Response(
            MessageSerializer(message, context=self.get_serializer_context()).data,
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=["post"], url_path="read")
    def marquer_lu(self, request, pk=None):
        conversation = self.get_object()
        nombre = MessagerieService.marquer_comme_lus(conversation, request.user)
        return Response(
            {
                "success": True,
                "message": f"{nombre} message(s) marque(s) comme lu(s).",
                "messages_marques": nombre,
            },
            status=status.HTTP_200_OK,
        )

    @action(detail=True, methods=["post", "delete"], url_path="block")
    def bloquer(self, request, pk=None):
        conversation = self.get_object()

        if request.method == "POST":
            if conversation.est_bloquee:
                return Response(
                    {
                        "success": False,
                        "message": "Cette conversation est deja bloquee.",
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )
            conversation.bloquer(request.user)
            interlocuteur = conversation.interlocuteur_de(request.user)
            return Response(
                {
                    "success": True,
                    "message": f"{interlocuteur.username} est bloque.",
                    "est_bloquee": True,
                },
                status=status.HTTP_200_OK,
            )

        if not conversation.est_bloquee:
            return Response(
                {"success": False, "message": "Cette conversation n'est pas bloquee."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        # Seul l'auteur du blocage peut le lever.
        if conversation.bloquee_par_id != request.user.pk:
            return Response(
                {
                    "success": False,
                    "message": (
                        "Seul l'utilisateur ayant bloque la conversation peut "
                        "la debloquer."
                    ),
                },
                status=status.HTTP_403_FORBIDDEN,
            )
        conversation.debloquer()
        return Response(
            {"success": True, "message": "Conversation debloquee.", "est_bloquee": False},
            status=status.HTTP_200_OK,
        )

    @action(detail=True, methods=["post"], url_path="report")
    def signaler(self, request, pk=None):
        conversation = self.get_object()
        serializer = SignalementSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        signalement, cree = SignalementConversation.objects.get_or_create(
            conversation=conversation,
            signale_par=request.user,
            traite_le=None,
            defaults={
                "motif": serializer.validated_data["motif"],
                "description": serializer.validated_data.get("description", ""),
            },
        )
        return Response(
            {
                "success": True,
                "cree": cree,
                "message": (
                    "Signalement transmis a la moderation."
                    if cree
                    else "Vous avez deja signale cette conversation."
                ),
                "signalement_id": signalement.pk,
            },
            status=status.HTTP_201_CREATED if cree else status.HTTP_200_OK,
        )

    @action(detail=False, methods=["get"], url_path="unread-count")
    def non_lus(self, request):
        total = (
            Message.objects.filter(
                conversation__in=Conversation.objects.de(request.user)
            )
            .non_lus_pour(request.user)
            .count()
        )
        return Response({"messages_non_lus": total}, status=status.HTTP_200_OK)
