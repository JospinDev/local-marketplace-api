"""Permission stricte basee sur les permissions Django (groupes).

Regle metier demandee : un utilisateur appartenant a un groupe ne peut faire
QUE ce que les permissions de ce groupe autorisent.

Exemple : un groupe qui ne contient que `categories.add_categorie` autorise
uniquement la creation d'une categorie. La lecture (`view_categorie`), la
modification (`change_categorie`) et la suppression (`delete_categorie`)
restent refusees (403).

Difference avec `DjangoModelPermissions` de DRF : ce dernier laisse passer
toutes les requetes GET sans exiger `view_*`. Ici, GET exige `view_*`.
"""
from rest_framework.permissions import DjangoModelPermissions


class StrictModelPermission(DjangoModelPermissions):
    """Mappe chaque methode HTTP sur la permission Django correspondante."""

    # La lecture est explicitement controlee par `view_<model>`.
    perms_map = {
        "GET": ["%(app_label)s.view_%(model_name)s"],
        "OPTIONS": [],
        "HEAD": ["%(app_label)s.view_%(model_name)s"],
        "POST": ["%(app_label)s.add_%(model_name)s"],
        "PUT": ["%(app_label)s.change_%(model_name)s"],
        "PATCH": ["%(app_label)s.change_%(model_name)s"],
        "DELETE": ["%(app_label)s.delete_%(model_name)s"],
    }

    def get_required_permissions(self, method, model_cls):
        """Permet de surcharger la permission par action personnalisee.

        Un ViewSet peut declarer :

            action_permissions = {"desactiver": ["%(app_label)s.change_%(model_name)s"]}

        pour qu'une action `@action(detail=True, methods=["post"])` nommee
        `desactiver` exige `change_*` et non `add_*` (POST par defaut).
        """
        return super().get_required_permissions(method, model_cls)

    def has_permission(self, request, view):
        if getattr(view, "_ignore_model_permissions", False):
            return True
        if not request.user or not request.user.is_authenticated:
            return False

        action = getattr(view, "action", None)
        action_permissions = getattr(view, "action_permissions", None) or {}

        if action and action in action_permissions:
            queryset = self._queryset(view)
            kwargs = {
                "app_label": queryset.model._meta.app_label,
                "model_name": queryset.model._meta.model_name,
            }
            required = action_permissions[action]
            if isinstance(required, str):
                required = [required]
            perms = [perm % kwargs for perm in required]
            return request.user.has_perms(perms)

        return super().has_permission(request, view)
