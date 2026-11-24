"""Cree le groupe de moderation de la plateforme.

Usage :

    python manage.py init_groupes

Le modele d'acces de la plateforme ne comporte que DEUX niveaux :

1. le **superutilisateur** (`manage.py createsuperuser`), qui a tous les
   droits : Django considere ses permissions comme toujours accordees, y
   compris les suppressions et la configuration de la plateforme ;
2. le groupe **Moderateur**, defini ici, qui peut tout CONSULTER dans
   l'administration et MODERER, mais ne supprime rien et ne touche pas a la
   configuration.

Tout autre compte est un utilisateur ordinaire. Il n'a besoin d'aucune
permission pour vendre : l'acces a ses propres annonces, reservations,
ventes et avis repose sur la PROPRIETE de l'objet, pas sur un groupe. Les
permissions ci-dessous ne servent qu'aux endpoints `/api/v1/admin/...`.

Le controle est strict : `common.permissions.StrictModelPermission` exige la
permission correspondant a l'effet reel de chaque appel, y compris pour les
lectures (`view_*`) et pour les actions personnalisees. Un groupe ne peut
donc faire QUE ce que cette liste autorise.
"""
from django.contrib.auth.models import Group, Permission
from django.core.management.base import BaseCommand
from django.db import transaction

NOM_GROUPE = "Moderateur"

#: Permissions du groupe de moderation, par domaine.
#:
#: Ce qui est volontairement ABSENT :
#: - toute permission `delete_*` : un moderateur masque, suspend ou retire,
#:   il n'efface pas. Les suppressions restent au superutilisateur ;
#: - `add_user`, `add_produit`, `add_evaluation` : un moderateur ne cree pas
#:   de contenu a la place des utilisateurs ;
#: - `*_parametreplateforme` en ecriture et `consulter_statistiques` :
#:   la configuration et les chiffres globaux de la plateforme relevent du
#:   superutilisateur ;
#: - `add_journalaudit` et `change_journalaudit` : le journal d'audit n'a
#:   aucune route d'ecriture, personne ne doit pouvoir le retoucher.
PERMISSIONS_MODERATEUR = [
    # --- comptes (module 1) : consulter, suspendre, reactiver -----------
    "accounts.view_user",
    "accounts.change_user",
    # --- categories (module 2) : corriger un libelle, desactiver -------
    "categories.view_categorie",
    "categories.change_categorie",
    # --- annonces (module 3) : moderer le catalogue ---------------------
    "products.view_produit",
    "products.change_produit",
    # --- avis (module 11) : masquer un avis abusif ----------------------
    "reviews.view_evaluation",
    "reviews.change_evaluation",
    # --- signalements (modules 7 et 11) : traiter la file ---------------
    "messaging.view_signalementconversation",
    "messaging.change_signalementconversation",
    # --- litiges (modules 8, 9, 14) : consulter, sans jamais modifier ---
    "reservations.view_reservation",
    "sales.view_vente",
    "sales.view_lignevente",
    "products.view_mouvementstock",
    # --- journal d'audit (module 14) : lecture seule --------------------
    "moderation.view_journalaudit",
    # --- publicites : le bandeau de l'accueil mobile --------------------
    # Le moderateur gere le contenu du bandeau, interrupteur global
    # compris. `delete_publicite` reste au superutilisateur : supprimer
    # une publicite efface aussi ses compteurs, et desactiver suffit.
    "ads.view_publicite",
    "ads.add_publicite",
    "ads.change_publicite",
]


class Command(BaseCommand):
    help = "Cree ou met a jour le groupe Moderateur et ses permissions."

    def add_arguments(self, parser):
        parser.add_argument(
            "--nettoyer",
            action="store_true",
            help=(
                "Supprime les autres groupes (anciens exemples de "
                "moderation specialisee). Les comptes concernes redeviennent "
                "de simples utilisateurs."
            ),
        )

    @transaction.atomic
    def handle(self, *args, **options):
        groupe, cree = Group.objects.get_or_create(name=NOM_GROUPE)

        permissions = []
        for code in PERMISSIONS_MODERATEUR:
            app_label, codename = code.split(".")
            permission = Permission.objects.filter(
                content_type__app_label=app_label, codename=codename
            ).first()
            if permission is None:
                self.stderr.write(
                    self.style.WARNING(f"  permission introuvable : {code}")
                )
                continue
            permissions.append(permission)

        groupe.permissions.set(permissions)
        verbe = "cree" if cree else "mis a jour"
        self.stdout.write(
            self.style.SUCCESS(
                f"Groupe '{NOM_GROUPE}' {verbe} ({len(permissions)} permission(s))"
            )
        )

        if options["nettoyer"]:
            autres = Group.objects.exclude(name=NOM_GROUPE)
            noms = list(autres.values_list("name", flat=True))
            autres.delete()
            if noms:
                self.stdout.write(
                    self.style.WARNING(f"Groupes supprimes : {', '.join(noms)}")
                )
            else:
                self.stdout.write("Aucun autre groupe a supprimer.")

        self.stdout.write("")
        self.stdout.write(
            "Rappel du modele d'acces :\n"
            "  - superutilisateur : tous les droits (createsuperuser) ;\n"
            f"  - groupe {NOM_GROUPE} : consulter et moderer, sans supprimer "
            "ni configurer ;\n"
            "  - tout autre compte : utilisateur ordinaire, qui peut vendre "
            "sans aucune permission."
        )
