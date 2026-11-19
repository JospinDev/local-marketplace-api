"""Point d'entree ASGI : HTTP (Django) + WebSocket (Channels).

Le WebSocket est authentifie par JWT via `JWTAuthMiddleware`, et
`AllowedHostsOriginValidator` refuse les origines non autorisees.
"""
import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")

# L'application HTTP doit etre construite avant d'importer le routage, pour
# que le registre des applications Django soit pret.
django_asgi_application = get_asgi_application()

from channels.routing import ProtocolTypeRouter, URLRouter  # noqa: E402
from channels.security.websocket import AllowedHostsOriginValidator  # noqa: E402

from modules.messaging.middleware import JWTAuthMiddleware  # noqa: E402
from modules.messaging.routing import (  # noqa: E402
    websocket_urlpatterns as routes_messagerie,
)
from modules.notifications.routing import (  # noqa: E402
    websocket_urlpatterns as routes_notifications,
)

# Deux canaux, une seule authentification : la messagerie (module 7) et les
# notifications (module 12) partagent `JWTAuthMiddleware`.
websocket_urlpatterns = routes_messagerie + routes_notifications

application = ProtocolTypeRouter(
    {
        "http": django_asgi_application,
        "websocket": AllowedHostsOriginValidator(
            JWTAuthMiddleware(URLRouter(websocket_urlpatterns))
        ),
    }
)
