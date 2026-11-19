from django.contrib import admin

from modules.notifications.models import AppareilPush, Notification


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = (
        "id", "destinataire", "type_notification", "titre", "lu_le", "created_at",
    )
    list_filter = ("type_notification", "lu_le", "created_at")
    search_fields = ("destinataire__username", "titre", "message")
    autocomplete_fields = ("destinataire",)
    date_hierarchy = "created_at"
    # Une notification est la trace d'un evenement : on ne la reecrit pas.
    readonly_fields = (
        "destinataire", "type_notification", "titre", "message",
        "reference_type", "reference_id", "donnees",
    )

    def has_add_permission(self, request):
        return False


@admin.register(AppareilPush)
class AppareilPushAdmin(admin.ModelAdmin):
    list_display = (
        "id", "utilisateur", "plateforme", "libelle", "actif",
        "derniere_utilisation", "created_at",
    )
    list_filter = ("plateforme", "actif")
    search_fields = ("utilisateur__username", "jeton", "libelle")
    autocomplete_fields = ("utilisateur",)
