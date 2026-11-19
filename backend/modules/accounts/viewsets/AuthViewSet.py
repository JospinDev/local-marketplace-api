"""Module 1 - ViewSet d'authentification.

Construit sur `GenericViewSet` (jamais `APIView`) : chaque operation est une
action du ViewSet avec son propre serializer.

Connexion : username + password uniquement.
Email : facultatif, mais prouve par un code envoye a l'adresse declaree.
"""
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework_simplejwt.serializers import TokenRefreshSerializer

from modules.accounts.serializers import (
    EmailResendSerializer,
    EmailVerifySerializer,
    LoginSerializer,
    LogoutSerializer,
    PasswordChangeSerializer,
    PasswordResetConfirmSerializer,
    PasswordResetRequestSerializer,
    RegisterSerializer,
    UserSerializer,
)


@extend_schema_view(
    register=extend_schema(
        tags=["Auth"],
        summary="Inscription",
        description=(
            "Le `username` est obligatoire et unique. L'`email` est facultatif ; "
            "s'il est fourni, un code de verification est envoye a cette adresse "
            "et le compte reste inactif tant que le code n'est pas valide."
        ),
    ),
    login=extend_schema(tags=["Auth"], summary="Connexion (username + password)"),
    logout=extend_schema(tags=["Auth"], summary="Deconnexion (revocation du refresh)"),
    refresh=extend_schema(tags=["Auth"], summary="Renouvellement du token"),
    email_verify=extend_schema(tags=["Auth"], summary="Verifier l'email avec le code recu"),
    email_resend=extend_schema(tags=["Auth"], summary="Renvoyer le code de verification"),
    password_change=extend_schema(tags=["Auth"], summary="Changer mon mot de passe"),
    password_reset=extend_schema(tags=["Auth"], summary="Demander une reinitialisation"),
    password_reset_confirm=extend_schema(
        tags=["Auth"], summary="Confirmer la reinitialisation"
    ),
)
class AuthViewSet(viewsets.GenericViewSet):
    """Operations d'authentification et de recuperation de compte."""

    permission_classes = [AllowAny]
    throttle_scope = "auth"

    serializer_classes = {
        "register": RegisterSerializer,
        "login": LoginSerializer,
        "logout": LogoutSerializer,
        "refresh": TokenRefreshSerializer,
        "email_verify": EmailVerifySerializer,
        "email_resend": EmailResendSerializer,
        "password_change": PasswordChangeSerializer,
        "password_reset": PasswordResetRequestSerializer,
        "password_reset_confirm": PasswordResetConfirmSerializer,
    }

    def get_serializer_class(self):
        return self.serializer_classes.get(self.action, LoginSerializer)

    # ------------------------------------------------------------- inscription
    @action(detail=False, methods=["post"], url_path="register")
    def register(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        utilisateur = serializer.save()

        if utilisateur.email:
            message = (
                "Compte cree. Un code de verification a ete envoye a "
                f"{utilisateur.email}. Le compte sera actif apres validation du code."
            )
        else:
            message = "Compte cree. Vous pouvez vous connecter immediatement."

        return Response(
            {
                "success": True,
                "message": message,
                "email_verification_requise": bool(utilisateur.email),
                "utilisateur": UserSerializer(utilisateur, context=self.get_serializer_context()).data,
            },
            status=status.HTTP_201_CREATED,
        )

    # --------------------------------------------------------------- connexion
    @action(detail=False, methods=["post"], url_path="login")
    def login(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        donnees = serializer.validated_data
        return Response(
            {
                "success": True,
                "access": donnees["access"],
                "refresh": donnees["refresh"],
                "utilisateur": UserSerializer(
                    donnees["utilisateur"], context=self.get_serializer_context()
                ).data,
            },
            status=status.HTTP_200_OK,
        )

    @action(
        detail=False,
        methods=["post"],
        url_path="logout",
        permission_classes=[IsAuthenticated],
    )
    def logout(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(
            {"success": True, "message": "Deconnexion effectuee."},
            status=status.HTTP_200_OK,
        )

    @action(detail=False, methods=["post"], url_path="token/refresh")
    def refresh(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(serializer.validated_data, status=status.HTTP_200_OK)

    # ------------------------------------------------------- verification email
    @action(detail=False, methods=["post"], url_path="email/verify")
    def email_verify(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        utilisateur = serializer.validated_data["utilisateur"]
        return Response(
            {
                "success": True,
                "message": "Email verifie. Le compte est actif.",
                "utilisateur": UserSerializer(
                    utilisateur, context=self.get_serializer_context()
                ).data,
            },
            status=status.HTTP_200_OK,
        )

    @action(
        detail=False,
        methods=["post"],
        url_path="email/resend",
        throttle_scope="email_code",
    )
    def email_resend(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        utilisateur = serializer.validated_data["utilisateur"]
        return Response(
            {
                "success": True,
                "message": f"Un nouveau code a ete envoye a {utilisateur.email}.",
            },
            status=status.HTTP_200_OK,
        )

    # ------------------------------------------------------------ mot de passe
    @action(
        detail=False,
        methods=["post"],
        url_path="password/change",
        permission_classes=[IsAuthenticated],
    )
    def password_change(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(
            {"success": True, "message": "Mot de passe modifie."},
            status=status.HTTP_200_OK,
        )

    @action(
        detail=False,
        methods=["post"],
        url_path="password/reset",
        throttle_scope="email_code",
    )
    def password_reset(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(
            {
                "success": True,
                "message": "Un code de reinitialisation a ete envoye par email.",
            },
            status=status.HTTP_200_OK,
        )

    @action(detail=False, methods=["post"], url_path="password/reset/confirm")
    def password_reset_confirm(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(
            {"success": True, "message": "Mot de passe reinitialise."},
            status=status.HTTP_200_OK,
        )
