"""Routage REST du module 12 : /notifications/."""
from django.urls import include, path
from rest_framework.routers import SimpleRouter

from modules.notifications.viewsets import NotificationViewSet

router = SimpleRouter()
router.register("notifications", NotificationViewSet, basename="notifications")

urlpatterns = [
    path("", include(router.urls)),
]
