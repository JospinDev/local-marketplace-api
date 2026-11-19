"""Routage du module 1 : auth (public), /me/ (prive), /admin/users/ (permissions).

`/me/` n'expose pas de `pk` : le ViewSet travaille toujours sur l'utilisateur
authentifie, les methodes du ViewSet sont donc mappees explicitement.
"""
from django.urls import include, path
from rest_framework.routers import SimpleRouter

from modules.accounts.viewsets import AuthViewSet, MeViewSet, UserAdminViewSet

router_auth = SimpleRouter()
router_auth.register("auth", AuthViewSet, basename="auth")

router_admin = SimpleRouter()
router_admin.register("users", UserAdminViewSet, basename="admin-users")

me_detail = MeViewSet.as_view(
    {
        "get": "retrieve",
        "put": "update",
        "patch": "partial_update",
        "delete": "destroy",
    }
)
me_settings = MeViewSet.as_view({"get": "parametres"})

urlpatterns = [
    path("", include(router_auth.urls)),
    path("me/", me_detail, name="me-detail"),
    path("me/settings/", me_settings, name="me-settings"),
    path("admin/", include(router_admin.urls)),
]
