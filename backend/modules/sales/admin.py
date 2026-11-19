from django.contrib import admin

from modules.sales.models import LigneVente, Vente


class LigneVenteInline(admin.TabularInline):
    model = LigneVente
    extra = 0
    # Les prix passes ne se reecrivent pas depuis l'admin.
    readonly_fields = ("produit", "quantite", "prix_unitaire", "sous_total")
    can_delete = False


@admin.register(Vente)
class VenteAdmin(admin.ModelAdmin):
    list_display = (
        "id", "vendeur", "acheteur", "montant_total", "devise",
        "moyen_paiement", "statut_paiement", "statut", "created_at",
    )
    list_filter = ("statut", "statut_paiement", "moyen_paiement", "created_at")
    search_fields = ("vendeur__username", "acheteur__username", "lignes__produit__titre")
    autocomplete_fields = ("acheteur", "vendeur", "reservation")
    date_hierarchy = "created_at"
    inlines = [LigneVenteInline]
    readonly_fields = ("montant_total", "confirmee_le", "confirmee_par_acheteur_le")
