# Inventario del codebase — Fase 0 (bloques 1 y 2)

Fecha: 2026-08-06
Estado: refleja el estado real del sistema tras los bloques 1 y 2 de Fase 0.

## Bloque 2 completado

### Alembic y migraciones
- `alembic.ini` + `alembic/` inicializados; `env.py` usa `settings.DATABASE_URL` y `Base.metadata` (importa `app.models.user`).
- Migración inicial `87ff91bf578e` (tablas `users`, `subscriptions`). Se ajustó `server_default` a `func.now()` para que sea portable a PostgreSQL.
- `main.py` ejecuta `create_all` solo para URLs SQLite (dev/tests aislados); en PostgreSQL las tablas se crean exclusivamente vía Alembic.

### PostgreSQL en contenedor
- `docker-compose.yml` en la raíz: `postgres:16`, usuario/db `contamind`, healthcheck, volumen persistente, puerto configurable.
- **Hallazgo**: había un PostgreSQL nativo de Windows escuchando en `5432` con locale no-UTF8; sus mensajes de error (cp1252) rompen a psycopg2 (bug conocido #1816, `UnicodeDecodeError`). El contenedor se movió al puerto **5433** y ese es el default de `settings.POSTGRES_PORT`.
- `settings.py`: `DATABASE_URL` ahora se construye desde `POSTGRES_*` (default dev = PostgreSQL en `localhost:5433`); SQLite sigue disponible definiendo `DATABASE_URL` explícitamente.
- Migraciones aplicadas y verificadas contra PostgreSQL (tablas `alembic_version`, `users`, `subscriptions`).

### Normalización de errores
- `app/shared/errors.py`: contrato uniforme `{success: false, error: {code, message, details}, correlation_id}`.
  - `AppError` (excepción de dominio con `code`/`status_code`/`details`).
  - Handlers registrados en la app: `AppError`, `RequestValidationError` (422 `validation_error`), `HTTPException` (incluye `starlette.HTTPException` → 404 de rutas inexistentes) y `Exception` (500 `internal_error`, no filtra detalles, loggea el stacktrace).
  - `register_exception_handlers(app)` invocado en `main.py`.

### Logging estructurado + correlation ID
- `app/shared/logging.py`: `JsonFormatter` (salida JSON por línea), `configure_logging(debug)`, y `RequestLoggingMiddleware` (ASGI puro) que propaga/genera `X-Request-ID`, lo expone en `request.state.request_id` y loggea acceso con `request_id`, `method`, `path`, `status_code`, `duration_ms`.
- El handler de error interno loggea el stacktrace con su `correlation_id`.
- CORS sigue permitiendo el header `X-Request-ID`.

### Feature flags
- `settings.FEATURE_FLAGS: dict[str, bool]` (JSON en `.env`).
- `app/config/features.py`: constantes (`DIAN_INTEGRATION_ENABLED`, `SIIGO_INTEGRATION_ENABLED`, `LLM_ENABLED`, `MOCK_EXTERNAL_SERVICES`) + `is_enabled()` / `enabled_features()`.
- `bootstrap.py` registra la tool MOCK solo si `MOCK_EXTERNAL_SERVICES` está habilitada (default True) y loggea la decisión.

### Pruebas (suite: 28 verdes)
- Nuevas: `tests/test_errors.py` (7) y `tests/test_features.py` (6). Resto de la suite sin cambios de resultado.

## 1. Inventario de componentes

### En uso (ruta activa)
| Componente | Ubicación | Estado |
|---|---|---|
| App FastAPI + CORS + logging + errores | `backend/main.py` | Estabilizado |
| Auth JWT + admin suscripciones | `app/api/v1/auth.py`, `admin.py` | Sin cambios |
| Chat API | `app/api/v1/chat/` | Estabilizado |
| Orquestador | `app/ai/orchestrator/orchestrator.py` | Corregido |
| Resolución de intents | `app/ai/orchestrator/intent_resolver.py` | Sin cambios |
| Catálogo de intents | `app/ai/orchestrator/intent_catalog.py` | Reducido a intents con workflow real |
| WorkflowManager | `app/ai/workflows/manager.py` | Corregido |
| Workflow chat / exógena | `app/ai/workflows/chat/`, `exogena/` | Corregidos |
| Registro de tools | `app/ai/tools/registry.py` | En uso |
| Registro de agentes | `app/ai/registry/` | En uso |
| Bootstrap | `app/ai/bootstrap/bootstrap.py` | Corregido + gated por feature flag |
| Sesiones | `app/ai/session/manager.py` | En uso |
| Tool mock | `app/ai/tools/consultar_obligaciones.py` | MOCK explícito |
| DB y migraciones | `app/database/`, `alembic/` | Alembic configurado |
| Contrato de errores | `app/shared/errors.py` | Nuevo |
| Logging estructurado | `app/shared/logging.py` | Nuevo |
| Feature flags | `app/config/features.py` | Nuevo |

### Código muerto / dormido (conservado, sin ruta de ejecución)
| Componente | Ubicación | Decisión |
|---|---|---|
| Dispatcher / WorkflowResolver | `app/ai/orchestrator/dispatcher.py`, `workflow_resolver.py` | Rediseño Fase 3 |
| ToolSelector | `app/ai/tools/selector.py` | Reemplazado por catálogo Fase 3 |
| Sistema de tareas | `app/ai/tasks/` | Rediseño Fase 3 |
| WorkflowStep | `app/ai/workflows/core/workflow_step.py` | Uso Fase 3 |
| Agente DIAN | `app/ai/agents/dian/` | Dormido; base del agente real Fases 3-4 |
| Memoria | `app/ai/memory/` | Diseño Fase 3 |
| Integraciones externas | `app/integrations/` (dian, siigo, alegra, worldoffice) | Sin implementación; Fases 3-4 |
| Módulos de negocio | `app/modules/` (rut, exogena, facturacion, nomina, conciliacion) | Sin implementación; Fases 3-5 |

### Código eliminado (Bloque 1)
| Archivo | Motivo |
|---|---|
| `app/ai/tools/implementations/*.py` (4 archivos vacíos) | Rompían el import de `bootstrap` |
| `app/ai/workflows/exogena/states/running.py` | Estado huérfano que provocaba `KeyError` |

## 2. Defectos corregidos (Bloque 1)

| # | Defecto | Corrección |
|---|---|---|
| 1 | `orchestrator.py` invocaba `manager.get()` sobre el módulo | Import explícito de `workflow_manager` |
| 2 | `bootstrap` importaba tool desde archivo vacío | Tool real + eliminación de archivos vacíos |
| 3 | `bootstrap()` nunca se invocaba | Invocación en `main.py` |
| 4 | `from app.ai.bootstrap import bootstrap` → módulo, no función | Import explícito |
| 5 | `from app.ai.tools import registry` → módulo, no instancia | Import explícito |
| 6 | No existía workflow `chat` | Nuevo `ChatWorkflow` |
| 7 | Intents sin workflow → `ValueError` | Catálogo limitado |
| 8 | `context.user_message` nunca seteado | Seteo en el orquestador |
| 9 | Flujo multi-turno reiniciado por `Context` nuevo por request | `SessionManager` |
| 10 | Fin de flujo dejaba estado `RUNNING` → `KeyError` | Reset de estado al cerrar |
| 11 | `session_id` inexistente en `Context` | Mapeo a `conversation_id` |
| 12 | `AUTH_SECRET_KEY` hardcodeada | Secret obligatorio en staging/production |
| 13 | Versión inconsistente en `health.py` | Uso de `settings.VERSION` |
| 14 | `datetime.utcnow()` deprecado | `datetime.now(timezone.utc)` |
| 15 | `.venv` (Linux) committeado y roto | Desregistrado + `.gitignore` |
| 16 | `.gitignore` insuficiente | Ampliado |

## 3. Decisiones tomadas

- PostgreSQL en puerto 5433 (evita conflicto con instalación nativa de Windows en 5432).
- `create_all` solo para SQLite; PostgreSQL gestionado por Alembic.
- Contrato de errores uniforme para toda la API; los errores 500 no filtran detalles internos.
- Mocks identificados explícitamente y controlados por feature flag.
- Se conserva el código dormido para las Fases 3-5.

## 4. Pruebas

Suite en `backend/tests/` (28 pruebas, verdes):
- `test_health.py` (4), `test_chat.py` (5), `test_bootstrap.py` (1), `test_settings.py` (4), `test_errors.py` (7), `test_features.py` (6).

## 5. Pendientes para el cierre de Fase 0

- Actualizar README con instrucciones de arranque (docker compose, alembic, tests).
- Inventario final actualizado al cierre completo.
