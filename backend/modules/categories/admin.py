from django.contrib import admin

from modules.categories.models import Categorie


@admin.register(Categorie)
class CategorieAdmin(admin.ModelAdmin):
    list_display = ("nom", "parent", "slug", "ordre", "is_active", "created_at")
    list_filter = ("is_active", "parent")
    search_fields = ("nom", "slug", "description")
    prepopulated_fields = {"slug": ("nom",)}
    ordering = ("ordre", "nom")
    autocomplete_fields = ("parent",)
