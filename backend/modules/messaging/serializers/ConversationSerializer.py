"""Serializers des conversations."""
from django.contrib.auth import get_user_model
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from modules.messaging.models import Conversation, MotifSignalement
from modules.messaging.serializers.MessageSerializer import MessageSerializer
from modules.products.models import Produit

User = get_user_model()


class InterlocuteurSerializer(serializers.Serializer):
    """Participant affiche dans la liste des conversations."""

    id = serializers.IntegerField(read_only=True)
    username = serializers.CharField(read_only=True)
    nom_commercial = serializers.CharField(read_only=True)
    nom_complet = serializers.CharField(read_only=True)
    photo = serializers.ImageField(read_only=True)
    localisation = serializers.CharField(read_only=True)


class ProduitConversationSerializer(serializers.ModelSerializer):
    """Rappel de l'annonce concernee par la discussion."""

    image_principale = serializers.SerializerMethodField()

    class Meta:
        model = Produit
        fields = (
            "id", "titre", "prix", "devise", "status", "localisation",
            "image_principale",
        )
        read_only_fields = fields

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_image_principale(self, obj):
        image = next(
            (i for i in obj.images.all() if i.est_principale),
            next(iter(obj.images.all()), None),
        )
        if image is None:
            return None
        request = self.context.get("request")
        url = image.image.url
        return request.build_absolute_uri(url) if request else url


class ConversationSerializer(serializers.ModelSerializer):
    """Conversation vue par l'un de ses participants."""

    interlocuteur = serializers.SerializerMethodField()
    produit = ProduitConversationSerializer(read_only=True)
    dernier_message = serializers.SerializerMethodField()
    messages_non_lus = serializers.SerializerMethodField()
    est_bloquee = serializers.BooleanField(read_only=True)
    bloquee_par_moi = serializers.SerializerMethodField()
    prix_actuel_produit = serializers.SerializerMethodField()

    class Meta:
        model = Conversation
        fields = (
            "id", "acheteur", "vendeur", "interlocuteur", "produit",
            "prix_initial", "prix_actuel_produit", "dernier_message",
            "messages_non_lus", "est_bloquee", "bloquee_par",
            "bloquee_par_moi", "dernier_message_le", "created_at",
        )
        read_only_fields = fields

    @extend_schema_field(InterlocuteurSerializer)
    def get_interlocuteur(self, obj):
        request = self.context.get("request")
        if request is None or not request.user.is_authenticated:
            return None
        autre = obj.interlocuteur_de(request.user)
        return InterlocuteurSerializer(autre, context=self.context).data

    @extend_schema_field(MessageSerializer(allow_null=True))
    def get_dernier_message(self, obj):
        # `messages` est prefetche par le ViewSet : pas de requete par ligne.
        messages = list(obj.messages.all())
        if not messages:
            return None
        return MessageSerializer(messages[-1], context=self.context).data

    @extend_schema_field(serializers.IntegerField)
    def get_messages_non_lus(self, obj) -> int:
        request = self.context.get("request")
        if request is None or not request.user.is_authenticated:
            return 0
        annote = getattr(obj, "nombre_non_lus", None)
        if annote is not None:
            return annote
        return obj.messages.non_lus_pour(request.user).count()

    @extend_schema_field(serializers.BooleanField)
    def get_bloquee_par_moi(self, obj) -> bool:
        request = self.context.get("request")
        if request is None or not request.user.is_authenticated:
            return False
        return obj.bloquee_par_id == request.user.pk

    @extend_schema_field(serializers.DecimalField(max_digits=14, decimal_places=2, allow_null=True))
    def get_prix_actuel_produit(self, obj):
        # Permet a l'application de signaler un ecart avec `prix_initial`.
        return obj.produit.prix if obj.produit_id else None


class ConversationCreationSerializer(serializers.Serializer):
    """Ouverture d'une conversation, depuis une annonce ou un profil vendeur."""

    produit = serializers.PrimaryKeyRelatedField(
        queryset=Produit.objects.all(),
        required=False,
        allow_null=True,
        help_text="Annonce depuis laquelle la discussion demarre.",
    )
    interlocuteur = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.filter(is_active=True),
        required=False,
        allow_null=True,
        help_text=(
            "Personne a contacter. Obligatoire si aucune annonce n'est "
            "fournie, ou si vous etes vous-meme le proprietaire de l'annonce "
            "(cas du vendeur qui ecrit le premier a un acheteur)."
        ),
    )
    message = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=5000,
        help_text="Premier message, facultatif.",
    )

    def validate_produit(self, produit):
        if produit is None:
            return None
        # On ne discute que d'une annonce reellement visible.
        if not Produit.objects.visibles().filter(pk=produit.pk).exists():
            raise serializers.ValidationError(
                "Cette annonce n'est pas disponible a la discussion."
            )
        return produit

    def validate(self, attrs):
        """Determine les deux participants ET leurs roles.

        Les roles sont imposes par l'annonce, pas par celui qui ecrit le
        premier : le proprietaire de l'annonce est toujours le `vendeur`,
        l'autre participant est l'`acheteur`. Sans cela, un vendeur qui
        contacte un client en premier serait enregistre comme acheteur de
        son propre produit.
        """
        produit = attrs.get("produit")
        interlocuteur = attrs.get("interlocuteur")
        utilisateur = self.context["request"].user

        if produit is None and interlocuteur is None:
            raise serializers.ValidationError(
                {"produit": "Indiquez une annonce ou un interlocuteur."}
            )

        if produit is None:
            acheteur, vendeur = utilisateur, interlocuteur
        elif produit.owner != utilisateur:
            # Cas courant : un acheteur contacte le vendeur depuis l'annonce.
            acheteur, vendeur = utilisateur, produit.owner
        else:
            # Le vendeur ecrit le premier : il doit designer son acheteur.
            if interlocuteur is None:
                raise serializers.ValidationError(
                    {
                        "interlocuteur": (
                            "Cette annonce est la votre : precisez "
                            "l'acheteur que vous souhaitez contacter."
                        )
                    }
                )
            acheteur, vendeur = interlocuteur, produit.owner

        if acheteur == vendeur:
            raise serializers.ValidationError(
                {
                    "detail": (
                        "Vous ne pouvez pas ouvrir une conversation avec "
                        "vous-meme."
                    )
                }
            )

        attrs["acheteur"] = acheteur
        attrs["vendeur"] = vendeur
        return attrs


class BlocageSerializer(serializers.Serializer):
    """Aucun champ : le blocage porte sur la conversation entiere."""


class SignalementSerializer(serializers.Serializer):
    """Signalement d'une conversation, transmis a la moderation."""

    motif = serializers.ChoiceField(choices=MotifSignalement.choices)
    description = serializers.CharField(
        required=False, allow_blank=True, max_length=2000
    )
