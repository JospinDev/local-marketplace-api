"""Routage du module 11.

Trois portes distinctes, avec trois modeles de protection :

- `/reviews/`                      prive, base sur la propriete ;
- `/admin/reviews/`                moderation, permissions de groupe ;
- `/public/products/{id}/reviews/` ouvert a tous, avis valides seulement.
"""
from django.urls import include, path
from rest_framework.routers import SimpleRouter

from modules.reviews.viewsets import (
    EvaluationModerationViewSet,
    EvaluationProduitPubliqueViewSet,
    EvaluationViewSet,
)

router = SimpleRouter()
router.register("reviews", EvaluationViewSet, basename="reviews")

router_admin = SimpleRouter()
router_admin.register(
    "reviews", EvaluationModerationViewSet, basename="admin-reviews"
)

avis_produit = EvaluationProduitPubliqueViewSet.as_view({"get": "list"})

urlpatterns = [
    path("", include(router.urls)),
    path("admin/", include(router_admin.urls)),
    path(
        "public/products/<int:produit_id>/reviews/",
        avis_produit,
        name="public-product-reviews",
    ),
]
