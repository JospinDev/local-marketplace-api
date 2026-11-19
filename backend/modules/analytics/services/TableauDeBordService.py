"""Service du tableau de bord vendeur (module 10).

Tout est calcule en base, par agregation : aucune boucle Python sur des
milliers de lignes, et aucun compteur denormalise a maintenir (donc rien a
resynchroniser le jour ou une vente est annulee).

La regle qui gouverne tout le module est celle du paragraphe E du cahier des
charges :

    "Le chiffre d'affaires ne doit prendre en compte que les ventes
     confirmees."

    Reservations      5   250 000 BIF
    Ventes confirmees 3   150 000 BIF
    -> le revenu declare est de 150 000 BIF, et non de 250 000 BIF.

Les revenus se lisent donc TOUJOURS sur `LigneVente`, filtree par
`VenteQuerySet.STATUTS_COMPTABILISABLES`, et jamais sur les reservations.
La valeur des reservations en cours est exposee a part, clairement nommee.
"""
from datetime import timedelta
from decimal import Decimal

from django.db.models import (
    Avg,
    Count,
    DecimalField,
    ExpressionWrapper,
    F,
    Q,
    Sum,
    Value,
)
from django.db.models.functions import Coalesce
from django.utils import timezone

from modules.messaging.models import Conversation
from modules.products.models import Inventaire, Produit, StatutProduit
from modules.reservations.models import Reservation, StatutReservation
from modules.reviews.models import Evaluation
from modules.sales.models import LigneVente, StatutVente, Vente, VenteQuerySet

ZERO = Value(Decimal("0"), output_field=DecimalField(max_digits=18, decimal_places=2))


class TableauDeBordService:
    """Indicateurs commerciaux et financiers d'un vendeur."""

    # ------------------------------------------------------------- outillage
    @staticmethod
    def _bornes_temporelles():
        """Debuts de journee, de semaine (lundi) et de mois, heure locale."""
        maintenant = timezone.localtime()
        debut_jour = maintenant.replace(hour=0, minute=0, second=0, microsecond=0)
        return {
            "jour": debut_jour,
            "semaine": debut_jour - timedelta(days=debut_jour.weekday()),
            "mois": debut_jour.replace(day=1),
        }

    @staticmethod
    def _lignes_comptabilisables(vendeur):
        """Lignes de vente qui comptent comme revenu.

        Le filtre porte sur le STATUT de la vente : une vente annulee ou
        remboursee sort du chiffre d'affaires sans que ses lignes soient
        modifiees (les prix passes restent lisibles).
        """
        return LigneVente.objects.filter(
            vente__vendeur=vendeur,
            vente__statut__in=VenteQuerySet.STATUTS_COMPTABILISABLES,
        )

    @staticmethod
    def _total(queryset) -> dict:
        agregats = queryset.aggregate(
            revenu=Coalesce(Sum("sous_total"), ZERO),
            quantite=Coalesce(Sum("quantite"), Value(0)),
        )
        return {
            "revenu": agregats["revenu"],
            "quantite": agregats["quantite"],
        }

    # ------------------------------------------------------- A. vue generale
    @staticmethod
    def vue_generale(vendeur) -> dict:
        """Section A du cahier des charges."""
        produits = Produit.objects.de(vendeur)
        disponible = Q(
            inventaire__quantite_totale__gt=F("inventaire__quantite_reservee")
            + F("inventaire__quantite_vendue")
        )

        comptages_produits = produits.aggregate(
            publies=Count(
                "id",
                filter=Q(
                    status__in=[StatutProduit.ACTIVE, StatutProduit.OUT_OF_STOCK]
                ),
            ),
            disponibles=Count(
                "id", filter=Q(status=StatutProduit.ACTIVE) & disponible
            ),
            en_rupture=Count("id", filter=Q(status=StatutProduit.OUT_OF_STOCK)),
            total=Count("id"),
        )

        reservations = Reservation.objects.recues_par(vendeur).aggregate(
            en_attente=Count("id", filter=Q(statut=StatutReservation.PENDING)),
            en_cours=Count("id", filter=Q(statut=StatutReservation.CONFIRMED)),
        )

        ventes = Vente.objects.vendues_par(vendeur).aggregate(
            confirmees=Count(
                "id", filter=Q(statut__in=VenteQuerySet.STATUTS_COMPTABILISABLES)
            ),
            clients=Count(
                "acheteur",
                filter=Q(statut__in=VenteQuerySet.STATUTS_COMPTABILISABLES),
                distinct=True,
            ),
        )

        reputation = Evaluation.objects.recues_par(vendeur).moyennes()

        return {
            "produits_publies": comptages_produits["publies"],
            "produits_disponibles": comptages_produits["disponibles"],
            "produits_en_rupture": comptages_produits["en_rupture"],
            "produits_total": comptages_produits["total"],
            "demandes_de_reservation_en_attente": reservations["en_attente"],
            "reservations_en_cours": reservations["en_cours"],
            "ventes_confirmees": ventes["confirmees"],
            "nombre_clients": ventes["clients"],
            "nombre_conversations": Conversation.objects.filter(
                vendeur=vendeur
            ).count(),
            "note_moyenne_vendeur": reputation["note_vendeur"],
            "nombre_evaluations": reputation["nombre_evaluations"],
        }

    # -------------------------------------------------- B. gestion financiere
    @staticmethod
    def revenus(vendeur) -> dict:
        """Section B : revenus, par periode, par produit, par categorie.

        Les periodes se mesurent sur `confirmee_le`, la date a laquelle le
        vendeur a declare avoir recu le paiement : c'est le moment ou
        l'argent est entre, pas celui ou la vente a ete saisie.
        """
        lignes = TableauDeBordService._lignes_comptabilisables(vendeur)
        bornes = TableauDeBordService._bornes_temporelles()

        total = TableauDeBordService._total(lignes)
        periodes = {
            nom: TableauDeBordService._total(
                lignes.filter(vente__confirmee_le__gte=debut)
            )["revenu"]
            for nom, debut in bornes.items()
        }

        par_produit = [
            {
                "produit": ligne["produit"],
                "titre": ligne["produit__titre"],
                "quantite_vendue": ligne["quantite_vendue"],
                "revenu": ligne["revenu"],
            }
            for ligne in lignes.values("produit", "produit__titre")
            .annotate(
                quantite_vendue=Sum("quantite"),
                revenu=Coalesce(Sum("sous_total"), ZERO),
            )
            .order_by("-revenu")
        ]

        par_categorie = [
            {
                "categorie": ligne["produit__categorie"],
                "nom": ligne["produit__categorie__nom"],
                "quantite_vendue": ligne["quantite_vendue"],
                "revenu": ligne["revenu"],
            }
            for ligne in lignes.values(
                "produit__categorie", "produit__categorie__nom"
            )
            .annotate(
                quantite_vendue=Sum("quantite"),
                revenu=Coalesce(Sum("sous_total"), ZERO),
            )
            .order_by("-revenu")
        ]

        return {
            "chiffre_affaires_total": total["revenu"],
            "quantite_vendue": total["quantite"],
            "revenus_du_jour": periodes["jour"],
            "revenus_de_la_semaine": periodes["semaine"],
            "revenus_du_mois": periodes["mois"],
            "valeur_reservations_en_cours": (
                TableauDeBordService.valeur_reservations_en_cours(vendeur)
            ),
            "ventes_en_attente_de_confirmation": Vente.objects.vendues_par(
                vendeur
            )
            .filter(statut=StatutVente.INITIATED)
            .count(),
            "par_produit": par_produit,
            "par_categorie": par_categorie,
            "devise": "BIF",
        }

    @staticmethod
    def valeur_reservations_en_cours(vendeur):
        """Valeur des quantites mises de cote, au prix actuel des annonces.

        Exposee a part, et jamais additionnee au chiffre d'affaires : une
        reservation n'est pas un revenu (regle du module 8).
        """
        valeur = ExpressionWrapper(
            F("quantite_confirmee") * F("produit__prix"),
            output_field=DecimalField(max_digits=18, decimal_places=2),
        )
        return (
            Reservation.objects.recues_par(vendeur)
            .filter(statut=StatutReservation.CONFIRMED)
            .aggregate(total=Coalesce(Sum(valeur), ZERO))["total"]
        )

    # ------------------------------------------------------ C. gestion du stock
    @staticmethod
    def stocks(vendeur) -> dict:
        """Section C : les quatre quantites, en total et par produit."""
        inventaires = Inventaire.objects.filter(produit__owner=vendeur)

        disponible_expression = ExpressionWrapper(
            F("quantite_totale") - F("quantite_reservee") - F("quantite_vendue"),
            output_field=DecimalField(max_digits=18, decimal_places=2),
        )
        valeur_stock = ExpressionWrapper(
            (
                F("quantite_totale") - F("quantite_reservee") - F("quantite_vendue")
            )
            * F("produit__prix"),
            output_field=DecimalField(max_digits=18, decimal_places=2),
        )

        # Les alias d'agregation sont volontairement prefixes : un alias
        # nomme `quantite_reservee` masquerait la COLONNE du meme nom dans
        # l'expression `valeur_stock` calculee au sein du meme aggregate(),
        # et Django refuserait la requete ("is an aggregate").
        sommes = inventaires.aggregate(
            total_stock=Coalesce(Sum("quantite_totale"), Value(0)),
            total_reservee=Coalesce(Sum("quantite_reservee"), Value(0)),
            total_vendue=Coalesce(Sum("quantite_vendue"), Value(0)),
            total_valeur_disponible=Coalesce(Sum(valeur_stock), ZERO),
        )
        totaux = {
            "stock_total": sommes["total_stock"],
            "quantite_reservee": sommes["total_reservee"],
            "quantite_vendue": sommes["total_vendue"],
            "quantite_disponible": (
                sommes["total_stock"]
                - sommes["total_reservee"]
                - sommes["total_vendue"]
            ),
            "valeur_stock_disponible": sommes["total_valeur_disponible"],
            "valeur_reservations_en_cours": (
                TableauDeBordService.valeur_reservations_en_cours(vendeur)
            ),
        }

        totaux["par_produit"] = [
            {
                "produit": ligne["produit_id"],
                "titre": ligne["produit__titre"],
                "statut": ligne["produit__status"],
                "prix": ligne["produit__prix"],
                "quantite_totale": ligne["quantite_totale"],
                "quantite_reservee": ligne["quantite_reservee"],
                "quantite_vendue": ligne["quantite_vendue"],
                "quantite_disponible": int(ligne["disponible"]),
            }
            for ligne in inventaires.annotate(disponible=disponible_expression)
            .values(
                "produit_id", "produit__titre", "produit__status", "produit__prix",
                "quantite_totale", "quantite_reservee", "quantite_vendue",
                "disponible",
            )
            .order_by("produit__titre")
        ]
        return totaux

    # ---------------------------------------------------------- D. historique
    @staticmethod
    def compteurs_reservations(vendeur) -> dict:
        """Section D : issues des reservations recues."""
        return Reservation.objects.recues_par(vendeur).aggregate(
            en_attente=Count("id", filter=Q(statut=StatutReservation.PENDING)),
            acceptees=Count("id", filter=Q(statut=StatutReservation.CONFIRMED)),
            annulees=Count("id", filter=Q(statut=StatutReservation.CANCELLED)),
            expirees=Count("id", filter=Q(statut=StatutReservation.EXPIRED)),
            transformees_en_vente=Count(
                "id", filter=Q(statut=StatutReservation.FULFILLED)
            ),
            quantite_immobilisee=Coalesce(
                Sum(
                    "quantite_confirmee",
                    filter=Q(statut=StatutReservation.CONFIRMED),
                ),
                Value(0),
            ),
        )

    @staticmethod
    def taux_de_transformation(vendeur) -> float | None:
        """Part des reservations acceptees qui ont fini en vente.

        Indicateur demande au chapitre 11 du cahier des charges ("taux de
        transformation des reservations en ventes"). Les demandes encore en
        attente ou toujours en cours sont exclues du denominateur : leur sort
        n'est pas joue.
        """
        compteurs = Reservation.objects.recues_par(vendeur).aggregate(
            transformees=Count("id", filter=Q(statut=StatutReservation.FULFILLED)),
            perdues=Count(
                "id",
                filter=Q(
                    statut__in=[
                        StatutReservation.CANCELLED, StatutReservation.EXPIRED
                    ]
                ),
            ),
        )
        jugees = compteurs["transformees"] + compteurs["perdues"]
        if jugees == 0:
            return None
        return round(compteurs["transformees"] * 100 / jugees, 2)

    @staticmethod
    def produits_les_plus_vendus(vendeur, limite: int = 10) -> list:
        lignes = (
            TableauDeBordService._lignes_comptabilisables(vendeur)
            .values("produit", "produit__titre", "produit__prix")
            .annotate(
                quantite_vendue=Sum("quantite"),
                revenu=Coalesce(Sum("sous_total"), ZERO),
                nombre_ventes=Count("vente", distinct=True),
            )
            .order_by("-quantite_vendue", "-revenu")[:limite]
        )
        return [
            {
                "produit": ligne["produit"],
                "titre": ligne["produit__titre"],
                "prix": ligne["produit__prix"],
                "quantite_vendue": ligne["quantite_vendue"],
                "revenu": ligne["revenu"],
                "nombre_ventes": ligne["nombre_ventes"],
            }
            for ligne in lignes
        ]

    @staticmethod
    def produits_les_plus_consultes(vendeur, limite: int = 10) -> list:
        produits = (
            Produit.objects.de(vendeur)
            .filter(status__in=[StatutProduit.ACTIVE, StatutProduit.OUT_OF_STOCK])
            .annotate(
                note_moyenne=Avg(
                    "evaluations__note_produit",
                    filter=Q(evaluations__statut="VISIBLE"),
                )
            )
            .order_by("-nombre_vues")[:limite]
        )
        return [
            {
                "produit": produit.pk,
                "titre": produit.titre,
                "prix": produit.prix,
                "nombre_vues": produit.nombre_vues,
                "quantite_disponible": produit.quantite_disponible,
                "note_moyenne": (
                    round(produit.note_moyenne, 2)
                    if produit.note_moyenne is not None
                    else None
                ),
            }
            for produit in produits
        ]
