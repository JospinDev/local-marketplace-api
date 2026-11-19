"""Authentification JWT des connexions WebSocket.

Le cahier des charges exige que la connexion WebSocket soit authentifiee.
Django Channels ne lit pas l'en-tete `Authorization` par defaut, et un
client mobile ne peut pas toujours en poser un lors du handshake : le token
est donc accepte de trois facons, par ordre de preference.

1. en-tete `Authorization: Bearer <token>` ;
2. sous-protocole WebSocket ;
3. parametre de requete `?token=<token>` (le plus simple depuis Flutter).

Un token absent ou invalide laisse `scope["user"]` anonyme : c'est le
consumer qui refuse alors la connexion.
"""
from urllib.parse import parse_qs

from channels.db import database_sync_to_async
from channels.middleware import BaseMiddleware
from django.contrib.auth.models import AnonymousUser


@database_sync_to_async
def _utilisateur_depuis_token(token_brut: str):
    """Valide le token et retourne l'utilisateur, ou AnonymousUser."""
    from rest_framework_simplejwt.exceptions import TokenError
    from rest_framework_simplejwt.tokens import AccessToken
    from django.contrib.auth import get_user_model

    try:
        token = AccessToken(token_brut)
        identifiant = token["user_id"]
    except (TokenError, KeyError):
        return AnonymousUser()

    User = get_user_model()
    utilisateur = User.objects.filter(pk=identifiant, is_active=True).first()
    return utilisateur or AnonymousUser()


def _extraire_token(scope) -> str | None:
    # 1. En-tete Authorization.
    for cle, valeur in scope.get("headers", []):
        if cle == b"authorization":
            morceaux = valeur.decode(errors="ignore").split()
            if len(morceaux) == 2 and morceaux[0].lower() == "bearer":
                return morceaux[1]

    # 2. Sous-protocole : ["bearer", "<token>"].
    sous_protocoles = scope.get("subprotocols") or []
    if len(sous_protocoles) >= 2 and sous_protocoles[0].lower() == "bearer":
        return sous_protocoles[1]

    # 3. Parametre de requete ?token=...
    parametres = parse_qs((scope.get("query_string") or b"").decode(errors="ignore"))
    valeurs = parametres.get("token") or parametres.get("access_token")
    if valeurs:
        return valeurs[0]

    return None


class JWTAuthMiddleware(BaseMiddleware):
    """Place l'utilisateur authentifie dans `scope["user"]`."""

    async def __call__(self, scope, receive, send):
        token = _extraire_token(scope)
        scope["user"] = (
            await _utilisateur_depuis_token(token) if token else AnonymousUser()
        )
        return await super().__call__(scope, receive, send)
