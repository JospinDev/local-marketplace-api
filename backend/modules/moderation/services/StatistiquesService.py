"""Statistiques globales de la plateforme (module 14).

Difference essentielle avec le tableau de bord du module 10 : celui-ci est
le point de vue d'UN vendeur sur SES chiffres, celui-la est le point de vue
de la plateforme sur l'ensemble. Les deux partagent la meme regle d'or : le
chiffre d'affaires ne compte que les ventes confirmees.

Tous les indicateurs du chapitre 11 du cahier des charges ("Indicateurs de
suivi") sont couverts : utilisateurs, annonces, reservations, ventes,
revenus, taux de transformation, avis.
"""
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db.models import Avg, Count, DecimalField, Q, Sum, Value
from django.db.models.functions import Coalesce
from django.utils import timezone

from modules.messaging.models import Conversation, Message, SignalementConversation
from modules.products.models import Produit, StatutProduit
from modules.reservations.models import Reservation, StatutReservation
from modules.reviews.models import Evaluation, SignalementEvaluation, StatutEvaluation
from modules.sales.models import LigneVente, StatutVente, Vente, VenteQuerySet

User = get_user_model()
ZERO = Value(Decimal("0"), output_field=DecimalField(max_digits=20, decimal_places=2))


class StatistiquesService:
    """Agregats a l'echelle de la plateforme."""

    @staticmethod
    def globales() -> dict:
        return {
            "utilisateurs": StatistiquesService.utilisateurs(),
            "annonces": StatistiquesService.annonces(),
            "reservations": StatistiquesService.reservations(),
            "ventes": StatistiquesService.ventes(),
            "messagerie": StatistiquesService.messagerie(),
            "evaluations": StatistiquesService.evaluations(),
            "moderation": StatistiquesService.moderation(),
            "genere_le": timezone.now(),
        }

    # -------------------------------------------------------- utilisateurs
    @staticmethod
    def utilisateurs() -> dict:
        maintenant = timezone.now()
        debut_mois = timezone.localtime(maintenant).replace(
            day=1, hour=0, minute=0, second=0, microsecond=0
        )
        agregats = User.objects.aggregate(
            total=Count("id"),
            actifs=Count("id", filter=Q(is_active=True)),
            suspendus=Count("id", filter=Q(statut_compte="SUSPENDU")),
            email_verifie=Count("id", filter=Q(email_verifie=True)),
            inscrits_ce_mois=Count("id", filter=Q(date_joined__gte=debut_mois)),
        )
        # Un "vendeur" n'est pas un role : c'est un compte qui a publie.
        agregats["vendeurs"] = (
            User.objects.filter(
                produits__status__in=[
                    StatutProduit.ACTIVE, StatutProduit.OUT_OF_STOCK
                ]
            )
            .distinct()
            .count()
        )
        return agregats

    # ------------------------------------------------------------- annonces
    @staticmethod
    def annonces() -> dict:
        par_statut = dict(
            Produit.objects.values_list("status")
            .annotate(total=Count("id"))
            .values_list("status", "total")
        )
        return {
            "total": Produit.objects.count(),
            "par_statut": {
                statut: par_statut.get(statut, 0)
                for statut in StatutProduit.values
            },
            "visibles": Produit.objects.visibles().count(),
            "mises_en_avant": Produit.objects.filter(est_mis_en_avant=True).count(),
            "vues_cumulees": Produit.objects.aggregate(
                total=Coalesce(Sum("nombre_vues"), Value(0))
            )["total"],
        }

    # --------------------------------------------------------- reservations
    @staticmethod
    def reservations() -> dict:
        agregats = Reservation.objects.aggregate(
            total=Count("id"),
            en_attente=Count("id", filter=Q(statut=StatutReservation.PENDING)),
            acceptees=Count("id", filter=Q(statut=StatutReservation.CONFIRMED)),
            annulees=Count("id", filter=Q(statut=StatutReservation.CANCELLED)),
            expirees=Count("id", filter=Q(statut=StatutReservation.EXPIRED)),
            transformees=Count("id", filter=Q(statut=StatutReservation.FULFILLED)),
        )
        jugees = (
            agregats["transformees"] + agregats["annulees"] + agregats["expirees"]
        )
        agregats["taux_de_transformation"] = (
            round(agregats["transformees"] * 100 / jugees, 2) if jugees else None
        )
        return agregats

    # ---------------------------------------------------------------- ventes
    @staticmethod
    def ventes() -> dict:
        comptages = Vente.objects.aggregate(
            total=Count("id"),
            **{
                f"statut_{statut.lower()}": Count("id", filter=Q(statut=statut))
                for statut in StatutVente.values
            },
        )
        lignes = LigneVente.objects.filter(
            vente__statut__in=VenteQuerySet.STATUTS_COMPTABILISABLES
        )
        financier = lignes.aggregate(
            chiffre_affaires=Coalesce(Sum("sous_total"), ZERO),
            quantite_vendue=Coalesce(Sum("quantite"), Value(0)),
        )
        return {
            **comptages,
            **financier,
            "ventes_comptabilisees": Vente.objects.comptabilisables().count(),
            "panier_moyen": (
                round(
                    financier["chiffre_affaires"]
                    / Vente.objects.comptabilisables().count(),
                    2,
                )
                if Vente.objects.comptabilisables().exists()
                else Decimal("0")
            ),
            "devise": "BIF",
        }

    # ------------------------------------------------------------ messagerie
    @staticmethod
    def messagerie() -> dict:
        return {
            "conversations": Conversation.objects.count(),
            "messages": Message.objects.count(),
            "conversations_bloquees": Conversation.objects.filter(
                bloquee_par__isnull=False
            ).count(),
        }

    # ----------------------------------------------------------- evaluations
    @staticmethod
    def evaluations() -> dict:
        agregats = Evaluation.objects.aggregate(
            total=Count("id"),
            visibles=Count("id", filter=Q(statut=StatutEvaluation.VISIBLE)),
            masquees=Count("id", filter=Q(statut=StatutEvaluation.MASQUEE)),
            retirees=Count("id", filter=Q(statut=StatutEvaluation.RETIREE)),
        )
        moyennes = Evaluation.objects.valides().aggregate(
            note_produit=Avg("note_produit"), note_vendeur=Avg("note_vendeur")
        )
        agregats["note_produit_moyenne"] = (
            round(moyennes["note_produit"], 2)
            if moyennes["note_produit"] is not None
            else None
        )
        agregats["note_vendeur_moyenne"] = (
            round(moyennes["note_vendeur"], 2)
            if moyennes["note_vendeur"] is not None
            else None
        )
        return agregats

    # ------------------------------------------------------------ moderation
    @staticmethod
    def moderation() -> dict:
        return {
            "signalements_conversations_en_attente": (
                SignalementConversation.objects.filter(traite_le__isnull=True).count()
            ),
            "signalements_avis_en_attente": (
                SignalementEvaluation.objects.filter(traite_le__isnull=True).count()
            ),
            "annonces_en_attente_de_moderation": Produit.objects.filter(
                status=StatutProduit.PENDING
            ).count(),
            "annonces_retirees": Produit.objects.filter(
                status=StatutProduit.REMOVED
            ).count(),
        }
