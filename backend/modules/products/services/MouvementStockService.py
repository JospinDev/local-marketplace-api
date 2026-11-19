"""Service d'ecriture de l'historique des mouvements de stock.

Toute modification de `Inventaire` faite par les modules Reservations (8) et
Ventes (9) passe par ici : la quantite est appliquee, puis tracee avec une
photographie du stock resultant. Cela garantit qu'un stock ne peut pas
bouger sans laisser d'explication.

Les appels se font TOUJOURS dans la transaction de l'appelant, apres un
`select_for_update()` sur l'inventaire : ce service ne verrouille rien
lui-meme, il n'invente pas de section critique.
"""
from modules.products.models import Inventaire, MouvementStock, TypeMouvementStock


class MouvementStockService:
    """Applique un mouvement de stock et l'enregistre."""

    @staticmethod
    def tracer(
        inventaire: Inventaire,
        type_mouvement: str,
        quantite: int,
        reference_type: str = "",
        reference_id: int | None = None,
        utilisateur=None,
        commentaire: str = "",
    ) -> MouvementStock:
        """Enregistre un mouvement deja applique a l'inventaire."""
        return MouvementStock.objects.create(
            produit_id=inventaire.produit_id,
            type_mouvement=type_mouvement,
            quantite=quantite,
            reference_type=reference_type,
            reference_id=reference_id,
            effectue_par=utilisateur if utilisateur and utilisateur.is_authenticated else None,
            commentaire=commentaire,
            quantite_totale_apres=inventaire.quantite_totale,
            quantite_reservee_apres=inventaire.quantite_reservee,
            quantite_vendue_apres=inventaire.quantite_vendue,
        )

    @staticmethod
    def reserver(inventaire, quantite, reference_id, utilisateur=None, commentaire=""):
        inventaire.quantite_reservee += quantite
        inventaire.save(update_fields=["quantite_reservee", "updated_at"])
        return MouvementStockService.tracer(
            inventaire, TypeMouvementStock.RESERVATION, quantite,
            "reservation", reference_id, utilisateur, commentaire,
        )

    @staticmethod
    def liberer(inventaire, quantite, reference_id, utilisateur=None, commentaire=""):
        """Rend disponible une quantite reservee.

        Ne touche JAMAIS `quantite_vendue` : une reservation annulee ou
        expiree ne doit pas compter comme une vente (regle du cahier des
        charges).
        """
        inventaire.quantite_reservee = max(inventaire.quantite_reservee - quantite, 0)
        inventaire.save(update_fields=["quantite_reservee", "updated_at"])
        return MouvementStockService.tracer(
            inventaire, TypeMouvementStock.LIBERATION, quantite,
            "reservation", reference_id, utilisateur, commentaire,
        )

    @staticmethod
    def vendre(inventaire, quantite, reference_id, utilisateur=None, commentaire=""):
        inventaire.quantite_vendue += quantite
        inventaire.save(update_fields=["quantite_vendue", "updated_at"])
        return MouvementStockService.tracer(
            inventaire, TypeMouvementStock.VENTE, quantite,
            "vente", reference_id, utilisateur, commentaire,
        )

    @staticmethod
    def annuler_vente(inventaire, quantite, reference_id, utilisateur=None, commentaire=""):
        """Remet en disponible une quantite precedemment vendue."""
        inventaire.quantite_vendue = max(inventaire.quantite_vendue - quantite, 0)
        inventaire.save(update_fields=["quantite_vendue", "updated_at"])
        return MouvementStockService.tracer(
            inventaire, TypeMouvementStock.ANNULATION_VENTE, quantite,
            "vente", reference_id, utilisateur, commentaire,
        )
