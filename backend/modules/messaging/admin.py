from django.contrib import admin

from modules.messaging.models import (
    Conversation,
    Message,
    SignalementConversation,
)


class MessageInline(admin.TabularInline):
    model = Message
    extra = 0
    fields = ("expediteur", "contenu", "image", "lu_le", "created_at")
    readonly_fields = ("created_at",)


@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):
    list_display = (
        "id", "acheteur", "vendeur", "produit", "prix_initial",
        "dernier_message_le", "bloquee_par",
    )
    list_filter = ("bloquee_par",)
    search_fields = (
        "acheteur__username", "vendeur__username", "produit__titre",
    )
    autocomplete_fields = ("acheteur", "vendeur", "produit")
    inlines = (MessageInline,)
    date_hierarchy = "created_at"


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ("id", "conversation", "expediteur", "contenu", "lu_le", "created_at")
    search_fields = ("contenu", "expediteur__username")
    autocomplete_fields = ("conversation", "expediteur")


@admin.register(SignalementConversation)
class SignalementConversationAdmin(admin.ModelAdmin):
    list_display = (
        "id", "conversation", "signale_par", "motif", "traite_le", "created_at",
    )
    list_filter = ("motif",)
    search_fields = ("signale_par__username", "description")
