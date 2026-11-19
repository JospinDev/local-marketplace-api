"""Format d'erreur unique pour toute l'API (consomme par Flutter)."""
from rest_framework.views import exception_handler


def api_exception_handler(exc, context):
    response = exception_handler(exc, context)
    if response is None:
        return None

    detail = response.data
    payload = {
        "success": False,
        "status_code": response.status_code,
    }

    if isinstance(detail, dict) and "detail" in detail and len(detail) == 1:
        payload["message"] = str(detail["detail"])
        payload["errors"] = {}
    elif isinstance(detail, dict):
        payload["message"] = "Donnees invalides."
        payload["errors"] = detail
    else:
        payload["message"] = "Requete invalide."
        payload["errors"] = {"detail": detail}

    response.data = payload
    return response
