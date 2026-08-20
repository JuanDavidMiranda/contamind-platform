"""Material criptográfico efímero para servicios DIAN.

El certificado PKCS#12 se descifra solamente durante la operación que lo
requiere. Esta clase no tiene representación que exponga sus secretos.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Mapping

from cryptography import x509
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs12


@dataclass(frozen=True, repr=False)
class DianTechnicalCredentials:
    software_id: str
    software_password: str
    private_key: rsa.RSAPrivateKey
    certificate: x509.Certificate

    @classmethod
    def from_secret_values(cls, values: Mapping[str, str]) -> "DianTechnicalCredentials":
        required = {
            "software_id",
            "software_password",
            "certificate_pfx_base64",
            "certificate_password",
        }
        missing = sorted(name for name in required if not values.get(name))
        if missing:
            raise ValueError("Faltan datos técnicos DIAN requeridos.")
        try:
            raw_pfx = base64.b64decode(values["certificate_pfx_base64"], validate=True)
            private_key, certificate, _ = pkcs12.load_key_and_certificates(
                raw_pfx,
                values["certificate_password"].encode("utf-8"),
            )
        except (TypeError, ValueError) as exc:
            raise ValueError("El certificado DIAN no tiene un formato PKCS#12 válido.") from exc
        if not isinstance(private_key, rsa.RSAPrivateKey) or certificate is None:
            raise ValueError("El certificado DIAN debe incluir una clave privada RSA.")
        now = datetime.now(UTC)
        if not certificate.not_valid_before_utc <= now <= certificate.not_valid_after_utc:
            raise ValueError("El certificado DIAN no está vigente.")
        return cls(
            software_id=values["software_id"],
            software_password=values["software_password"],
            private_key=private_key,
            certificate=certificate,
        )

    def __repr__(self) -> str:
        return "DianTechnicalCredentials(**redacted**)"
