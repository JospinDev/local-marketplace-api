"""Generation de codes numeriques de verification."""
import secrets


def generate_numeric_code(length: int = 6) -> str:
    """Retourne un code numerique aleatoire cryptographiquement sur."""
    return "".join(str(secrets.randbelow(10)) for _ in range(length))
