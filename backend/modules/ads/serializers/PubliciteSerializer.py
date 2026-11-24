"""Serialiseurs des publicites.

Deux vues distinctes, volontairement : le client public n'a aucune raison
de connaitre les compteurs, l'auteur ou la fenetre de diffusion. Il recoit
uniquement ce qu'il doit dessiner.
"""
from rest_framework import serializers

from modules.ads.models import Publicite, TypeCiblePublicite


class PubliciteSerializer(serializers.ModelSerializer):
    """Vue PUBLIQUE : strictement ce qu'il faut pour afficher le bandeau."""

    type_cible_libelle = serializers.CharField(
        source="get_type_cible_display", read_only=True
    )

    class Meta:
        model = Publicite
        fields = (
            "id", "titre", "sous_titre", "image", "libelle_action",
            "type_cible", "type_cible_libelle", "cible_id", "cible_url",
            "ordre",
        )
        read_only_fields = fields


class PubliciteAdminSerializer(serializers.ModelSerializer):
    """Vue ADMINISTRATION : tout, compteurs et fenetre inclus."""

    type_cible_libelle = serializers.CharField(
        source="get_type_cible_display", read_only=True
    )
    cree_par_username = serializers.CharField(
        source="cree_par.username", read_only=True, default=""
    )
    est_diffusable = serializers.BooleanField(read_only=True)

    class Meta:
        model = Publicite
        fields = (
            "id", "titre", "sous_titre", "image", "libelle_action",
            "type_cible", "type_cible_libelle", "cible_id", "cible_url",
            "actif", "ordre", "debut_le", "fin_le", "est_diffusable",
            "nombre_affichages", "nombre_clics",
            "cree_par", "cree_par_username", "created_at", "updated_at",
        )
        read_only_fields = (
            "id", "type_cible_libelle", "est_diffusable",
            "nombre_affichages", "nombre_clics",
            "cree_par", "cree_par_username", "created_at", "updated_at",
        )

    def validate(self, attrs):
        """La cible doit etre coherente avec son type.

        Sans ce controle, on pourrait enregistrer une publicite de type
        `PRODUIT` sans identifiant : elle s'afficherait, et l'appui ne
        ferait rien. Mieux vaut refuser a la creation.
        """
        instance = self.instance
        type_cible = attrs.get(
            "type_cible",
            getattr(instance, "type_cible", TypeCiblePublicite.AUCUNE),
        )
        cible_id = attrs.get("cible_id", getattr(instance, "cible_id", None))
        cible_url = attrs.get("cible_url", getattr(instance, "cible_url", ""))

        if type_cible == TypeCiblePublicite.URL:
            if not cible_url:
                raise serializers.ValidationError(
                    {"cible_url": "Une adresse web est requise pour ce type."}
                )
        elif type_cible != TypeCiblePublicite.AUCUNE:
            if not cible_id:
                raise serializers.ValidationError(
                    {
                        "cible_id": (
                            "Indiquez l'identifiant de la "
                            f"{type_cible.lower()} visee."
                        )
                    }
                )

        debut = attrs.get("debut_le", getattr(instance, "debut_le", None))
        fin = attrs.get("fin_le", getattr(instance, "fin_le", None))
        if debut and fin and fin < debut:
            raise serializers.ValidationError(
                {"fin_le": "La fin de diffusion precede son debut."}
            )

        return attrs


class EtatBandeauSerializer(serializers.Serializer):
    """Reponse de /public/ads/state/ et de /admin/ads/state/."""

    actives = serializers.BooleanField(
        help_text="Interrupteur global du bandeau publicitaire."
    )
    nombre_diffusables = serializers.IntegerField(
        help_text="Publicites reellement affichables en ce moment."
    )


class InterrupteurSerializer(serializers.Serializer):
    """Entree de POST /admin/ads/state/."""

    actives = serializers.BooleanField(
        help_text="false fait disparaitre tout le bandeau cote mobile."
    )
