"""Provisiona el primer administrador de una beta privada de ContaMind.

No usa credenciales de demostración ni imprime contraseñas. Ejecútalo solo en
una consola administrada, con la configuración del ambiente ya cargada:

    .\\.venv\\Scripts\\python.exe scripts\\provision_platform_admin.py \\
        --email operador@empresa.com --full-name ""Operador ContaMind""

Para automatización no interactiva, define temporalmente
``CONTAMIND_INITIAL_ADMIN_PASSWORD`` en el proceso que lo ejecuta y elimínala
al terminar.
"""

from __future__ import annotations

import argparse
import getpass
import os
import sys
from pathlib import Path

from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database.database import SessionLocal
from app.models.user import User
from app.shared.security import hash_password, validate_new_password


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Provisiona un administrador de plataforma.")
    parser.add_argument("--email", required=True, help="Correo de la persona administradora.")
    parser.add_argument("--full-name", required=True, help="Nombre completo de la persona administradora.")
    parser.add_argument(
        "--reset-password",
        action="store_true",
        help="Rota la contraseña si la cuenta ya existe.",
    )
    return parser.parse_args()


def read_password() -> str:
    from_environment = os.environ.get("CONTAMIND_INITIAL_ADMIN_PASSWORD")
    if from_environment is not None:
        return validate_new_password(from_environment)

    first = getpass.getpass("Contraseña inicial segura: ")
    second = getpass.getpass("Confirma la contraseña: ")
    if first != second:
        raise ValueError("Las contraseñas no coinciden.")
    return validate_new_password(first)


def main() -> int:
    args = parse_args()
    email = args.email.strip().lower()
    full_name = args.full_name.strip()
    if not full_name or email.count("@") != 1 or email.startswith("@") or email.endswith("@"):
        raise ValueError("Debes proporcionar un nombre y correo válidos.")

    db = SessionLocal()
    try:
        user = db.scalar(select(User).where(User.email == email))
        if user is None:
            password = read_password()
            user = User(
                email=email,
                full_name=full_name,
                password_hash=hash_password(password),
                is_platform_admin=True,
            )
            db.add(user)
            db.commit()
            print(f"Administrador de plataforma creado para {email}.")
            return 0

        user.full_name = full_name
        user.is_platform_admin = True
        if args.reset_password:
            password = read_password()
            user.password_hash = hash_password(password)
            user.token_version += 1
        db.commit()
        action = "Contraseña rotada y permisos confirmados" if args.reset_password else "Permisos confirmados"
        print(f"{action} para {email}.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ValueError as exc:
        print(f"No fue posible provisionar el administrador: {exc}", file=sys.stderr)
        raise SystemExit(2) from None
