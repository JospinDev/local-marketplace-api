"""Remplace les 5 champs de localisation par un unique champ texte libre.

Ordre des operations : on ajoute d'abord `localisation`, on y reporte les
valeurs existantes, et seulement ensuite on supprime les anciennes colonnes.
L'inverse ferait perdre les localisations deja saisies.
"""
from django.conf import settings
from django.db import migrations, models

SEPARATEUR = ", "
ANCIENS_CHAMPS = ("quartier", "zone", "commune", "province", "adresse_descriptive")


def reporter_localisation(apps, schema_editor):
    """Concatene les anciens champs non vides, du plus precis au plus large."""
    Produit = apps.get_model("products", "Produit")
    a_mettre_a_jour = []
    for produit in Produit.objects.all().iterator():
        parties = []
        for champ in ANCIENS_CHAMPS:
            valeur = (getattr(produit, champ, "") or "").strip()
            # Evite les repetitions du type "Mukaza, Mukaza".
            if valeur and valeur.lower() not in [p.lower() for p in parties]:
                parties.append(valeur)
        produit.localisation = SEPARATEUR.join(parties)[:255]
        a_mettre_a_jour.append(produit)

    if a_mettre_a_jour:
        Produit.objects.bulk_update(a_mettre_a_jour, ["localisation"], batch_size=500)


def rendre_les_anciens_champs(apps, schema_editor):
    """Retour arriere : remet le texte complet dans `adresse_descriptive`."""
    Produit = apps.get_model("products", "Produit")
    a_mettre_a_jour = []
    for produit in Produit.objects.all().iterator():
        produit.adresse_descriptive = (produit.localisation or "")[:255]
        a_mettre_a_jour.append(produit)
    if a_mettre_a_jour:
        Produit.objects.bulk_update(
            a_mettre_a_jour, ["adresse_descriptive"], batch_size=500
        )


class Migration(migrations.Migration):

    dependencies = [
        ('categories', '0001_initial'),
        ('products', '0001_initial'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        # 1. Le nouveau champ, avant toute suppression.
        migrations.AddField(
            model_name='produit',
            name='localisation',
            field=models.CharField(blank=True, db_index=True, help_text="Texte libre : quartier, zone, commune ou province. Le vendeur n'est jamais oblige d'indiquer son adresse exacte, il peut se limiter a un point de rencontre.", max_length=255, verbose_name='localisation'),
        ),
        # 2. Report des donnees existantes.
        migrations.RunPython(reporter_localisation, rendre_les_anciens_champs),
        # 3. Suppression des anciennes colonnes et de leur index.
        migrations.RemoveIndex(
            model_name='produit',
            name='products_pr_provinc_082c3d_idx',
        ),
        migrations.RemoveField(
            model_name='produit',
            name='adresse_descriptive',
        ),
        migrations.RemoveField(
            model_name='produit',
            name='commune',
        ),
        migrations.RemoveField(
            model_name='produit',
            name='province',
        ),
        migrations.RemoveField(
            model_name='produit',
            name='quartier',
        ),
        migrations.RemoveField(
            model_name='produit',
            name='zone',
        ),
        migrations.AddIndex(
            model_name='produit',
            index=models.Index(fields=['localisation'], name='products_pr_localis_7d228b_idx'),
        ),
    ]
