"""Module 12 - Filtres des notifications (django-filter)."""
from django_filters import rest_framework as filters

from modules.notifications.models import Notification, TypeNotification


class ListeDeTypes(filters.BaseInFilter, filters.CharFilter):
    """Permet `?type_in=MESSAGE_NOUVEAU,RESERVATION_ACCEPTEE`."""


class NotificationFilter(filters.FilterSet):
    type_notification = filters.ChoiceFilter(choices=TypeNotification.choices)
    type_in = ListeDeTypes(
        field_name="type_notification",
        label="Plusieurs types separes par des virgules",
    )
    non_lues = filters.BooleanFilter(
        method="filtrer_non_lues", label="Uniquement les notifications non lues"
    )
    titre = filters.CharFilter(lookup_expr="icontains")
    message = filters.CharFilter(lookup_expr="icontains")

    created_at_gte = filters.DateTimeFilter(field_name="created_at", lookup_expr="gte")
    created_at_lte = filters.DateTimeFilter(field_name="created_at", lookup_expr="lte")

    class Meta:
        model = Notification
        fields = {
            "reference_type": ["exact"],
            "reference_id": ["exact"],
            "lu_le": ["isnull", "gte", "lte"],
            "created_at": ["exact", "gte", "lte"],
        }

    def filtrer_non_lues(self, queryset, name, value):
        if value is None:
            return queryset
        return queryset.non_lues() if value else queryset.lues()
