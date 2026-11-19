from django.contrib import admin

from modules.reservations.models import Reservation


@admin.register(Reservation)
class ReservationAdmin(admin.ModelAdmin):
    list_display = (
        "id", "produit", "acheteur", "vendeur", "quantite_demandee",
        "quantite_confirmee", "quantite_livree", "statut", "expire_le",
    )
    list_filter = ("statut", "cloturee_par", "created_at")
    search_fields = ("produit__titre", "acheteur__username", "vendeur__username")
    autocomplete_fields = ("produit", "acheteur", "vendeur")
    date_hierarchy = "created_at"
    readonly_fields = ("quantite_confirmee", "quantite_livree", "confirmee_le")
