"""Routage REST du module 7 : /conversations/."""
from django.urls import include, path
from rest_framework.routers import SimpleRouter

from modules.messaging.viewsets import ConversationViewSet

router = SimpleRouter()
router.register("conversations", ConversationViewSet, basename="conversations")

urlpatterns = [
    path("", include(router.urls)),
]
