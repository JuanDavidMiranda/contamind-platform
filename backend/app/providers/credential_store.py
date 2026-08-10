"""Almacén persistente y cifrado de secretos de proveedores."""

import base64
import hashlib
import json
from uuid import uuid4

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config.settings import settings
from app.models.data_source import ProviderCredentialRecord
from app.providers.canonical import ProviderContext
from app.providers.secrets import ProviderSecret, SecretStore
from app.shared.errors import app_error


class ProviderCredentialCipher:
    """Cifra valores con Fernet (confidencialidad e integridad autenticada)."""

    key_version = "fernet-v1"

    def __init__(self, key: bytes) -> None:
        self._fernet = Fernet(key)

    @classmethod
    def from_settings(cls) -> "ProviderCredentialCipher":
        configured_key = settings.PROVIDER_CREDENTIALS_MASTER_KEY
        if configured_key:
            try:
                return cls(configured_key.encode("ascii"))
            except (UnicodeEncodeError, ValueError) as exc:
                raise RuntimeError(
                    "PROVIDER_CREDENTIALS_MASTER_KEY debe ser una clave Fernet válida."
                ) from exc

        # Desarrollo y tests: la clave queda ligada a AUTH_SECRET_KEY. En entornos
        # persistentes es obligatoria una clave independiente validada por Settings.
        assert settings.AUTH_SECRET_KEY is not None
        derived_key = base64.urlsafe_b64encode(
            hashlib.sha256(
                f"provider-credentials:{settings.AUTH_SECRET_KEY}".encode("utf-8")
            ).digest()
        )
        return cls(derived_key)

    def encrypt(self, secret: ProviderSecret) -> str:
        payload = json.dumps(
            dict(secret.values), sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return self._fernet.encrypt(payload).decode("ascii")

    def decrypt(self, ciphertext: str) -> ProviderSecret:
        try:
            raw = json.loads(self._fernet.decrypt(ciphertext.encode("ascii")))
        except (InvalidToken, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("El secreto cifrado no es válido.") from exc
        if not isinstance(raw, dict) or not all(
            isinstance(key, str) and isinstance(value, str)
            for key, value in raw.items()
        ):
            raise ValueError("El secreto cifrado no tiene un formato válido.")
        return ProviderSecret(raw)


class EncryptedDatabaseSecretStore(SecretStore):
    """SecretStore transaccional con alcance fuente + empresa + proveedor."""

    def __init__(self, db: Session, cipher: ProviderCredentialCipher | None = None) -> None:
        self._db = db
        self._cipher = cipher or ProviderCredentialCipher.from_settings()

    @staticmethod
    def _source_id(context: ProviderContext) -> str:
        if context.data_source_id is None:
            raise ValueError("El contexto de proveedor requiere data_source_id.")
        return str(context.data_source_id)

    def get(self, context: ProviderContext) -> ProviderSecret | None:
        record = self._db.scalar(
            select(ProviderCredentialRecord).where(
                ProviderCredentialRecord.data_source_id == self._source_id(context),
                ProviderCredentialRecord.tenant_id == str(context.tenant_id),
                ProviderCredentialRecord.company_id == str(context.company_id),
                ProviderCredentialRecord.provider_id == context.provider,
            )
        )
        if record is None:
            return None
        try:
            return self._cipher.decrypt(record.ciphertext)
        except ValueError as exc:
            raise app_error(
                "PROVIDER_AUTH_FAILED",
                message="No fue posible usar las credenciales configuradas del proveedor.",
                details={"provider": context.provider},
            ) from exc

    def save(
        self,
        context: ProviderContext,
        secret: ProviderSecret,
        *,
        actor_user_id: int | None = None,
    ) -> None:
        source_id = self._source_id(context)
        record = self._db.scalar(
            select(ProviderCredentialRecord).where(
                ProviderCredentialRecord.data_source_id == source_id
            )
        )
        if record is None:
            record = ProviderCredentialRecord(
                id=str(uuid4()),
                data_source_id=source_id,
                tenant_id=str(context.tenant_id),
                company_id=str(context.company_id),
                provider_id=context.provider,
                ciphertext=self._cipher.encrypt(secret),
                key_version=self._cipher.key_version,
                created_by_user_id=actor_user_id,
                updated_by_user_id=actor_user_id,
            )
            self._db.add(record)
            return

        record.tenant_id = str(context.tenant_id)
        record.company_id = str(context.company_id)
        record.provider_id = context.provider
        record.ciphertext = self._cipher.encrypt(secret)
        record.key_version = self._cipher.key_version
        record.updated_by_user_id = actor_user_id

    def revoke(self, context: ProviderContext) -> None:
        record = self._db.scalar(
            select(ProviderCredentialRecord).where(
                ProviderCredentialRecord.data_source_id == self._source_id(context),
                ProviderCredentialRecord.tenant_id == str(context.tenant_id),
                ProviderCredentialRecord.company_id == str(context.company_id),
                ProviderCredentialRecord.provider_id == context.provider,
            )
        )
        if record is not None:
            self._db.delete(record)
