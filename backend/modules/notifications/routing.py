"""Routes WebSocket du module 12."""
from django.urls import re_path

from modules.notifications.consumers import NotificationConsumer

websocket_urlpatterns = [
    re_path(
        r"^ws/notifications/$",
        NotificationConsumer.as_asgi(),
        name="ws-notifications",
    ),
]
