from django.contrib import admin

from modules.sellers.models import AbonnementVendeur


@admin.register(AbonnementVendeur)
class AbonnementVendeurAdmin(admin.ModelAdmin):
    list_display = ("abonne", "vendeur", "created_at")
    search_fields = ("abonne__username", "vendeur__username")
    autocomplete_fields = ("abonne", "vendeur")
    date_hierarchy = "created_at"
