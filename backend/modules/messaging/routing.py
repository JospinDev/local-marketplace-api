"""Routes WebSocket du module 7."""
from django.urls import re_path

from modules.messaging.consumers import ConversationConsumer

websocket_urlpatterns = [
    re_path(
        r"^ws/conversations/(?P<conversation_id>\d+)/$",
        ConversationConsumer.as_asgi(),
        name="ws-conversation",
    ),
]
