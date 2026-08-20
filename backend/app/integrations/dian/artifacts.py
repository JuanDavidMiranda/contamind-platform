"""Cifrado de artefactos electrónicos que deben sobrevivir a la cola.

Los XML firmados y ZIP de DIAN pueden contener datos tributarios de terceros.
Nunca se persisten en claro ni se devuelven desde las vistas operativas; esta
utilidad deriva una clave distinta de la usada para credenciales de proveedor.
"""

from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from app.config.settings import settings


class DianArtifactCipher:
    """Cifra bytes de documentos con separación de propósito por dominio."""

    key_version = "dian-artifacts-v1"

    def __init__(self, key: bytes) -> None:
        self._fernet = Fernet(key)

    @classmethod
    def from_settings(cls) -> "DianArtifactCipher":
        master = settings.PROVIDER_CREDENTIALS_MASTER_KEY
        if not master:
            raise ValueError("Se requiere PROVIDER_CREDENTIALS_MASTER_KEY para cifrar documentos DIAN.")
        material = hashlib.sha256(
            b"contamind:dian-electronic-artifacts:v1:" + master.encode("ascii")
        ).digest()
        return cls(base64.urlsafe_b64encode(material))

    def encrypt(self, plaintext: bytes) -> str:
        if not plaintext or len(plaintext) > 15_000_000:
            raise ValueError("El artefacto DIAN está vacío o excede el límite de almacenamiento.")
        return self._fernet.encrypt(plaintext).decode("ascii")

    def decrypt(self, ciphertext: str) -> bytes:
        try:
            return self._fernet.decrypt(ciphertext.encode("ascii"))
        except (InvalidToken, UnicodeEncodeError) as exc:
            raise ValueError("El artefacto cifrado DIAN no es válido.") from exc
