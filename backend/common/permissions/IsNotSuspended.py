"""Un compte suspendu ne peut plus publier ni contacter les vendeurs."""
from rest_framework.permissions import BasePermission


class IsNotSuspended(BasePermission):
    message = "Votre compte est suspendu : cette action est indisponible."

    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False
        return getattr(user, "statut_compte", "ACTIF") != "SUSPENDU"
