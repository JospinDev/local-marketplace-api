"""Permissions de propriete : un vendeur n'agit que sur ses propres objets."""
from rest_framework.permissions import SAFE_METHODS, BasePermission


class IsOwner(BasePermission):
    """Autorise uniquement le proprietaire de l'objet.

    Le champ de propriete est configurable sur la vue via `owner_field`
    (par defaut `owner`).
    """

    message = "Vous n'etes pas le proprietaire de cette ressource."

    def has_object_permission(self, request, view, obj):
        owner_field = getattr(view, "owner_field", "owner")
        owner = getattr(obj, owner_field, None)
        if owner is None and obj.__class__.__name__ == "User":
            owner = obj
        return owner == request.user


class IsOwnerOrReadOnly(IsOwner):
    """Lecture ouverte, ecriture reservee au proprietaire."""

    def has_object_permission(self, request, view, obj):
        if request.method in SAFE_METHODS:
            return True
        return super().has_object_permission(request, view, obj)
