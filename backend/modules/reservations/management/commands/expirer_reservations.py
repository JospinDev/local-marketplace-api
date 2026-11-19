"""Libere le stock des reservations arrivees a echeance.

Usage :

    python manage.py expirer_reservations
    python manage.py expirer_reservations --simulation

A planifier (tache cron ou planificateur de taches Windows) a la frequence
souhaitee. L'API appelle de toute facon la meme fonction a la lecture des
listes de reservations, pour qu'une plateforme sans ordonnanceur ne garde
jamais du stock bloque indefiniment ; la commande sert a traiter aussi les
produits que personne ne consulte.
"""
from django.core.management.base import BaseCommand

from modules.reservations.models import Reservation
from modules.reservations.services import ReservationService


class Command(BaseCommand):
    help = "Passe en EXPIRED les reservations depassees et libere leur stock."

    def add_arguments(self, parser):
        parser.add_argument(
            "--simulation",
            action="store_true",
            help="Affiche ce qui serait expire, sans rien modifier.",
        )

    def handle(self, *args, **options):
        a_expirer = list(
            Reservation.objects.expirables().select_related("produit", "acheteur")
        )

        if not a_expirer:
            self.stdout.write("Aucune reservation a expirer.")
            return

        for reservation in a_expirer:
            self.stdout.write(
                f"  reservation {reservation.pk} : "
                f"{reservation.quantite_immobilisee} unite(s) de "
                f"{reservation.produit.titre} ({reservation.statut}), "
                f"echeance {reservation.expire_le:%Y-%m-%d %H:%M}"
            )

        if options["simulation"]:
            self.stdout.write(
                self.style.WARNING(
                    f"Simulation : {len(a_expirer)} reservation(s) seraient expirees."
                )
            )
            return

        traitees = ReservationService.expirer_les_depassees()
        self.stdout.write(
            self.style.SUCCESS(
                f"{traitees} reservation(s) expiree(s) ; le stock immobilise "
                "est de nouveau disponible."
            )
        )
