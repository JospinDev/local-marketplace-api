from django.contrib import admin

from modules.moderation.models import JournalAudit, ParametrePlateforme


@admin.register(JournalAudit)
class JournalAuditAdmin(admin.ModelAdmin):
    """Lecture seule, y compris pour un superutilisateur.

    Un journal d'audit que l'on peut retoucher ne vaut rien devant un
    litige : ni ajout, ni modification, ni suppression.
    """

    list_display = (
        "created_at", "acteur_username", "action", "cible_type",
        "cible_id", "cible_libelle", "adresse_ip",
    )
    list_filter = ("action", "cible_type", "created_at")
    search_fields = ("acteur_username", "cible_libelle", "motif")
    date_hierarchy = "created_at"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(ParametrePlateforme)
class ParametrePlateformeAdmin(admin.ModelAdmin):
    list_display = ("cle", "valeur", "type_valeur", "modifie_par", "updated_at")
    list_filter = ("type_valeur",)
    search_fields = ("cle", "description")
    readonly_fields = ("modifie_par",)
