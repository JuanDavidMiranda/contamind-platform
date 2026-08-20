#!/bin/sh
set -eu

require_value() {
    variable_name="$1"
    value="$(printenv "$variable_name" || true)"

    case "$value" in
        ""|__REEMPLAZAR__*|CAMBIA_ESTE_*|CHANGE_ME*)
            printf '%s\n' "La variable $variable_name debe contener un valor real antes de iniciar la beta." >&2
            exit 64
            ;;
    esac
}

# Impide que un contenedor de beta arranque por accidente con valores vacíos o
# marcadores de ejemplo. Los valores reales llegan únicamente por el archivo
# ignorado deploy/beta/beta.env o por un gestor de secretos externo.
require_value "AUTH_SECRET_KEY"
require_value "PROVIDER_CREDENTIALS_MASTER_KEY"
require_value "POSTGRES_PASSWORD"

exec "$@"
