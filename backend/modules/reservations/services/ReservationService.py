"""Service metier des reservations (module 8).

C'est le SEUL endroit qui fait bouger `Inventaire.quantite_reservee`. Toute
operation suit le meme schema :

1. ouvrir une transaction ;
2. verrouiller la ligne d'inventaire avec `select_for_update()` ;
3. relire les quantites APRES le verrou ;
4. decider, appliquer, tracer le mouvement de stock.

Le point 3 est le coeur du paragraphe 8.1 du cahier des charges : si deux
vendeurs (ou deux onglets) acceptent simultanement des reservations sur les
2 dernieres unites, la seconde transaction attend le verrou, relit
`quantite_disponible = 0` et echoue proprement en 400. Sans le verrou, les
deux lectures verraient "2 disponibles" et le stock passerait en negatif.

PostgreSQL applique reellement ce verrou de ligne. SQLite serialise de toute
facon les ecritures, donc le code est correct sur les deux moteurs.
"""
from datetime import timedelta

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied

from modules.products.models import Inventaire, StatutProduit
from modules.products.services import MouvementStockService, ProduitStatutService
from modules.notifications.services import NotificationService
from modules.reservations.models import (
    Reservation,
    RoleCloture,
    StatutReservation,
)


class ReservationService:
    """Cycle de vie d'une reservation et immobilisation du stock."""

    # ------------------------------------------------------------- outillage
    @staticmethod
    def duree_de_validite() -> timedelta:
        """Duree d'expiration configurable (cahier des charges, module 8).

        Lue dans la configuration de la plateforme (module 14), avec repli
        sur le `.env` puis sur 72 heures : la table des parametres peut
        rester vide sans rien changer au comportement.
        """
        from modules.moderation.models import ParametrePlateforme

        heures = ParametrePlateforme.valeur_de(
            "RESERVATION_DUREE_HEURES",
            getattr(settings, "RESERVATION_DUREE_HEURES", 72),
        )
        return timedelta(hours=int(heures))

    @staticmethod
    def _verrouiller_inventaire(produit_id: int) -> Inventaire:
        """Verrouille la ligne de stock et la relit telle qu'elle est en base.

        `select_for_update()` doit porter sur `Inventaire` et non sur
        `Produit` : c'est la ligne de stock que deux transactions se
        disputent.
        """
        inventaire = (
            Inventaire.objects.select_for_update()
            .select_related("produit", "produit__owner")
            .filter(produit_id=produit_id)
            .first()
        )
        if inventaire is None:
            raise serializers.ValidationError(
                {
                    "produit": (
                        "Ce produit n'a pas encore de stock enregistre : le "
                        "vendeur doit saisir sa quantite avant toute reservation."
                    )
                }
            )
        return inventaire

    @staticmethod
    def _verifier_annonce_reservable(inventaire: Inventaire) -> None:
        produit = inventaire.produit
        if produit.status == StatutProduit.OUT_OF_STOCK:
            raise serializers.ValidationError(
                {"produit": "Ce produit est en rupture de stock."}
            )
        if produit.status != StatutProduit.ACTIVE:
            raise serializers.ValidationError(
                {
                    "produit": (
                        "Cette annonce n'accepte pas de reservation "
                        f"(statut {produit.status})."
                    )
                }
            )
        if not produit.owner.is_active or getattr(
            produit.owner, "statut_compte", "ACTIF"
        ) == "SUSPENDU":
            raise serializers.ValidationError(
                {"produit": "Le vendeur de cette annonce est indisponible."}
            )

    # ------------------------------------------------------------- demander
    @staticmethod
    @transaction.atomic
    def demander(produit, acheteur, quantite: int, message: str = "") -> Reservation:
        """L'acheteur demande une quantite (statut PENDING).

        Une demande n'immobilise pas encore le stock : elle est verifiee
        contre le disponible du moment pour ne pas faire esperer l'acheteur,
        mais seule l'acceptation du vendeur reserve reellement.
        """
        inventaire = ReservationService._verrouiller_inventaire(produit.pk)
        produit = inventaire.produit

        if produit.owner_id == acheteur.pk:
            raise serializers.ValidationError(
                {"produit": "Vous ne pouvez pas reserver votre propre annonce."}
            )

        ReservationService._verifier_annonce_reservable(inventaire)

        disponible = inventaire.quantite_disponible
        if disponible <= 0:
            raise serializers.ValidationError(
                {"produit": "Plus aucune quantite disponible pour ce produit."}
            )
        if quantite > disponible:
            raise serializers.ValidationError(
                {
                    "quantite_demandee": (
                        f"Quantite trop elevee : {disponible} unite(s) "
                        "disponible(s) actuellement."
                    )
                }
            )

        try:
            reservation = Reservation.objects.create(
                produit=produit,
                acheteur=acheteur,
                vendeur=produit.owner,
                quantite_demandee=quantite,
                message=message,
                expire_le=timezone.now() + ReservationService.duree_de_validite(),
            )
        except IntegrityError as exc:
            # Contrainte `reservation_active_unique_par_acheteur`.
            raise serializers.ValidationError(
                {
                    "produit": (
                        "Vous avez deja une reservation en cours sur ce "
                        "produit. Modifiez sa quantite ou annulez-la."
                    )
                }
            ) from exc

        # Module 12 : le vendeur doit savoir qu'une demande l'attend.
        NotificationService.reservation_demandee(reservation)
        return reservation

    # ------------------------------------------------------------- accepter
    @staticmethod
    def accepter(reservation: Reservation, vendeur, quantite: int | None = None):
        """Le vendeur accepte : c'est ici que le stock est immobilise.

        `quantite` permet d'accepter moins que demande (il ne reste que 2 des
        3 unites souhaitees), avec l'accord implicite de l'acheteur qui garde
        la possibilite d'annuler.

        L'expiration est traitee AVANT d'ouvrir la transaction d'acceptation :
        si elle etait faite a l'interieur, l'erreur levee ensuite annulerait
        l'expiration elle-meme (tout le bloc serait defait) et la demande
        perimee resterait indefiniment en attente.
        """
        if reservation.vendeur_id != vendeur.pk:
            raise PermissionDenied(
                "Seul le vendeur de l'annonce peut accepter cette reservation."
            )
        if reservation.est_expiree:
            ReservationService.expirer(reservation)
            raise serializers.ValidationError(
                {"statut": "Cette demande a expire : elle ne peut plus etre acceptee."}
            )
        return ReservationService._accepter_sous_verrou(reservation, vendeur, quantite)

    @staticmethod
    @transaction.atomic
    def _accepter_sous_verrou(reservation, vendeur, quantite):
        # On relit la reservation sous verrou pour empecher deux acceptations
        # simultanees de la MEME reservation (double immobilisation).
        reservation = (
            Reservation.objects.select_for_update()
            .select_related("produit")
            .get(pk=reservation.pk)
        )

        if reservation.statut != StatutReservation.PENDING:
            raise serializers.ValidationError(
                {
                    "statut": (
                        "Seule une demande en attente peut etre acceptee "
                        f"(statut actuel : {reservation.statut})."
                    )
                }
            )

        quantite = reservation.quantite_demandee if quantite is None else quantite
        if quantite < 1:
            raise serializers.ValidationError(
                {"quantite": "La quantite acceptee doit etre superieure a zero."}
            )
        if quantite > reservation.quantite_demandee:
            raise serializers.ValidationError(
                {
                    "quantite": (
                        "Impossible d'accepter plus que la quantite demandee "
                        f"({reservation.quantite_demandee})."
                    )
                }
            )

        inventaire = ReservationService._verrouiller_inventaire(reservation.produit_id)
        disponible = inventaire.quantite_disponible
        if quantite > disponible:
            # Cas du scenario 8.1 : une autre reservation a ete acceptee
            # entre-temps. On refuse plutot que de depasser le stock.
            raise serializers.ValidationError(
                {
                    "quantite": (
                        f"Stock insuffisant : {disponible} unite(s) "
                        "disponible(s). Acceptez une quantite plus faible ou "
                        "liberez une autre reservation."
                    )
                }
            )

        MouvementStockService.reserver(
            inventaire,
            quantite,
            reservation.pk,
            utilisateur=vendeur,
            commentaire=f"Acceptation de la reservation {reservation.pk}",
        )

        maintenant = timezone.now()
        reservation.statut = StatutReservation.CONFIRMED
        reservation.quantite_confirmee = quantite
        reservation.confirmee_le = maintenant
        # La date limite repart de l'acceptation : l'acheteur a toute la
        # duree configuree pour venir retirer sa commande.
        reservation.expire_le = maintenant + ReservationService.duree_de_validite()
        reservation.save(
            update_fields=[
                "statut", "quantite_confirmee", "confirmee_le",
                "expire_le", "updated_at",
            ]
        )

        ProduitStatutService.synchroniser_statut_stock(inventaire.produit)
        NotificationService.reservation_acceptee(reservation)
        return reservation

    # -------------------------------------------------------------- refuser
    @staticmethod
    @transaction.atomic
    def refuser(reservation: Reservation, vendeur, motif: str = "") -> Reservation:
        """Le vendeur refuse une demande encore en attente.

        Un refus ne libere rien : une demande PENDING n'immobilisait pas de
        stock. Le statut retenu est CANCELLED (le cahier des charges ne
        prevoit pas de statut REFUSED) ; `cloturee_par` et `motif` disent qui
        a refuse et pourquoi.
        """
        if reservation.vendeur_id != vendeur.pk:
            raise PermissionDenied(
                "Seul le vendeur de l'annonce peut refuser cette reservation."
            )
        if reservation.statut != StatutReservation.PENDING:
            raise serializers.ValidationError(
                {
                    "statut": (
                        "Seule une demande en attente peut etre refusee "
                        f"(statut actuel : {reservation.statut})."
                    )
                }
            )

        reservation.statut = StatutReservation.CANCELLED
        reservation.cloturee_le = timezone.now()
        reservation.cloturee_par = RoleCloture.VENDEUR
        reservation.motif = motif or "Demande refusee par le vendeur."
        reservation.save(
            update_fields=["statut", "cloturee_le", "cloturee_par", "motif", "updated_at"]
        )
        NotificationService.reservation_refusee(reservation)
        return reservation

    # --------------------------------------------------------------- annuler
    @staticmethod
    @transaction.atomic
    def annuler(reservation: Reservation, utilisateur, motif: str = "") -> Reservation:
        """Annulation par l'acheteur ou le vendeur ; libere le stock.

        Exemple du cahier des charges : le client ne vient pas chercher ses
        3 unites, le vendeur annule, les 3 unites redeviennent disponibles.
        """
        if not reservation.est_participant(utilisateur):
            raise PermissionDenied("Cette reservation ne vous concerne pas.")

        reservation = (
            Reservation.objects.select_for_update()
            .select_related("produit")
            .get(pk=reservation.pk)
        )
        if not reservation.est_active:
            raise serializers.ValidationError(
                {
                    "statut": (
                        "Cette reservation est deja cloturee "
                        f"(statut {reservation.statut})."
                    )
                }
            )

        ReservationService._liberer_si_confirmee(
            reservation,
            utilisateur=utilisateur,
            commentaire=f"Annulation de la reservation {reservation.pk}",
        )

        reservation.statut = StatutReservation.CANCELLED
        reservation.cloturee_le = timezone.now()
        reservation.cloturee_par = reservation.role_de(utilisateur)
        reservation.motif = motif
        reservation.save(
            update_fields=["statut", "cloturee_le", "cloturee_par", "motif", "updated_at"]
        )
        # Module 12 : seule la partie qui n'a pas annule est prevenue.
        NotificationService.reservation_annulee(reservation, utilisateur)
        return reservation

    # -------------------------------------------------------------- expirer
    @staticmethod
    @transaction.atomic
    def expirer(reservation: Reservation) -> Reservation:
        """Passe une reservation depassee en EXPIRED et libere son stock."""
        reservation = (
            Reservation.objects.select_for_update()
            .select_related("produit")
            .get(pk=reservation.pk)
        )
        if not reservation.est_active:
            return reservation

        ReservationService._liberer_si_confirmee(
            reservation,
            utilisateur=None,
            commentaire=f"Expiration de la reservation {reservation.pk}",
        )

        reservation.statut = StatutReservation.EXPIRED
        reservation.cloturee_le = timezone.now()
        reservation.cloturee_par = RoleCloture.SYSTEME
        reservation.motif = "Delai de retrait depasse."
        reservation.save(
            update_fields=["statut", "cloturee_le", "cloturee_par", "motif", "updated_at"]
        )
        # Module 12 : l'acheteur perd sa reservation, le vendeur recupere
        # son stock. Les deux doivent le savoir.
        NotificationService.reservation_expiree(reservation)
        return reservation

    @staticmethod
    def expirer_les_depassees(maintenant=None) -> int:
        """Traite toutes les reservations arrivees a echeance.

        Appelee par `manage.py expirer_reservations` (tache planifiee) et,
        de maniere opportuniste, a la lecture des listes : une plateforme
        sans ordonnanceur ne doit pas garder du stock bloque indefiniment.
        """
        identifiants = list(
            Reservation.objects.expirables(maintenant).values_list("pk", flat=True)
        )
        traitees = 0
        for identifiant in identifiants:
            reservation = (
                Reservation.objects.select_related("produit")
                .filter(pk=identifiant)
                .first()
            )
            if reservation is None:
                continue
            with transaction.atomic():
                ReservationService.expirer(reservation)
            ProduitStatutService.synchroniser_statut_stock(reservation.produit)
            traitees += 1
        return traitees

    # ----------------------------------------------------- modifier quantite
    @staticmethod
    @transaction.atomic
    def modifier_quantite(reservation: Reservation, utilisateur, quantite: int):
        """Ajuste la quantite, selon le role et le statut.

        Le cahier des charges demande une modification "avec accord des
        parties". La regle retenue, qui garde la decision du cote de celui
        qui engage quelque chose :

        - PENDING : l'ACHETEUR ajuste sa demande (le vendeur n'a encore rien
          promis, il acceptera ou non la nouvelle quantite) ;
        - CONFIRMED : le VENDEUR ajuste la quantite mise de cote, car c'est
          son stock qui est immobilise. L'acheteur reste libre d'annuler.

        La negociation elle-meme se fait dans la messagerie (module 7).
        """
        if not reservation.est_participant(utilisateur):
            raise PermissionDenied("Cette reservation ne vous concerne pas.")
        if quantite < 1:
            raise serializers.ValidationError(
                {"quantite": "La quantite doit etre superieure a zero."}
            )

        reservation = (
            Reservation.objects.select_for_update()
            .select_related("produit")
            .get(pk=reservation.pk)
        )

        if reservation.statut == StatutReservation.PENDING:
            if reservation.acheteur_id != utilisateur.pk:
                raise PermissionDenied(
                    "Tant que la demande est en attente, seul l'acheteur peut "
                    "changer la quantite souhaitee. Vous pouvez l'accepter "
                    "partiellement avec /accept/."
                )
            inventaire = ReservationService._verrouiller_inventaire(
                reservation.produit_id
            )
            if quantite > inventaire.quantite_disponible:
                raise serializers.ValidationError(
                    {
                        "quantite": (
                            f"Quantite trop elevee : "
                            f"{inventaire.quantite_disponible} unite(s) "
                            "disponible(s)."
                        )
                    }
                )
            reservation.quantite_demandee = quantite
            reservation.save(update_fields=["quantite_demandee", "updated_at"])
            return reservation

        if reservation.statut == StatutReservation.CONFIRMED:
            if reservation.vendeur_id != utilisateur.pk:
                raise PermissionDenied(
                    "La reservation est acceptee : seul le vendeur peut "
                    "ajuster la quantite mise de cote. Vous pouvez annuler "
                    "avec /cancel/."
                )

            inventaire = ReservationService._verrouiller_inventaire(
                reservation.produit_id
            )
            ecart = quantite - reservation.quantite_confirmee
            if ecart > 0:
                if ecart > inventaire.quantite_disponible:
                    raise serializers.ValidationError(
                        {
                            "quantite": (
                                f"Stock insuffisant : seulement "
                                f"{inventaire.quantite_disponible} unite(s) "
                                "en plus sont disponibles."
                            )
                        }
                    )
                MouvementStockService.reserver(
                    inventaire, ecart, reservation.pk, utilisateur=utilisateur,
                    commentaire=f"Augmentation de la reservation {reservation.pk}",
                )
            elif ecart < 0:
                MouvementStockService.liberer(
                    inventaire, -ecart, reservation.pk, utilisateur=utilisateur,
                    commentaire=f"Reduction de la reservation {reservation.pk}",
                )

            # La demande suit la quantite confirmee si celle-ci augmente :
            # la contrainte en base interdit confirmee > demandee.
            reservation.quantite_demandee = max(
                reservation.quantite_demandee, quantite
            )
            reservation.quantite_confirmee = quantite
            reservation.save(
                update_fields=["quantite_demandee", "quantite_confirmee", "updated_at"]
            )
            ProduitStatutService.synchroniser_statut_stock(inventaire.produit)
            return reservation

        raise serializers.ValidationError(
            {
                "statut": (
                    "Une reservation cloturee ne peut plus changer de "
                    f"quantite (statut {reservation.statut})."
                )
            }
        )

    # --------------------------------------------------------------- interne
    @staticmethod
    def _liberer_si_confirmee(reservation, utilisateur=None, commentaire=""):
        """Rend disponible la quantite immobilisee, le cas echeant.

        Ne touche jamais `quantite_vendue` : une reservation annulee ou
        expiree ne doit pas diminuer le stock vendu (regle du module 8).
        """
        if reservation.statut != StatutReservation.CONFIRMED:
            return None
        if reservation.quantite_confirmee <= 0:
            return None

        inventaire = ReservationService._verrouiller_inventaire(reservation.produit_id)
        mouvement = MouvementStockService.liberer(
            inventaire,
            reservation.quantite_confirmee,
            reservation.pk,
            utilisateur=utilisateur,
            commentaire=commentaire,
        )
        ProduitStatutService.synchroniser_statut_stock(inventaire.produit)
        return mouvement
