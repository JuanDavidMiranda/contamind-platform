# ContaMind AI — Plataforma para automatización contable

Backend FastAPI para la automatización de tareas contables y financieras (DIAN, exógena, integraciones contables).

## Requisitos

- Python 3.13
- Docker + Docker Compose (para PostgreSQL de desarrollo)
- PostgreSQL 16 vía contenedor (puerto 5433; evita conflicto con instalaciones locales en 5432)

## Puesta en marcha

```powershell
# 1. Entorno virtual e instalación de dependencias
cd backend
.\scripts\setup.ps1          # python -m venv .venv + pip install -r requirements.txt y requirements-dev.txt

# 2. Configuración
Copy-Item .env.example .env   # ajustar valores según ambiente

# 3. Base de datos (PostgreSQL en contenedor)
docker compose up -d          # desde la raíz del repo
.\scripts\migrate.ps1         # alembic upgrade head

# 4. Ejecutar el servidor
.\scripts\run.ps1             # uvicorn main:app --reload
```

> Pruebas rápidas aisladas con SQLite: definir `DATABASE_URL=sqlite:///./contamind.db` en `.env` (conveniente para tests sin contenedor).

## Calidad

```powershell
.\scripts\lint.ps1          # ruff check . --select E9,F (solo errores de sintaxis e imports)
.\scripts\test.ps1          # pytest por defecto (unit + integration)
.\scripts\test-postgres.ps1 # pytest con postgres opt-in (requiere contenedor en 5433)
```

## Health checks

- `GET /api/v1/health` — estado general (aplicación, versión).
- `GET /api/v1/health/live` — liveness (no toca la BD).
- `GET /api/v1/health/ready` — readiness: `SELECT 1` contra la BD; 503 sin exponer internos.

## Migraciones

```powershell
.\.venv\Scripts\alembic.exe revision --autogenerate -m "descripción"
.\.venv\Scripts\alembic.exe upgrade head
```

## Pruebas

La suite usa markers: `unit`, `integration` y `postgres` (opt-in, requiere contenedor en `127.0.0.1:5433`).

```powershell
.\scripts\test.ps1            # por defecto: unit + integration (60 passed, 1 skipped)
.\scripts\test-postgres.ps1   # incluye test_migrations (61 passed)
```

## Configuración por ambiente

`backend/.env.example` documenta las variables. Puntos clave:

- `AUTH_SECRET_KEY`: obligatoria en `staging` y `production`; en `development` se autogenera si no se define.
- `DATABASE_URL`: por defecto apunta a PostgreSQL del contenedor; se puede sobrescribir a SQLite.
- `FEATURE_FLAGS` (JSON): `DIAN_INTEGRATION_ENABLED`, `SIIGO_INTEGRATION_ENABLED`, `LLM_ENABLED`, `MOCK_EXTERNAL_SERVICES`. Las integraciones externas NO están implementadas (Fases 3-4); los mocks están marcados explícitamente.
- Sesiones: `SESSION_MAX_ACTIVE` (límite de sesiones activas, evicción LRU) y `SESSION_TTL_SECONDS` (expiración por inactividad). La persistencia de sesión es temporal en memoria (`TEMPORARY_PERSISTENCE=True`): no sobrevive reinicios.

## Contrato de errores

Todos los endpoints devuelven errores con forma uniforme, con códigos estables del catálogo (`backend/app/shared/error_catalog.py`): `VALIDATION_ERROR` (422), `AUTH_MISSING_TOKEN`/`AUTH_INVALID_TOKEN`/`AUTH_EXPIRED_TOKEN`/`AUTH_INVALID_CREDENTIALS` (401), `FORBIDDEN` (403), `NOT_FOUND` (404), `CONFLICT` (409), `SERVICE_UNAVAILABLE`/`DEPENDENCY_DISABLED` (503), `INTERNAL_ERROR` (500).

```json
{
  "success": false,
  "error": { "code": "VALIDATION_ERROR", "message": "Datos de entrada inválidos.", "recoverable": true, "details": [] },
  "correlation_id": "uuid"
}
```

Los logs de acceso y errores son JSON por línea e incluyen `request_id` (propagable vía header `X-Request-ID`).

## Estado del proyecto

- Fase 0 (cerrada): arranque limpio, imports, workflow de chat/exógena, pruebas (61 verdes, incluye PostgreSQL), config segura, Alembic, PostgreSQL en contenedor, catálogo de errores estable, health checks live/ready, sesiones con TTL/LRU e interfaz reemplazable, logging estructurado, feature flags y tooling Ruff/markers. Ver `backend/docs/checkpoint1-fase0.md` y `backend/docs/cierre-fase0.md`.
- Fase 1 (spike de viabilidad DIAN/Siigo/Alegra/World Office — documental, sin código productivo): arquitectura de proveedores neutral (ADR-0001), vertical DIAN con GetAcquirer como primer piloto (ADR-0002), evaluación de Siigo/Alegra/World Office (ADR-0003/0004/0005), modelo contable canónico (ADR-0006) y estrategia de autenticación transversal (ADR-0007). Ver `backend/docs/adr/` y `backend/docs/spike-fase1.md`.
- Pendiente: Fase 2 (infraestructura de proveedores: ports, modelo canónico, contracts), Fase 3 (primer adaptador financiero), Fase 4 (primer vertical DIAN), multiempresa/multiagente y módulos de negocio. Las integraciones reales requieren credenciales de los proveedores (los nombres previstos de variables están documentados en los ADR, no en `.env.example`).
