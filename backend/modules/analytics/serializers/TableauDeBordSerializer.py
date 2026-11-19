"""Serializers du module 10.

Le tableau de bord est en lecture seule : ces serializers ne servent qu'a
decrire les reponses, ce qui donne un schema OpenAPI typé et donc un client
Flutter genere sans surprise.
"""
from rest_framework import serializers


class VueGeneraleSerializer(serializers.Serializer):
    """Section A du cahier des charges."""

    produits_publies = serializers.IntegerField()
    produits_disponibles = serializers.IntegerField()
    produits_en_rupture = serializers.IntegerField()
    produits_total = serializers.IntegerField(
        help_text="Brouillons et annonces archivees comprises."
    )
    demandes_de_reservation_en_attente = serializers.IntegerField(
        help_text="Demandes qui attendent votre reponse."
    )
    reservations_en_cours = serializers.IntegerField(
        help_text="Reservations acceptees : du stock est immobilise."
    )
    ventes_confirmees = serializers.IntegerField()
    nombre_clients = serializers.IntegerField(
        help_text="Acheteurs distincts ayant une vente confirmee."
    )
    nombre_conversations = serializers.IntegerField()
    note_moyenne_vendeur = serializers.FloatField(allow_null=True)
    nombre_evaluations = serializers.IntegerField()


class RevenuParProduitSerializer(serializers.Serializer):
    produit = serializers.IntegerField()
    titre = serializers.CharField()
    quantite_vendue = serializers.IntegerField()
    revenu = serializers.DecimalField(max_digits=18, decimal_places=2)


class RevenuParCategorieSerializer(serializers.Serializer):
    categorie = serializers.IntegerField()
    nom = serializers.CharField()
    quantite_vendue = serializers.IntegerField()
    revenu = serializers.DecimalField(max_digits=18, decimal_places=2)


class TableauDeBordRevenusSerializer(serializers.Serializer):
    """Section B : gestion financiere."""

    chiffre_affaires_total = serializers.DecimalField(
        max_digits=18, decimal_places=2,
        help_text="Ventes confirmees uniquement (PAID et COMPLETED).",
    )
    quantite_vendue = serializers.IntegerField()
    revenus_du_jour = serializers.DecimalField(max_digits=18, decimal_places=2)
    revenus_de_la_semaine = serializers.DecimalField(
        max_digits=18, decimal_places=2, help_text="Depuis lundi, heure locale."
    )
    revenus_du_mois = serializers.DecimalField(
        max_digits=18, decimal_places=2, help_text="Depuis le 1er du mois."
    )
    valeur_reservations_en_cours = serializers.DecimalField(
        max_digits=18, decimal_places=2,
        help_text=(
            "Valeur des quantites mises de cote. N'est PAS un revenu et "
            "n'entre dans aucun total ci-dessus."
        ),
    )
    ventes_en_attente_de_confirmation = serializers.IntegerField(
        help_text="Ventes declarees dont le paiement n'est pas encore confirme."
    )
    par_produit = RevenuParProduitSerializer(many=True)
    par_categorie = RevenuParCategorieSerializer(many=True)
    devise = serializers.CharField()


class StockParProduitSerializer(serializers.Serializer):
    produit = serializers.IntegerField()
    titre = serializers.CharField()
    statut = serializers.CharField()
    prix = serializers.DecimalField(max_digits=14, decimal_places=2)
    quantite_totale = serializers.IntegerField()
    quantite_reservee = serializers.IntegerField()
    quantite_vendue = serializers.IntegerField()
    quantite_disponible = serializers.IntegerField()


class StocksSerializer(serializers.Serializer):
    """Section C : etat des stocks."""

    stock_total = serializers.IntegerField()
    quantite_reservee = serializers.IntegerField()
    quantite_vendue = serializers.IntegerField()
    quantite_disponible = serializers.IntegerField()
    valeur_stock_disponible = serializers.DecimalField(
        max_digits=18, decimal_places=2,
        help_text="Quantite disponible x prix actuel de chaque annonce.",
    )
    valeur_reservations_en_cours = serializers.DecimalField(
        max_digits=18, decimal_places=2
    )
    par_produit = StockParProduitSerializer(many=True)


class CompteursReservationsSerializer(serializers.Serializer):
    """Section D : issues des reservations recues."""

    en_attente = serializers.IntegerField()
    acceptees = serializers.IntegerField()
    annulees = serializers.IntegerField()
    expirees = serializers.IntegerField()
    transformees_en_vente = serializers.IntegerField()
    quantite_immobilisee = serializers.IntegerField()
    taux_de_transformation = serializers.FloatField(
        allow_null=True,
        help_text=(
            "Part des reservations jugees (vendues, annulees ou expirees) "
            "qui se sont transformees en vente, en pourcentage. `null` tant "
            "qu'aucune reservation n'est arrivee a son terme."
        ),
    )


class ProduitLePlusVenduSerializer(serializers.Serializer):
    produit = serializers.IntegerField()
    titre = serializers.CharField()
    prix = serializers.DecimalField(max_digits=14, decimal_places=2)
    quantite_vendue = serializers.IntegerField()
    revenu = serializers.DecimalField(max_digits=18, decimal_places=2)
    nombre_ventes = serializers.IntegerField()


class ProduitLePlusConsulteSerializer(serializers.Serializer):
    produit = serializers.IntegerField()
    titre = serializers.CharField()
    prix = serializers.DecimalField(max_digits=14, decimal_places=2)
    nombre_vues = serializers.IntegerField()
    quantite_disponible = serializers.IntegerField()
    note_moyenne = serializers.FloatField(allow_null=True)


class ProduitsPopulairesSerializer(serializers.Serializer):
    """Section D : produits les plus vendus et les plus consultes."""

    les_plus_vendus = ProduitLePlusVenduSerializer(many=True)
    les_plus_consultes = ProduitLePlusConsulteSerializer(many=True)
