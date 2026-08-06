import base64
import hashlib
import hmac
import json
import os
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.config.settings import settings
from app.models.user import User


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode().rstrip("=")


def _decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1)
    return "scrypt$" + _b64(salt) + "$" + _b64(digest)


def verify_password(password: str, stored_value: str) -> bool:
    try:
        algorithm, salt_value, digest_value = stored_value.split("$", 2)
        if algorithm != "scrypt":
            return False
        candidate = hashlib.scrypt(
            password.encode(),
            salt=_decode(salt_value),
            n=2**14,
            r=8,
            p=1,
        )
        return hmac.compare_digest(candidate, _decode(digest_value))
    except (TypeError, ValueError):
        return False


def create_access_token(user: User) -> str:
    header = _b64(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    payload = _b64(
        json.dumps(
            {
                "sub": str(user.id),
                "email": user.email,
                "admin": user.is_platform_admin,
                "exp": int(
                    (datetime.now(timezone.utc) + timedelta(minutes=settings.AUTH_TOKEN_TTL_MINUTES)).timestamp()
                ),
            },
            separators=(",", ":"),
        ).encode()
    )
    signature = _b64(
        hmac.new(settings.AUTH_SECRET_KEY.encode(), (header + "." + payload).encode(), hashlib.sha256).digest()
    )
    return header + "." + payload + "." + signature


def get_current_user(authorization: str | None, db: Session) -> User:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token de acceso requerido.")

    try:
        header, payload, signature = authorization.removeprefix("Bearer ").split(".")
        expected = _b64(
            hmac.new(settings.AUTH_SECRET_KEY.encode(), (header + "." + payload).encode(), hashlib.sha256).digest()
        )
        if not hmac.compare_digest(signature, expected):
            raise ValueError("Firma inválida")

        claims = json.loads(_decode(payload))
        if int(claims["exp"]) <= int(datetime.now(timezone.utc).timestamp()):
            raise ValueError("Token vencido")
        user = db.get(User, int(claims["sub"]))
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token inválido.") from None

    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Usuario no encontrado.")
    return user
