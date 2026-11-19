"""Suspension / reactivation d'un compte par l'administration."""
from rest_framework import serializers


class SuspensionSerializer(serializers.Serializer):
    motif = serializers.CharField(max_length=255, required=False, allow_blank=True)
