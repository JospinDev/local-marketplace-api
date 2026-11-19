from django.contrib import admin

from modules.reviews.models import Evaluation, SignalementEvaluation


class SignalementInline(admin.TabularInline):
    model = SignalementEvaluation
    extra = 0
    readonly_fields = ("signale_par", "motif", "description", "created_at")


@admin.register(Evaluation)
class EvaluationAdmin(admin.ModelAdmin):
    list_display = (
        "id", "produit", "auteur", "vendeur", "note_produit",
        "note_vendeur", "statut", "created_at",
    )
    list_filter = ("statut", "note_produit", "note_vendeur", "created_at")
    search_fields = (
        "produit__titre", "auteur__username", "vendeur__username", "commentaire",
    )
    autocomplete_fields = ("vente", "produit", "auteur", "vendeur")
    date_hierarchy = "created_at"
    inlines = [SignalementInline]
    # Les notes et le texte appartiennent a leur auteur : la moderation
    # masque un avis, elle ne le reecrit pas.
    readonly_fields = (
        "vente", "produit", "auteur", "vendeur", "note_produit",
        "note_vendeur", "commentaire", "modifiee_le", "moderee_par",
        "moderee_le",
    )


@admin.register(SignalementEvaluation)
class SignalementEvaluationAdmin(admin.ModelAdmin):
    list_display = ("id", "evaluation", "signale_par", "motif", "traite_le")
    list_filter = ("motif", "traite_le")
    search_fields = ("evaluation__commentaire", "signale_par__username")
    autocomplete_fields = ("evaluation", "signale_par")
