"""Service metier : cycle de vie d'une annonce et coherence du stock.

Les transitions de statut sont centralisees ici pour que le module 8
(reservations) et le module 9 (ventes) appliquent exactement les memes
regles que les actions du vendeur.
"""
from django.db import transaction
from django.utils import timezone
from rest_framework import serializers

from modules.products.models import Produit, StatutProduit


class ProduitStatutService:
    """Regles de passage d'un statut a l'autre."""

    # Statuts depuis lesquels le vendeur peut publier son annonce.
    PUBLIABLES = (
        StatutProduit.DRAFT,
        StatutProduit.PAUSED,
        StatutProduit.ARCHIVED,
        StatutProduit.OUT_OF_STOCK,
        StatutProduit.ACTIVE,
    )
    PAUSABLES = (StatutProduit.ACTIVE, StatutProduit.OUT_OF_STOCK)

    @staticmethod
    @transaction.atomic
    def publier(produit: Produit) -> Produit:
        if produit.status == StatutProduit.REMOVED:
            raise serializers.ValidationError(
                {
                    "status": (
                        "Cette annonce a ete retiree par l'administration : "
                        "elle ne peut pas etre republiee."
                    )
                }
            )
        if produit.status not in ProduitStatutService.PUBLIABLES:
            raise serializers.ValidationError(
                {"status": f"Publication impossible depuis le statut {produit.status}."}
            )

        premiere_publication = produit.publie_le is None

        produit.status = (
            StatutProduit.ACTIVE
            if produit.quantite_disponible > 0
            else StatutProduit.OUT_OF_STOCK
        )
        if premiere_publication:
            produit.publie_le = timezone.now()
        produit.save(update_fields=["status", "publie_le", "updated_at"])

        # Module 12 : les abonnes du vendeur sont prevenus, mais seulement
        # a la premiere mise en ligne. Une annonce mise en pause puis
        # republiee ne doit pas renotifier tout le monde.
        if premiere_publication:
            from modules.notifications.services import NotificationService

            NotificationService.nouvelle_annonce_de_vendeur_suivi(produit)

        return produit

    @staticmethod
    @transaction.atomic
    def mettre_en_pause(produit: Produit) -> Produit:
        if produit.status not in ProduitStatutService.PAUSABLES:
            raise serializers.ValidationError(
                {"status": f"Mise en pause impossible depuis le statut {produit.status}."}
            )
        produit.status = StatutProduit.PAUSED
        produit.save(update_fields=["status", "updated_at"])
        return produit

    @staticmethod
    @transaction.atomic
    def archiver(produit: Produit) -> Produit:
        """Suppression douce : l'historique des ventes doit rester lisible."""
        if produit.status == StatutProduit.REMOVED:
            raise serializers.ValidationError(
                {"status": "Annonce deja retiree par l'administration."}
            )
        produit.status = StatutProduit.ARCHIVED
        produit.save(update_fields=["status", "updated_at"])
        return produit

    @staticmethod
    @transaction.atomic
    def synchroniser_statut_stock(produit: Produit) -> Produit:
        """Aligne le statut sur le stock reellement disponible.

        - plus aucune quantite disponible et annonce ACTIVE -> OUT_OF_STOCK
        - du stock de nouveau disponible et annonce OUT_OF_STOCK -> ACTIVE

        Les statuts DRAFT, PAUSED, ARCHIVED et REMOVED ne sont jamais
        modifies automatiquement : ils relevent d'une decision du vendeur
        ou de l'administration.
        """
        disponible = produit.quantite_disponible

        if disponible == 0 and produit.status == StatutProduit.ACTIVE:
            produit.status = StatutProduit.OUT_OF_STOCK
            produit.save(update_fields=["status", "updated_at"])
        elif disponible > 0 and produit.status == StatutProduit.OUT_OF_STOCK:
            produit.status = StatutProduit.ACTIVE
            produit.save(update_fields=["status", "updated_at"])

        ProduitStatutService._alerter_sur_le_stock(produit, disponible)
        return produit

    @staticmethod
    def _alerter_sur_le_stock(produit, disponible: int) -> None:
        """Module 12 : rupture et stock faible.

        Les alertes ne concernent que les annonces publiees : prevenir un
        vendeur que son brouillon est "epuise" n'aurait aucun sens.

        Le service de notification ne cree pas de doublon tant que l'alerte
        precedente n'est pas lue : sans cela, chaque vente d'un produit a
        stock faible ferait sonner le telephone du vendeur.
        """
        if produit.status not in (StatutProduit.ACTIVE, StatutProduit.OUT_OF_STOCK):
            return

        from modules.notifications.services import NotificationService

        if disponible == 0:
            NotificationService.stock_epuise(produit)
            # Ceux qui avaient mis l'annonce en favori sont prevenus aussi.
            NotificationService.favori_indisponible(produit)
        elif disponible <= NotificationService.seuil_de_stock_faible():
            NotificationService.stock_presque_epuise(produit, disponible)
