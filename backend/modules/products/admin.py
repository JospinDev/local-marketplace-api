from django.contrib import admin

from modules.products.models import (
    Inventaire,
    MouvementStock,
    Produit,
    ProduitImage,
)


class InventaireInline(admin.StackedInline):
    model = Inventaire
    extra = 0
    readonly_fields = ("quantite_reservee", "quantite_vendue")


class ProduitImageInline(admin.TabularInline):
    model = ProduitImage
    extra = 0


@admin.register(Produit)
class ProduitAdmin(admin.ModelAdmin):
    list_display = (
        "titre", "owner", "categorie", "prix", "devise", "etat", "status",
        "localisation", "est_mis_en_avant", "nombre_vues", "created_at",
    )
    list_filter = ("status", "etat", "devise", "est_mis_en_avant", "categorie")
    search_fields = ("titre", "description", "owner__username", "localisation")
    autocomplete_fields = ("categorie", "owner")
    readonly_fields = ("nombre_vues", "publie_le", "slug")
    inlines = (InventaireInline, ProduitImageInline)
    date_hierarchy = "created_at"


@admin.register(Inventaire)
class InventaireAdmin(admin.ModelAdmin):
    list_display = (
        "produit", "quantite_totale", "quantite_reservee",
        "quantite_vendue", "quantite_disponible",
    )
    readonly_fields = ("quantite_reservee", "quantite_vendue")
    search_fields = ("produit__titre",)


@admin.register(MouvementStock)
class MouvementStockAdmin(admin.ModelAdmin):
    """Historique en lecture seule : une trace d'audit ne se corrige pas."""

    list_display = (
        "created_at", "produit", "type_mouvement", "quantite",
        "quantite_totale_apres", "quantite_reservee_apres",
        "quantite_vendue_apres", "effectue_par",
    )
    list_filter = ("type_mouvement", "created_at")
    search_fields = ("produit__titre", "commentaire", "effectue_par__username")
    date_hierarchy = "created_at"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
