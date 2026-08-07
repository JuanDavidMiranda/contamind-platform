# Cierre de Fase 0 — Checkpoint 2

Fecha: 2026-08-06
Estado: Fase 0 cerrada. Árbol en verde (`ruff check . --select E9,F` limpio; `pytest` 61 tests, con PostgreSQL incluido).

El Checkpoint 1 cubrió los bloques 1-2 (ver `docs/checkpoint1-fase0.md`). Este documento cierra Fase 0 con el Checkpoint 2: catálogo de errores estable, health checks live/ready, `SessionManager` endurecido, eliminación de código muerto, tooling de calidad y suite ampliada.

## 1. Alcance aprobado

- Eliminar `backend/app/api/v1/chat/chat.py` (código muerto, sin referencias).
- Añadir Ruff con **solo** `--select E9,F` (sin autofix ni reformateo; correcciones locales seguras de F401 únicamente).
- No tocar RBAC completo, multiempresa, LLM, DIAN real, Siigo real ni frontend.
- Mantener la API pública de `session_manager`; conservar `/health` y `/agents`; añadir únicamente `/health/live` y `/health/ready`.
- Sin secretos reales en `.env.example`, tests ni docs.

## 2. Catálogo de errores estable

`app/shared/error_catalog.py` define `ErrorDefinition(code, http_status, message, recoverable)` y el dict `ERROR_CATALOG`. `get_error_definition(code)` cae a `INTERNAL_ERROR` si el código no existe.

| Código | HTTP | recoverable | Mensaje |
|---|---|---|---|
| `VALIDATION_ERROR` | 422 | True | Datos de entrada inválidos. |
| `AUTH_MISSING_TOKEN` | 401 | True | No se proporcionó un token de autenticación. |
| `AUTH_INVALID_TOKEN` | 401 | True | Token de autenticación inválido o con formato incorrecto. |
| `AUTH_EXPIRED_TOKEN` | 401 | True | Token de autenticación expirado. |
| `AUTH_INVALID_CREDENTIALS` | 401 | True | Credenciales inválidas. |
| `FORBIDDEN` | 403 | False | No tiene permisos para realizar esta operación. |
| `NOT_FOUND` | 404 | True | Recurso no encontrado. |
| `CONFLICT` | 409 | True | Conflicto con el estado actual del recurso. |
| `DEPENDENCY_DISABLED` | 503 | True | La dependencia requerida está deshabilitada. |
| `SERVICE_UNAVAILABLE` | 503 | True | Servicio temporalmente no disponible. |
| `INTERNAL_ERROR` | 500 | False | Error interno del servidor. |

Cambios en `app/shared/errors.py`:

- `AppError` ahora acepta `recoverable`; nueva factory `app_error(code, details, message, status_code)`.
- `ErrorDetail` usa `code`, `message`, `recoverable`, `details` (antes `error_code`/`message`/`details`).
- `_handle_http_error` mapea por `_STATUS_CODE_TO_CATALOG`: 401→`AUTH_INVALID_CREDENTIALS`, 403, 404, 409, 503.
- `_handle_validation_error` usa `VALIDATION_ERROR`; el handler 500 sanitiza la respuesta (sin internos) y loggea el stacktrace.
- `security.py` lanza `app_error("AUTH_MISSING_TOKEN"|"AUTH_EXPIRED_TOKEN"|"AUTH_INVALID_TOKEN")`; `auth.py` login usa `AUTH_INVALID_CREDENTIALS`.

## 3. Health checks

`app/api/v1/health.py`:

- `GET /health` (conservado): `status`, `application`, `version`.
- `GET /agents` (conservado): registros del runtime (bootstrap registra únicamente la tool MOCK; el registro de agentes queda para Fase 3).
- `GET /health/live` (nuevo): solo liveness, sin tocar la BD.
- `GET /health/ready` (nuevo): `SELECT 1` contra el `engine` de la app; si falla responde `app_error("SERVICE_UNAVAILABLE")`, loggea `ready check failed` con `request_id` y **no** expone detalles internos (test verifica que no filtre `postgresql|contamind|5433|password`).

## 4. SessionManager endurecido

`app/ai/session/manager.py` reescrito con API pública preservada:

- `SessionStore` (ABC): `get`, `save`, `delete`, `size` — interfaz reemplazable.
- `InMemorySessionStore`: `OrderedDict` con `(last_access, Context)`, purga por TTL y evicción LRU.
- `SessionManager(store=None, max_sessions=None, ttl_seconds=None)` con defaults de `settings`; `TEMPORARY_PERSISTENCE = True` (persistencia en memoria: no sobrevive reinicios).
- Nueva API: `active_count`.

Nuevos settings (documentados en `.env.example`): `SESSION_MAX_ACTIVE=1000`, `SESSION_TTL_SECONDS=3600`.

## 5. Código muerto: eliminación de `chat.py`

`app/api/v1/chat/chat.py` se eliminó: no aparecía en `app/api/router.py` (que importa `chat.controller`), tenía imports rotos y no estaba registrado en ninguna ruta.

Inventario final de código sin ruta de ejecución (conservado para Fases 3-5):

| Componente | Ubicación | Plan |
|---|---|---|
| Dispatcher / WorkflowResolver | `app/ai/orchestrator/dispatcher.py`, `workflow_resolver.py` | Rediseño Fase 3 |
| ToolSelector | `app/ai/tools/selector.py` | Reemplazado por catálogo Fase 3 |
| Sistema de tareas | `app/ai/tasks/` | Rediseño Fase 3 |
| WorkflowStep | `app/ai/workflows/core/workflow_step.py` | Uso Fase 3 |
| Agente DIAN | `app/ai/agents/dian/` | Dormido; base del agente real Fases 3-4 |
| Memoria | `app/ai/memory/` | Diseño Fase 3 |
| Integraciones externas | `app/integrations/` (dian, siigo, alegra, worldoffice) | Sin implementación; Fases 3-4 |
| Módulos de negocio | `app/modules/` (rut, exogena, facturacion, nomina, conciliacion) | Sin implementación; Fases 3-5 |

## 6. Tooling de calidad

- `backend/ruff.toml`: `target-version = "py313"`, `line-length = 100`, `select = ["E9","F"]` (sin autofix), excludes `alembic/versions`, `.venv`, `__pycache__`.
- `backend/requirements-dev.txt` (pinneado): `ruff==0.16.1`, `pytest==9.1.1`, `pytest-asyncio==1.4.0`, `httpx2==2.9.1` (requerido por TestClient de Starlette 1.3.1).
- `backend/pytest.ini`: markers `unit`, `integration`, `postgres` con descripciones.
- Scripts PowerShell + Makefile (objetivos equivalentes): `setup`, `lint`, `test`, `test-postgres`, `migrate`, `run`.

## 7. Suite de pruebas (61 tests)

| Marker | Archivo | Count |
|---|---|---|
| unit | `test_settings.py` | 4 |
| unit | `test_features.py` | 6 |
| unit | `test_bootstrap.py` | 1 |
| unit | `test_error_catalog.py` | 5 |
| unit | `test_session_manager.py` | 9 |
| unit | `test_registries.py` | 5 |
| unit | `test_secrets_in_logs.py` | 2 |
| integration | `test_health.py` | 4 |
| integration | `test_chat.py` | 5 |
| integration | `test_errors.py` | 8 |
| integration | `test_health_checks.py` | 3 |
| integration | `test_auth.py` | 8 |
| postgres | `test_migrations.py` | 1 |

Ejecución por defecto: `60 passed, 1 skipped` (postgres opt-in). Con `RUN_POSTGRES_TESTS=1` + `POSTGRES_TEST_DATABASE_URL`: `61 passed`.

Nota local: en `::1:5433` escucha `wslrelay` (rechaza la contraseña de contamind); el contenedor Docker responde en `127.0.0.1:5433`. Las pruebas usan `127.0.0.1` vía `POSTGRES_TEST_DATABASE_URL`.

Nuevos tests destacados:

- `test_session_manager.py` (9): aislamiento, recreación de contexto, evicción LRU, TTL caducado, store inyectado, singleton con API pública, y `test_context_never_holds_secrets`.
- `test_auth.py` (8): login ok/401/desconocido, sin token, token inválido, token expirado (`AUTH_TOKEN_TTL_MINUTES=-1`), 403 no-admin, admin lista subscriptions.
- `test_registries.py` (5): registros únicos idempotentes, `AgentNotFoundException`, mock registrado exactamente una vez.
- `test_secrets_in_logs.py` (2): `request_id` en logs JSON; `AUTH_SECRET_KEY` nunca aparece en el log de error.
- `test_migrations.py` (1): base vacía temporal, `create`+`drop`, Alembic `upgrade head` desde cero.
- `test_error_catalog.py` (5) y `test_health_checks.py` (3): catálogo estable y ready 503 sin filtrado de internos.

## 8. Smoke manual contra PostgreSQL

Servidor `uvicorn main:app` con `DATABASE_URL=postgresql+psycopg2://contamind:contamind@127.0.0.1:5433/contamind`:

| Llamada | Resultado |
|---|---|
| `GET /api/v1/health` | `{"status":"healthy","application":"ContaMind AI","version":"0.1.0"}` |
| `GET /api/v1/health/live` | `{"status":"ok"}` |
| `GET /api/v1/health/ready` | `{"status":"ready","database":"up"}` |
| `GET /api/v1/agents` | `{"value":[],"Count":0}` (runtime sin agentes registrados, esperado) |
| `GET /api/v1/no-such-route` | HTTP 404, cuerpo `{"success":false,"error":{"code":"NOT_FOUND","message":"Recurso no encontrado.","recoverable":true,...},"correlation_id":"..."}` |
| `POST /api/v1/chat {}` | HTTP 422, cuerpo `VALIDATION_ERROR` con `details` de campos faltantes |
| `POST /api/v1/auth/login` (correcto) | 200, token JWT + `user_id` + `is_platform_admin: true` |
| `POST /api/v1/auth/login` (incorrecto) | HTTP 401 |
| `GET /api/v1/admin/subscriptions` (token admin) | 200, lista (vacía) |
| Chat exógena: "quiero hacer exogena" | "Perfecto. ¿Cuál es el NIT de la empresa?" |
| Chat exógena: "900123456" | "Excelente. ¿Cuál es el año gravable?" |
| Chat exógena: "2025" | "Perfecto. Voy a preparar la exógena del año 2025 para la empresa 900123456." |

El flujo de chat exógena en tres requests HTTP independientes confirma la persistencia de sesión vía `SessionManager`.

## 9. Archivos creados / modificados / eliminados

Creados: `app/shared/error_catalog.py`, `tests/test_error_catalog.py`, `tests/test_health_checks.py`, `tests/test_session_manager.py`, `tests/test_auth.py`, `tests/test_registries.py`, `tests/test_secrets_in_logs.py`, `tests/test_migrations.py`, `pytest.ini`, `ruff.toml`, `requirements-dev.txt`, `scripts/{setup,lint,test,test-postgres,migrate,run}.ps1`, `Makefile`, `docs/cierre-fase0.md`.

Modificados: `app/shared/errors.py`, `app/shared/security.py`, `app/api/v1/auth.py`, `app/api/v1/health.py`, `app/ai/session/manager.py`, `app/config/settings.py`, `.env.example`, `main.py` (`# noqa: F401`), tests existentes (markers + códigos de error), `README.md`.

Eliminados: `app/api/v1/chat/chat.py`.

## 10. Commits

- `cadfb56` — `chore(shared): stable error catalog and health live/ready endpoints` (36 tests verdes)
- `b1bc481` — `feat(session): harden SessionManager with store interface, limits and TTL` (45 tests verdes)
- `ca3055f` — `chore: delete dead chat router, add ruff (E9,F) and dev requirements` (45 tests verdes)
- `9d19fa0` — `test: expand suite with unit/integration/postgres markers and quality scripts` (61 tests verdes)

## 11. Deuda técnica trasladada (no bloqueante)

- RBAC completo, multiempresa/multiagente, LLM real, DIAN real, Siigo real, frontend.
- Rediseño del código dormido (Dispatcher, ToolSelector, tareas, WorkflowStep, agentes DIAN, memoria, integraciones, módulos) en Fases 3-5.
- Auditoría de imports muertos restantes durante el spike de Fase 1.
- El venv `.venv` original estaba roto; se recreó con `python -m venv .venv` + `pip install -r requirements-dev.txt`.
- Peculiaridad local `::1:5433` (wslrelay) documentada; las pruebas y el smoke usan `127.0.0.1`.

## 12. Cierre

Fase 0 cerrada: arranque limpio, catálogo de errores estable, health checks, sesiones endurecidas con interfaz reemplazable, tooling de calidad reproducible y 61 tests en verde contra PostgreSQL. Siguiente: Fase 1 (consolidar decisiones del código dormido y primer vertical de negocio).
