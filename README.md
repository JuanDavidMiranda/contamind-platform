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
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip install pytest pytest-asyncio httpx

# 2. Configuración
Copy-Item .env.example .env   # ajustar valores según ambiente

# 3. Base de datos (PostgreSQL en contenedor)
docker compose up -d          # desde la raíz del repo
.\.venv\Scripts\alembic.exe upgrade head

# 4. Ejecutar el servidor
.\.venv\Scripts\python.exe -m uvicorn main:app --reload
```

> Pruebas rápidas aisladas con SQLite: definir `DATABASE_URL=sqlite:///./contamind.db` en `.env` (conveniente para tests sin contenedor).

## Migraciones

```powershell
.\.venv\Scripts\alembic.exe revision --autogenerate -m "descripción"
.\.venv\Scripts\alembic.exe upgrade head
```

## Pruebas

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

## Configuración por ambiente

`backend/.env.example` documenta las variables. Puntos clave:

- `AUTH_SECRET_KEY`: obligatoria en `staging` y `production`; en `development` se autogenera si no se define.
- `DATABASE_URL`: por defecto apunta a PostgreSQL del contenedor; se puede sobrescribir a SQLite.
- `FEATURE_FLAGS` (JSON): `DIAN_INTEGRATION_ENABLED`, `SIIGO_INTEGRATION_ENABLED`, `LLM_ENABLED`, `MOCK_EXTERNAL_SERVICES`. Las integraciones externas NO están implementadas (Fases 3-4); los mocks están marcados explícitamente.

## Contrato de errores

Todos los endpoints devuelven errores con forma uniforme:

```json
{
  "success": false,
  "error": { "code": "validation_error", "message": "Datos de entrada inválidos.", "details": [] },
  "correlation_id": "uuid"
}
```

Los logs de acceso y errores son JSON por línea e incluyen `request_id` (propagable vía header `X-Request-ID`).

## Estado del proyecto

- Fase 0 (estabilización): arranque limpio, imports, workflow de chat/exógena, pruebas (28 verdes), config segura, Alembic, PostgreSQL en contenedor, contrato de errores, logging estructurado y feature flags. Ver `backend/docs/checkpoint1-fase0.md`.
- Pendiente: multiempresa/multiagente, integraciones DIAN y Siigo (requiere credenciales), módulos de negocio.
