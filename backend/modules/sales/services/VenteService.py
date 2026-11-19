"""Service metier des ventes (module 9).

Comme pour les reservations, c'est le seul chemin d'ecriture : il est appele
aussi bien par `POST /sales/` que par `POST /reservations/{id}/complete/`,
pour que les deux portes d'entree appliquent exactement les memes controles.

La vente partielle est le scenario central du cahier des charges :

    Le client a reserve 3 pantalons a 35 000 BIF. Il vient en chercher 2 et
    paie 70 000 BIF.

Le service doit alors, dans UNE transaction :

1. enregistrer la vente de 2 unites au prix convenu ;
2. deduire 2 unites du stock physique (`quantite_vendue += 2`) ;
3. liberer les 3 unites reservees (`quantite_reservee -= 3`) ;
4. rendre la 3e unite disponible a nouveau ;
5. enregistrer le montant reellement encaisse.

Les etapes 2 et 3 se font ensemble : sans cela, l'unite non achetee
resterait bloquee indefiniment.
"""
from decimal import Decimal

from django.db import transaction
from django.utils import timezone
from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied

from modules.notifications.services import NotificationService
from modules.products.services import MouvementStockService, ProduitStatutService
from modules.reservations.models import Reservation, StatutReservation
from modules.reservations.services import ReservationService
from modules.sales.models import (
    LigneVente,
    MoyenPaiement,
    StatutPaiement,
    StatutVente,
    Vente,
)


class VenteService:
    """Declaration, confirmation et annulation des ventes."""

    # ---------------------------------------------- vente sur reservation
    @staticmethod
    def enregistrer_depuis_reservation(
        reservation: Reservation,
        vendeur,
        quantite: int | None = None,
        prix_unitaire: Decimal | None = None,
        moyen_paiement: str = MoyenPaiement.CASH,
        note: str = "",
    ) -> Vente:
        """Transforme une reservation acceptee en vente (eventuellement partielle).

        L'expiration est traitee hors de la transaction de vente : sinon
        l'erreur levee juste apres annulerait l'expiration elle-meme et le
        stock resterait immobilise.
        """
        if reservation.vendeur_id != vendeur.pk:
            raise PermissionDenied(
                "Seul le vendeur de l'annonce peut declarer cette vente."
            )
        if reservation.est_expiree:
            ReservationService.expirer(reservation)
            raise serializers.ValidationError(
                {
                    "statut": (
                        "Cette reservation a expire et son stock a ete libere : "
                        "le vendeur doit en creer une nouvelle ou declarer une "
                        "vente directe."
                    )
                }
            )
        return VenteService._vendre_sous_verrou(
            reservation, vendeur, quantite, prix_unitaire, moyen_paiement, note
        )

    @staticmethod
    @transaction.atomic
    def _vendre_sous_verrou(
        reservation, vendeur, quantite, prix_unitaire, moyen_paiement, note
    ) -> Vente:
        reservation = (
            Reservation.objects.select_for_update()
            .select_related("produit", "acheteur")
            .get(pk=reservation.pk)
        )

        if reservation.statut != StatutReservation.CONFIRMED:
            raise serializers.ValidationError(
                {
                    "statut": (
                        "Seule une reservation acceptee peut etre transformee "
                        f"en vente (statut actuel : {reservation.statut})."
                    )
                }
            )
        quantite = reservation.quantite_confirmee if quantite is None else quantite
        if quantite < 1:
            raise serializers.ValidationError(
                {"quantite": "La quantite vendue doit etre superieure a zero."}
            )
        if quantite > reservation.quantite_confirmee:
            raise serializers.ValidationError(
                {
                    "quantite": (
                        "La quantite vendue ne peut pas depasser la quantite "
                        f"reservee ({reservation.quantite_confirmee})."
                    )
                }
            )

        produit = reservation.produit
        prix = VenteService._prix_applique(produit, prix_unitaire)

        inventaire = ReservationService._verrouiller_inventaire(produit.pk)

        # Etape 3 et 4 : la reservation entiere est liberee...
        MouvementStockService.liberer(
            inventaire,
            reservation.quantite_confirmee,
            reservation.pk,
            utilisateur=vendeur,
            commentaire=(
                f"Cloture de la reservation {reservation.pk} : "
                f"{quantite} vendue(s), "
                f"{reservation.quantite_confirmee - quantite} liberee(s)"
            ),
        )
        # ... puis seule la quantite reellement achetee devient du vendu.
        # Le solde est deja redevenu disponible par la liberation ci-dessus.
        MouvementStockService.vendre(
            inventaire,
            quantite,
            reservation.pk,
            utilisateur=vendeur,
            commentaire=f"Vente issue de la reservation {reservation.pk}",
        )

        vente = VenteService._creer_vente(
            acheteur=reservation.acheteur,
            vendeur=vendeur,
            produit=produit,
            quantite=quantite,
            prix_unitaire=prix,
            moyen_paiement=moyen_paiement,
            note=note,
            reservation=reservation,
        )

        reservation.statut = StatutReservation.FULFILLED
        reservation.quantite_livree = quantite
        reservation.cloturee_le = timezone.now()
        reservation.cloturee_par = ""
        reservation.motif = (
            "Transformee en vente."
            if quantite == reservation.quantite_confirmee
            else (
                f"Vente partielle : {quantite} achetee(s) sur "
                f"{reservation.quantite_confirmee}, le solde est libere."
            )
        )
        reservation.save(
            update_fields=[
                "statut", "quantite_livree", "cloturee_le", "cloturee_par",
                "motif", "updated_at",
            ]
        )

        ProduitStatutService.synchroniser_statut_stock(inventaire.produit)
        return vente

    # -------------------------------------------------- vente directe
    @staticmethod
    @transaction.atomic
    def enregistrer_vente_directe(
        produit,
        vendeur,
        acheteur,
        quantite: int,
        prix_unitaire: Decimal | None = None,
        moyen_paiement: str = MoyenPaiement.CASH,
        note: str = "",
    ) -> Vente:
        """Vente sans reservation prealable (client venu directement).

        Le stock disponible est verifie sous verrou, exactement comme pour
        une acceptation de reservation.
        """
        if produit.owner_id != vendeur.pk:
            raise PermissionDenied(
                "Vous ne pouvez declarer une vente que sur vos propres annonces."
            )
        if acheteur.pk == vendeur.pk:
            raise serializers.ValidationError(
                {"acheteur": "Vous ne pouvez pas vous vendre a vous-meme."}
            )
        if quantite < 1:
            raise serializers.ValidationError(
                {"quantite": "La quantite vendue doit etre superieure a zero."}
            )

        inventaire = ReservationService._verrouiller_inventaire(produit.pk)
        disponible = inventaire.quantite_disponible
        if quantite > disponible:
            raise serializers.ValidationError(
                {
                    "quantite": (
                        f"Stock insuffisant : {disponible} unite(s) "
                        "disponible(s). Les quantites deja reservees par "
                        "d'autres acheteurs ne sont pas vendables."
                    )
                }
            )

        prix = VenteService._prix_applique(inventaire.produit, prix_unitaire)
        vente = VenteService._creer_vente(
            acheteur=acheteur,
            vendeur=vendeur,
            produit=inventaire.produit,
            quantite=quantite,
            prix_unitaire=prix,
            moyen_paiement=moyen_paiement,
            note=note,
            reservation=None,
        )

        MouvementStockService.vendre(
            inventaire,
            quantite,
            vente.pk,
            utilisateur=vendeur,
            commentaire=f"Vente directe {vente.pk}",
        )
        ProduitStatutService.synchroniser_statut_stock(inventaire.produit)
        return vente

    # ----------------------------------------------------- confirmations
    @staticmethod
    @transaction.atomic
    def confirmer_paiement(vente: Vente, vendeur) -> Vente:
        """Le vendeur declare avoir recu le paiement : INITIATED -> PAID."""
        if vente.vendeur_id != vendeur.pk:
            raise PermissionDenied("Seul le vendeur peut confirmer le paiement.")
        if vente.statut != StatutVente.INITIATED:
            raise serializers.ValidationError(
                {
                    "statut": (
                        "Seule une vente en attente de confirmation peut etre "
                        f"confirmee (statut actuel : {vente.statut})."
                    )
                }
            )

        vente.statut = StatutVente.PAID
        vente.statut_paiement = StatutPaiement.RECU
        vente.confirmee_le = timezone.now()
        vente.save(
            update_fields=["statut", "statut_paiement", "confirmee_le", "updated_at"]
        )
        return vente

    @staticmethod
    @transaction.atomic
    def confirmer_reception(vente: Vente, acheteur) -> Vente:
        """L'acheteur confirme avoir recu le produit : PAID -> COMPLETED.

        Controle recommande par le cahier des charges : il permet de
        detecter les ventes declarees a tort et conditionne la fiabilite
        des evaluations (module 11).
        """
        if vente.acheteur_id != acheteur.pk:
            raise PermissionDenied("Seul l'acheteur peut confirmer la reception.")
        if vente.statut != StatutVente.PAID:
            raise serializers.ValidationError(
                {
                    "statut": (
                        "Le vendeur doit d'abord confirmer le paiement "
                        f"(statut actuel : {vente.statut})."
                    )
                }
            )

        vente.statut = StatutVente.COMPLETED
        vente.confirmee_par_acheteur_le = timezone.now()
        vente.save(
            update_fields=["statut", "confirmee_par_acheteur_le", "updated_at"]
        )
        # Module 12 : le vendeur apprend que le client a bien recu.
        NotificationService.achat_confirme(vente)
        return vente

    # ----------------------------------------------------------- annulation
    @staticmethod
    @transaction.atomic
    def annuler(vente: Vente, utilisateur, motif: str) -> Vente:
        """Annule une vente et remet les quantites en disponible.

        Regles du paragraphe 8.2 :

        - seul le vendeur proprietaire peut annuler ;
        - le motif est obligatoire : une vente confirmee ne doit pas etre
          modifiee silencieusement ;
        - les lignes et leurs prix ne sont JAMAIS reecrits ; l'annulation
          produit un mouvement de stock `ANNULATION_VENTE` qui sert de
          trace d'audit ;
        - si le paiement avait ete declare recu, la vente part en REFUNDED
          plutot qu'en CANCELLED : le remboursement doit rester visible.
        """
        if vente.vendeur_id != utilisateur.pk:
            raise PermissionDenied("Seul le vendeur peut annuler une vente.")
        if not motif or not motif.strip():
            raise serializers.ValidationError(
                {
                    "motif": (
                        "Le motif est obligatoire : une vente annulee doit "
                        "laisser une trace explicable."
                    )
                }
            )
        if vente.est_cloturee:
            raise serializers.ValidationError(
                {"statut": f"Cette vente est deja cloturee (statut {vente.statut})."}
            )

        paiement_recu = vente.statut_paiement == StatutPaiement.RECU

        for ligne in vente.lignes.select_related("produit").all():
            inventaire = ReservationService._verrouiller_inventaire(ligne.produit_id)
            MouvementStockService.annuler_vente(
                inventaire,
                ligne.quantite,
                vente.pk,
                utilisateur=utilisateur,
                commentaire=f"Annulation de la vente {vente.pk} : {motif.strip()}",
            )
            ProduitStatutService.synchroniser_statut_stock(inventaire.produit)

        vente.statut = StatutVente.REFUNDED if paiement_recu else StatutVente.CANCELLED
        if paiement_recu:
            vente.statut_paiement = StatutPaiement.REMBOURSE
        vente.annulee_le = timezone.now()
        vente.motif_annulation = motif.strip()
        vente.save(
            update_fields=[
                "statut", "statut_paiement", "annulee_le",
                "motif_annulation", "updated_at",
            ]
        )
        return vente

    # --------------------------------------------------------------- interne
    @staticmethod
    def _prix_applique(produit, prix_unitaire) -> Decimal:
        """Prix retenu : celui convenu, sinon le prix affiche de l'annonce."""
        if prix_unitaire is None:
            return produit.prix
        prix = Decimal(prix_unitaire)
        if prix < 0:
            raise serializers.ValidationError(
                {"prix_unitaire": "Le prix ne peut pas etre negatif."}
            )
        return prix

    @staticmethod
    def _creer_vente(
        acheteur, vendeur, produit, quantite, prix_unitaire,
        moyen_paiement, note, reservation,
    ) -> Vente:
        vente = Vente.objects.create(
            reservation=reservation,
            acheteur=acheteur,
            vendeur=vendeur,
            moyen_paiement=moyen_paiement,
            note=note,
            devise=produit.devise,
            statut=StatutVente.INITIATED,
            statut_paiement=StatutPaiement.EN_ATTENTE,
        )
        LigneVente.objects.create(
            vente=vente,
            produit=produit,
            quantite=quantite,
            prix_unitaire=prix_unitaire,
        )
        vente.recalculer_montant()
        return vente
