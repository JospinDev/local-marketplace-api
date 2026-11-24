from django.contrib import admin

from modules.ads.models import Publicite


@admin.register(Publicite)
class PubliciteAdmin(admin.ModelAdmin):
    list_display = ("titre", "actif", "ordre", "debut_le", "fin_le", "nombre_clics")
    list_filter = ("actif", "type_cible")
    search_fields = ("titre", "sous_titre")
    ordering = ("ordre", "-created_at")
