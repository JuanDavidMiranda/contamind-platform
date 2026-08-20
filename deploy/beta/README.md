# Beta privada local de ContaMind

Esta configuración crea una pila repetible de **uso local**: PostgreSQL, migraciones Alembic, API FastAPI, workers de sincronización y de habilitación DIAN, y frontend. Los únicos puertos publicados se enlazan a `127.0.0.1`; por diseño no expone el producto a Internet.

No sustituye la preparación de una beta externa. Antes de dar acceso a un cliente desde Internet deben existir HTTPS con un proxy inverso, dominio y CORS HTTPS definitivos, copias de seguridad verificadas, monitoreo, límites de solicitud y una prueba en PostgreSQL limpio. Consulta también [la guía de beta privada](../../docs/beta-privada.md).

## Preparación

Desde la raíz del repositorio, crea el archivo local de variables:

```powershell
Copy-Item deploy/beta/beta.env.example deploy/beta/beta.env
```

Completa en `deploy/beta/beta.env` como mínimo:

- `POSTGRES_PASSWORD`: contraseña larga y exclusiva de esta base local.
- `AUTH_SECRET_KEY`: secreto aleatorio de al menos 32 caracteres.
- `PROVIDER_CREDENTIALS_MASTER_KEY`: una clave Fernet válida.

Puedes generar los dos últimos valores con el entorno Python del backend:

```powershell
.\backend\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(48))"
.\backend\.venv\Scripts\python.exe -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

No completes `OPENAI_API_KEY`, `DIAN_ACQUIRER_URL` ni actives ninguna bandera de integración para este piloto. La plantilla deja todas las integraciones reales y los mocks en `false`.

## Arranque y comprobación

Docker Desktop debe estar abierto y su motor debe estar en ejecución. Construye e inicia los servicios:

```powershell
docker compose --env-file deploy/beta/beta.env -f compose.beta.local.yml up --build -d
docker compose --env-file deploy/beta/beta.env -f compose.beta.local.yml ps
```

La primera orden ejecuta las migraciones antes de iniciar API y los workers. Comprueba que los servicios persistentes estén `running` y que `migrate` haya finalizado con código `0`. `dian-habilitation-worker` permanece inactivo respecto a envíos mientras `DIAN_ELECTRONIC_HABILITATION_ENABLED` sea `false`.

```powershell
Invoke-WebRequest http://localhost:8000/api/v1/health/ready
Invoke-WebRequest http://localhost:3000/
```

La interfaz queda en <http://localhost:3000/> y la API queda en <http://localhost:8000/>. El frontend recibe `BETA_API_BASE_URL` durante la compilación: si cambias ese valor debes reconstruir con `up --build`.

Para crear el primer administrador sin usar credenciales de demostración, ejecuta en una consola controlada:

```powershell
docker compose --env-file deploy/beta/beta.env -f compose.beta.local.yml exec api python scripts/provision_platform_admin.py --email operador@tuempresa.com --full-name "Operador ContaMind"
```

El comando solicita la contraseña de forma interactiva y no la imprime. Añade ese correo a `PLATFORM_ADMIN_EMAILS` antes de ejecutar una beta con `ENVIRONMENT=staging`.

## Detención y datos

```powershell
docker compose --env-file deploy/beta/beta.env -f compose.beta.local.yml down
```

Este comando conserva el volumen `contamind_beta_pgdata`. Para eliminar deliberadamente todos los datos locales y reconstruir desde cero, usa `down -v`; es una acción destructiva.

Las variables `POSTGRES_USER`, `POSTGRES_PASSWORD` y `POSTGRES_DB` solo inicializan un volumen nuevo. Si ya existe `contamind_beta_pgdata`, no las cambies esperando que PostgreSQL actualice sus credenciales: realiza una rotación administrada o reinicializa únicamente si los datos pueden eliminarse.

## Límites de esta configuración

- Está pensada para una única réplica de API, un worker de sincronización y un worker de habilitación DIAN. Las sesiones conversacionales y parte del control de tasa actual viven en memoria y no se comparten entre réplicas.
- No incluye proxy HTTPS, certificados, copias de seguridad automáticas, restauración, observabilidad ni exposición pública. No publiques los puertos cambiando `127.0.0.1` por `0.0.0.0`.
- La pila usa etiquetas mayores de imágenes (`python:3.13-slim-bookworm`, `node:22.13-bookworm-slim`, `postgres:16-bookworm`) para desarrollo local. Antes de una beta externa, fíjalas a digests revisados dentro del proceso de entrega.
- Ejecuta una vez `docker compose ... up --build` sobre una base vacía y verifica `/api/v1/health/ready` antes de invitar al cliente. No ingreses datos productivos, certificados ni credenciales DIAN hasta completar la validación de esa integración.
