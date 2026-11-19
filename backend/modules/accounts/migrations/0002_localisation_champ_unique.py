"""Remplace les 5 champs de localisation du compte par un champ texte libre.

Le nouveau champ est cree, alimente a partir des anciennes valeurs, puis les
anciennes colonnes sont supprimees.
"""
from django.db import migrations, models

SEPARATEUR = ", "
ANCIENS_CHAMPS = ("quartier", "zone", "commune", "province", "adresse_descriptive")


def reporter_localisation(apps, schema_editor):
    User = apps.get_model("accounts", "User")
    a_mettre_a_jour = []
    for utilisateur in User.objects.all().iterator():
        parties = []
        for champ in ANCIENS_CHAMPS:
            valeur = (getattr(utilisateur, champ, "") or "").strip()
            if valeur and valeur.lower() not in [p.lower() for p in parties]:
                parties.append(valeur)
        utilisateur.localisation = SEPARATEUR.join(parties)[:255]
        a_mettre_a_jour.append(utilisateur)

    if a_mettre_a_jour:
        User.objects.bulk_update(a_mettre_a_jour, ["localisation"], batch_size=500)


def rendre_les_anciens_champs(apps, schema_editor):
    User = apps.get_model("accounts", "User")
    a_mettre_a_jour = []
    for utilisateur in User.objects.all().iterator():
        utilisateur.adresse_descriptive = (utilisateur.localisation or "")[:255]
        a_mettre_a_jour.append(utilisateur)
    if a_mettre_a_jour:
        User.objects.bulk_update(
            a_mettre_a_jour, ["adresse_descriptive"], batch_size=500
        )


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='user',
            name='localisation',
            field=models.CharField(blank=True, db_index=True, help_text="Texte libre : quartier, zone, commune ou province, comme vous l'ecrivez. Jamais l'adresse exacte obligatoire.", max_length=255, verbose_name='localisation'),
        ),
        migrations.RunPython(reporter_localisation, rendre_les_anciens_champs),
        migrations.RemoveIndex(
            model_name='user',
            name='accounts_us_provinc_4e1846_idx',
        ),
        migrations.RemoveField(
            model_name='user',
            name='adresse_descriptive',
        ),
        migrations.RemoveField(
            model_name='user',
            name='commune',
        ),
        migrations.RemoveField(
            model_name='user',
            name='province',
        ),
        migrations.RemoveField(
            model_name='user',
            name='quartier',
        ),
        migrations.RemoveField(
            model_name='user',
            name='zone',
        ),
    ]
