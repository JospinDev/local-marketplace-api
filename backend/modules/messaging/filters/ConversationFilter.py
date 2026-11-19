"""Filtres de la messagerie (django-filter)."""
from django_filters import rest_framework as filters

from modules.messaging.models import Conversation, Message


class ConversationFilter(filters.FilterSet):
    produit = filters.NumberFilter(field_name="produit_id")
    # Recherche sur le nom de l'interlocuteur, quel que soit son role.
    interlocuteur = filters.CharFilter(
        method="filtrer_interlocuteur",
        label="Nom de l'interlocuteur contenant le mot saisi",
    )
    titre_produit = filters.CharFilter(
        field_name="produit__titre", lookup_expr="icontains"
    )
    non_lues = filters.BooleanFilter(
        method="filtrer_non_lues",
        label="Uniquement les conversations avec des messages non lus",
    )
    bloquees = filters.BooleanFilter(
        field_name="bloquee_par", lookup_expr="isnull", exclude=True,
        label="Uniquement les conversations bloquees",
    )

    dernier_message_le_gte = filters.DateTimeFilter(
        field_name="dernier_message_le", lookup_expr="gte"
    )
    dernier_message_le_lte = filters.DateTimeFilter(
        field_name="dernier_message_le", lookup_expr="lte"
    )

    class Meta:
        model = Conversation
        fields = {
            "created_at": ["exact", "gte", "lte"],
        }

    def filtrer_interlocuteur(self, queryset, name, value):
        from django.db.models import Q

        utilisateur = self.request.user if self.request else None
        if utilisateur is None or not utilisateur.is_authenticated:
            return queryset.none()

        return queryset.filter(
            (
                Q(acheteur=utilisateur)
                & (
                    Q(vendeur__username__icontains=value)
                    | Q(vendeur__nom_commercial__icontains=value)
                    | Q(vendeur__nom_complet__icontains=value)
                )
            )
            | (
                Q(vendeur=utilisateur)
                & (
                    Q(acheteur__username__icontains=value)
                    | Q(acheteur__nom_commercial__icontains=value)
                    | Q(acheteur__nom_complet__icontains=value)
                )
            )
        )

    def filtrer_non_lues(self, queryset, name, value):
        if self.request is None or not self.request.user.is_authenticated:
            return queryset.none()
        if value:
            return queryset.filter(nombre_non_lus__gt=0)
        return queryset.filter(nombre_non_lus=0)


class MessageFilter(filters.FilterSet):
    contenu = filters.CharFilter(field_name="contenu", lookup_expr="icontains")
    expediteur = filters.NumberFilter(field_name="expediteur_id")
    non_lus = filters.BooleanFilter(
        field_name="lu_le", lookup_expr="isnull", label="Uniquement les non lus"
    )
    avec_image = filters.BooleanFilter(
        field_name="image", lookup_expr="isnull", exclude=True,
        label="Uniquement les messages contenant une image",
    )
    created_at_gte = filters.DateTimeFilter(field_name="created_at", lookup_expr="gte")
    created_at_lte = filters.DateTimeFilter(field_name="created_at", lookup_expr="lte")

    class Meta:
        model = Message
        fields = {
            "created_at": ["exact", "gte", "lte"],
        }
