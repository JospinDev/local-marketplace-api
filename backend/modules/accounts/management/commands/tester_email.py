"""Verifie la configuration d'envoi d'emails.

Usage :

    python manage.py tester_email destinataire@exemple.com

Affiche la configuration active puis tente un envoi reel et explique
precisement la cause en cas d'echec.
"""
from django.conf import settings
from django.core.mail import send_mail
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Envoie un email de test pour valider la configuration SMTP."

    def add_arguments(self, parser):
        parser.add_argument("destinataire", help="Adresse email de destination.")

    def handle(self, *args, **options):
        destinataire = options["destinataire"]

        self.stdout.write("Configuration active :")
        self.stdout.write(f"  EMAIL_BACKEND    = {settings.EMAIL_BACKEND}")
        self.stdout.write(f"  EMAIL_HOST       = {settings.EMAIL_HOST}:{settings.EMAIL_PORT}")
        self.stdout.write(f"  EMAIL_USE_TLS    = {settings.EMAIL_USE_TLS}")
        self.stdout.write(f"  EMAIL_HOST_USER  = {settings.EMAIL_HOST_USER or '(vide)'}")
        mot_de_passe = settings.EMAIL_HOST_PASSWORD
        self.stdout.write(
            f"  EMAIL_HOST_PASSWORD = {'*' * len(mot_de_passe) if mot_de_passe else '(vide)'}"
        )
        self.stdout.write(f"  DEFAULT_FROM_EMAIL = {settings.DEFAULT_FROM_EMAIL}")
        self.stdout.write("")

        if settings.EMAIL_BACKEND.endswith("console.EmailBackend"):
            self.stdout.write(
                self.style.WARNING(
                    "Backend console : l'email ne sera PAS envoye, seulement "
                    "affiche ci-dessous. Renseignez EMAIL_HOST_PASSWORD dans "
                    ".env pour activer l'envoi reel."
                )
            )
            self.stdout.write("")

        try:
            envoyes = send_mail(
                subject="Marketplace Burundi - Test de configuration email",
                message=(
                    "Cet email confirme que la configuration SMTP du backend "
                    "Marketplace Burundi fonctionne.\n\n"
                    "Les codes de verification des comptes seront desormais "
                    "recus a cette adresse."
                ),
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[destinataire],
                fail_silently=False,
            )
        except Exception as exc:
            message = str(exc)
            self.stderr.write(self.style.ERROR(f"Echec de l'envoi : {message}"))
            if "Username and Password not accepted" in message or "535" in message:
                self.stderr.write(
                    "Cause probable : Gmail refuse le mot de passe. Utilisez un "
                    "mot de passe d'application de 16 caracteres, pas le mot de "
                    "passe habituel du compte."
                )
            elif "timed out" in message.lower() or "WinError 10060" in message:
                self.stderr.write(
                    "Cause probable : le port 587 est bloque (pare-feu, reseau "
                    "ou fournisseur d'acces)."
                )
            raise CommandError("Configuration email invalide.") from exc

        if envoyes:
            self.stdout.write(
                self.style.SUCCESS(f"Email envoye a {destinataire}.")
            )
        else:
            self.stderr.write(
                self.style.ERROR("Aucun destinataire n'a ete accepte par le serveur.")
            )
