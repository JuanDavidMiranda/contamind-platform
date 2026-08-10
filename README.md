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
- Pendiente: ampliar adaptadores financieros y el vertical DIAN, ejecutar sincronizaciones en segundo plano para grandes volúmenes, multiagente y módulos de negocio. Las integraciones reales requieren credenciales y autorizaciones de los proveedores.

### Arquitectura multi-proveedor

ContaMind no prioriza ni acopla el dominio a una marca. Los proveedores se registran mediante un identificador configurable y una modalidad de integración (`cloud_api`, intercambio de archivos, agente local, conector de base de datos o integración mediada por proveedor). Siigo, Novasoft y SysCafé son ejemplos de sistemas que pueden incorporarse cuando se confirme su contrato técnico y existan autorizaciones y datos de prueba. Ver `backend/docs/adr/0008-proveedores-configurables-y-modalidades.md`.

### Fuentes de datos por empresa

La captura manual de terceros ya está disponible para fuentes `manual_entry`. Se mantiene el mismo modelo canónico y la misma persistencia que usa una importación de archivo.

Cada empresa configura una o varias fuentes de datos: software contable conectado, exportaciones CSV/XLSX, agente o conector local de base de datos, captura manual y servicios fiscales como DIAN. Todas alimentan el mismo modelo canónico. Las rutas universales implementadas importan terceros desde CSV y XLSX con perfiles de mapeo, rechazos por fila, auditoría y persistencia; bases de datos y conectores locales requieren sus interfaces/agentes autorizados antes de habilitarse. Ver `backend/docs/adr/0009-fuentes-de-datos-por-empresa.md`.

### Acceso por empresa

El acceso a datos se controla mediante membresías por empresa: `owner`, `admin`, `operator` y `viewer`. Un operador puede importar y capturar información únicamente dentro de las fuentes de las empresas donde es miembro; no puede configurarlas. Los administradores de plataforma se reservan para soporte y para asignar el primer propietario. Ver `backend/docs/adr/0010-rbac-y-membresias-por-empresa.md`.

### Onboarding de empresas

`POST /api/v1/companies/onboarding` crea un tenant, su primera empresa y la membresía `owner` del usuario autenticado en una sola transacción. `GET /api/v1/companies/mine` lista exclusivamente las empresas disponibles para ese usuario. Fuentes y membresías verifican que la empresa exista y cada fuente, lote de importación y tercero guarda la referencia del usuario que lo creó o actualizó. Ver `backend/docs/adr/0011-empresas-persistidas-y-onboarding.md`.

### Ciclo de vida multiempresa

El propietario de un tenant puede crear razones sociales adicionales con `POST /api/v1/tenants/{tenant_id}/companies`. Las empresas se editan, desactivan o reactivan sin borrarlas; una empresa desactivada no acepta nuevas configuraciones, importaciones ni capturas. `GET /api/v1/companies/{company_id}/audit` expone la trazabilidad de fuentes, importaciones y capturas manuales para los miembros autorizados. Ver `backend/docs/adr/0012-ciclo-de-vida-multiempresa-por-tenant.md`.

### Captura manual contable

Las fuentes manuales activas pueden registrar impuestos, ítems, facturas, pagos y comprobantes contables. Cada operación exige `Idempotency-Key`, conserva empresa, fuente y autor, y valida referencias internas; los comprobantes además deben cuadrar por partida doble. Ver `backend/docs/adr/0013-captura-manual-del-nucleo-contable.md`.

### Importación contable CSV/XLSX

Las fuentes de archivos pueden importar impuestos, ítems, facturas, pagos y comprobantes con perfiles de mapeo por entidad. Las facturas y comprobantes agrupan sus líneas, resuelven referencias por código o documento y registran rechazos por fila sin descartar el lote completo. Ver `backend/docs/adr/0014-importacion-tabular-del-nucleo-contable.md`.

### Conexiones externas y sincronización

Las fuentes con proveedor se crean en estado `pending`. Un administrador configura credenciales mediante `PUT /api/v1/data-sources/{id}/credentials` y ejecuta `POST /api/v1/data-sources/{id}/connection-test`; solo una prueba exitosa habilita la fuente. Las credenciales se almacenan cifradas con Fernet y jamás aparecen en respuestas o auditorías.

`POST /api/v1/data-sources/{id}/sync/parties` sincroniza una página de terceros y conserva el cursor para la siguiente ejecución. Cada prueba y sincronización queda en `GET /api/v1/data-sources/{id}/connection-runs`, con actor, correlación, cursor, conteo y código de error, sin payloads sensibles. La primera referencia de API es Siigo, protegida por `SIIGO_INTEGRATION_ENABLED`; no hay proveedor prioritario y los conectores por archivo, agente local o base de datos usan el mismo ciclo. Ver `backend/docs/adr/0015-ciclo-de-vida-de-conexiones-externas.md`.
