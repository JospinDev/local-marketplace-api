from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from modules.accounts.models import CodeVerificationEmail, User


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    list_display = (
        "username", "email", "email_verifie", "nom_complet",
        "localisation", "statut_compte", "is_active",
    )
    list_filter = ("statut_compte", "email_verifie", "is_active", "is_staff", "groups")
    search_fields = (
        "username", "email", "nom_complet", "nom_commercial",
        "telephone", "localisation",
    )
    ordering = ("-date_joined",)

    fieldsets = (
        (None, {"fields": ("username", "password")}),
        ("Identite", {
            "fields": ("email", "email_verifie", "nom_complet", "telephone", "photo"),
        }),
        ("Localisation", {"fields": ("localisation",)}),
        ("Vitrine vendeur", {
            "fields": ("nom_commercial", "description", "telephone_public"),
        }),
        ("Etat du compte", {
            "fields": (
                "statut_compte", "motif_suspension", "suspendu_le",
                "suppression_demandee_le", "is_active",
            ),
        }),
        ("Permissions", {
            "fields": ("is_staff", "is_superuser", "groups", "user_permissions"),
        }),
        ("Dates", {"fields": ("last_login", "date_joined")}),
    )

    add_fieldsets = (
        (None, {
            "classes": ("wide",),
            "fields": ("username", "email", "password1", "password2"),
        }),
    )


@admin.register(CodeVerificationEmail)
class CodeVerificationEmailAdmin(admin.ModelAdmin):
    list_display = (
        "utilisateur", "email", "type_code", "code",
        "expire_le", "utilise_le", "tentatives",
    )
    list_filter = ("type_code",)
    search_fields = ("utilisateur__username", "email")
