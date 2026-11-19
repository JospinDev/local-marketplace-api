from django.contrib import admin

from modules.favorites.models import Favori


@admin.register(Favori)
class FavoriAdmin(admin.ModelAdmin):
    list_display = ("utilisateur", "produit", "prix_a_l_ajout", "created_at")
    search_fields = ("utilisateur__username", "produit__titre")
    autocomplete_fields = ("utilisateur", "produit")
    date_hierarchy = "created_at"
