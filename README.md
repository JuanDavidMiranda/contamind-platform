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

# 5. En otra terminal, consumir sincronizaciones externas en segundo plano
.\scripts\run-sync-worker.ps1  # cola persistente de proveedores
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
.\scripts\test.ps1            # por defecto: unit + integration (129 passed, 1 skipped)
.\scripts\test-postgres.ps1   # añade la validación real de migraciones PostgreSQL
```

### Siigo sin credenciales reales

El contrato inicial de Siigo se valida sin red ni secretos mediante
`httpx.MockTransport`. Estas pruebas cubren autenticación, paginación y mapeo de
terceros, además de credenciales incompletas, Partner-Id inválido, respuestas de
autenticación incorrectas, rate limiting y payloads incompatibles.

La prueba de integración `test_siigo_connection_e2e.py` recorre onboarding,
creación de fuente, cifrado de credenciales ficticias, prueba de conexión,
sincronización paginada, persistencia, auditoría y aislamiento multiempresa.

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest tests\test_siigo_adapter.py -q
```

`SIIGO_INTEGRATION_ENABLED` debe permanecer en `false` hasta disponer de
credenciales autorizadas. `MOCK_EXTERNAL_SERVICES` habilita herramientas mock de
la aplicación, pero no sustituye silenciosamente el adaptador real de Siigo.

## Configuración por ambiente

`backend/.env.example` documenta las variables. Puntos clave:

- `AUTH_SECRET_KEY`: obligatoria en `staging` y `production`; en `development` se autogenera si no se define.
- `DATABASE_URL`: por defecto apunta a PostgreSQL del contenedor; se puede sobrescribir a SQLite.
- `FEATURE_FLAGS` (JSON): `DIAN_INTEGRATION_ENABLED`, `SIIGO_INTEGRATION_ENABLED`, `LLM_ENABLED`, `MOCK_EXTERNAL_SERVICES`. Siigo dispone de un adaptador inicial de lectura, siempre deshabilitado por defecto; el resto de integraciones requiere su propio adaptador y autorización.
- Worker de proveedores: `PROVIDER_SYNC_MAX_ATTEMPTS`, `PROVIDER_SYNC_RETRY_BASE_SECONDS`, `PROVIDER_SYNC_RETRY_MAX_SECONDS`, `PROVIDER_SYNC_LEASE_SECONDS`, `PROVIDER_SYNC_WORKER_BATCH_SIZE` y `PROVIDER_SYNC_WORKER_POLL_SECONDS` controlan reintentos, recuperación y consumo de la cola.
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
- Pendiente: validar adaptadores con credenciales autorizadas, ampliar la cobertura financiera y el vertical DIAN, y desarrollar los módulos de negocio. Las integraciones reales requieren credenciales y autorizaciones de los proveedores.

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

### Agente de salud contable

El agente combina un análisis determinista y de solo lectura con una capa conversacional opcional. La interfaz que debe usar un asistente de salud contable es `POST /api/v1/companies/{company_id}/agents/accounting-health/chat`: fija el agente durante toda la conversación y acepta preguntas libres dentro de su propósito, por ejemplo, “¿qué debo revisar primero?” o “¿cómo corrijo un comprobante descuadrado?”. El usuario debe tener un rol de consulta sobre la empresa (owner, admin, operator o viewer). El chat general `POST /api/v1/companies/{company_id}/chat` conserva la selección por intención y no fuerza llamadas al agente para preguntas arbitrarias.

El backend siempre calcula primero las métricas y hallazgos verificables. Si LLM_ENABLED está activo y existe OPENAI_API_KEY, el modelo solo redacta una respuesta en español a partir de una proyección agregada del reporte; esa proyección no recibe company_id, filas de terceros, documentos, correos, credenciales ni permisos. La pregunta e historial se limitan y redactan por patrones conocidos; no constituyen una solución DLP completa, por lo que no se deben enviar datos personales ni secretos al chat. La llamada solicita Responses API sin estado de aplicación (`store=false`), usa un identificador de seguridad HMAC y un historial local limitado. La aplicación rechaza respuestas no ancladas a hallazgos o con cifras libres, valida los códigos citados y conserva el reporte determinista como fuente de verdad.

Actualmente advierte sobre fuentes no disponibles, rechazos de importación, terceros incompletos o duplicados, ítems sin cuenta, facturas sin contraparte, pagos sin factura y comprobantes descuadrados. Cada ejecución deja únicamente metadatos de auditoría en agent_executions (actor, empresa, correlación, resultado y códigos de hallazgo), sin guardar el mensaje, prompt, respuesta del modelo ni reporte. Si el LLM está apagado, no tiene clave o falla, el diagnóstico determinista sigue disponible.

Para habilitar la conversación, define OPENAI_API_KEY y activa LLM_ENABLED dentro de FEATURE_FLAGS; OPENAI_MODEL, OPENAI_TIMEOUT_SECONDS y OPENAI_MAX_OUTPUT_TOKENS permiten ajustar el proveedor. Antes de activarla en producción se requiere aprobación de privacidad, aviso al usuario y el acuerdo de tratamiento/retención aplicable al proveedor. El POST /api/v1/chat heredado continúa siendo anónimo y no puede activar este agente. Ver backend/docs/adr/0017-agente-de-salud-contable.md y backend/docs/adr/0018-capa-llm-conversacional-de-salud-contable.md.

### Agente de cartera

**Estado y supuestos al 2026-08-12.** El agente analiza cartera de facturas de venta y pagos ya registrados; no concilia extractos bancarios, no calcula intereses ni ejecuta comunicaciones o recaudos. Sus resultados son apoyo operativo y requieren revisión humana antes de una decisión contable, financiera o de cobro.

#### Datos de vencimiento e importación

Las facturas canónicas, la captura manual y las importaciones CSV/XLSX aceptan `due_date` y `payment_terms_days`. Los días de pago se validan entre `0` y `3650`; `0` es válido. Si se informa solo `payment_terms_days`, se deriva el vencimiento desde la fecha de expedición. Si se informan ambos valores, deben ser coherentes; una fecha anterior a la expedición o datos inconsistentes entre líneas de la misma factura se rechazan. Las facturas históricas pueden permanecer sin vencimiento hasta que se completen explícitamente.

#### Diagnóstico y antigüedad

`POST /api/v1/companies/{company_id}/agents/receivables/chat` exige una membresía de consulta (`owner`, `admin`, `operator` o `viewer`) y calcula primero un reporte determinista de solo lectura. Incluye saldos abiertos separados por moneda, pagos parciales o superiores, pagos asociados en moneda distinta, fechas faltantes, vencimientos y antigüedad: no vencida, vence hoy, 1–30, 31–60, 61–90 y más de 90 días, además de la categoría sin fecha de vencimiento. Los pagos en otra moneda no se compensan automáticamente. También muestra promedios de recaudo de facturas liquidadas y el estado de seguimientos/promesas vigentes o incumplidas.

El chat no devuelve clientes, documentos ni facturas individuales. `agent_executions` conserva únicamente metadatos de auditoría de la ejecución (actor, empresa, correlación, estado y códigos de hallazgo), sin mensaje, prompt, respuesta del modelo ni reporte completo.

#### Cobertura conversacional y límites

El chat cubre consultas agregadas y verificables sobre todo el módulo de cartera. Puede explicar prioridades y alertas, cantidades de facturas de venta abiertas, sin pago, con pago parcial o superior, vencidas o por vencer, y la antigüedad por rango. También responde por saldos pendientes **separados por moneda**, vencimientos sin fecha, pagos en moneda incompatible, facturas sin tercero, promedios de recaudo de facturas liquidadas y el estado de seguimientos, promesas abiertas o incumplidas. Puede aclarar qué representa una alerta y recomendar la siguiente revisión operativa; no convierte ni suma monedas distintas.

Las preguntas por una factura, cliente, pago, número, consecutivo, referencia o cualquier otro dato individual no se responden por el chat. Este explica el límite de privacidad y dirige al usuario autorizado a **Cartera operativa**, donde está el detalle paginado. Las solicitudes para crear, modificar, cobrar, enviar comunicaciones, registrar pagos o gestionar un seguimiento también están fuera del alcance conversacional: se realizan mediante las rutas operativas autorizadas y sus confirmaciones.

Cuando una pregunta pide una métrica que el reporte no calcula o no puede determinar con los datos disponibles —por ejemplo, proyección de caja, intereses, conciliación bancaria, riesgo crediticio, decisiones jurídicas, tributarias o de otros módulos— el agente lo indica con transparencia y no estima ni inventa cifras. Si falta un dato que sí pertenece a cartera, comunica la alerta de calidad correspondiente y sugiere completarlo en la fuente o revisarlo en la vista operativa.

#### Operación autorizada de cartera

La información individual se ofrece por una API operativa separada, nunca por el chat ni al LLM:

- `GET /api/v1/companies/{company_id}/receivables/open-items` lista facturas de venta abiertas paginadas, su saldo, vencimiento, antigüedad, moneda y último estado de seguimiento. Acepta `as_of`, `limit` y `offset`.
- `PATCH /api/v1/companies/{company_id}/receivables/invoices/{invoice_id}/terms` corrige vencimiento o condiciones de pago únicamente con `confirmed: true`. Registra quién y cuándo actualizó el dato; puede limpiar ambos valores enviando ambos como `null`.
- `GET|POST /api/v1/companies/{company_id}/collection-followups` y `PATCH /api/v1/companies/{company_id}/collection-followups/{followup_id}` gestionan seguimientos. Los estados válidos son `pending`, `contacted`, `promise_to_pay`, `resolved` y `cancelled`; una promesa exige `promised_date` y esa fecha no aplica a los demás estados.

Los roles de consulta pueden leer ítems abiertos y seguimientos. Solo `owner`, `admin` y `operator` de una empresa activa pueden modificar términos o crear/editar seguimientos, siempre con confirmación explícita. Los seguimientos conservan actor y marcas de tiempo; sus notas son opcionales, de máximo 280 caracteres y se rechazan si contienen patrones de correo, identificadores numéricos directos o enlaces. Esa validación reduce el riesgo, pero no reemplaza una política DLP ni el criterio del usuario: no escribir datos personales, credenciales, cuentas ni información de contacto.

### Agente y operación de cuentas por pagar

Las facturas canónicas de compra (`purchase`) ya pueden revisarse en una API operativa separada de cartera:

- `GET /api/v1/companies/{company_id}/payables/open-items` lista facturas de compra abiertas, paginadas, con saldo, vencimiento, antigüedad y moneda. Acepta `as_of`, `limit` y `offset`.
- `PATCH /api/v1/companies/{company_id}/payables/invoices/{invoice_id}/terms` corrige vencimiento o condiciones de pago de una factura de compra únicamente con `confirmed: true`.

La API no mezcla facturas de venta con compras, no suma ni compensa monedas distintas y no reutiliza los seguimientos de cobro, que pertenecen exclusivamente a cartera. Los roles de consulta pueden leer; `owner`, `admin` y `operator` de una empresa activa pueden corregir términos con trazabilidad de actor y fecha. El diagnóstico agregado está disponible en `POST /api/v1/companies/{company_id}/agents/payables/chat` y en la interfaz **Cuentas por pagar**. No programa pagos ni concilia extractos.

### Agente de flujo de caja

`POST /api/v1/companies/{company_id}/agents/cash-flow/chat` proyecta en modo determinista y de solo lectura los movimientos de facturas abiertas de venta y compra. Resta únicamente pagos ya registrados en la misma moneda de la factura y conserva COP, USD u otras monedas completamente separadas; no aplica tasas ni compensa divisas.

La proyección clasifica los saldos por fecha de vencimiento en vencidos, hoy, próximos 7 días, días 8–30, 31–60, 61–90 y después de 90 días. El resumen a 90 días incluye los movimientos vencidos todavía abiertos. Las facturas sin vencimiento se cuentan y generan una advertencia, pero no se ubican artificialmente en el calendario. La interfaz muestra entradas, salidas y movimiento neto por período y moneda.

El endpoint exige una membresía de consulta (`owner`, `admin`, `operator` o `viewer`) y no devuelve facturas, clientes, proveedores, documentos o pagos individuales. Tampoco registra cobros, programa pagos ni realiza transferencias. Cada consulta deja sólo metadatos agregados en `agent_executions`; el mensaje y el reporte no se guardan allí.

Esta proyección **no es un saldo bancario ni una medición de liquidez real**: no recibe cuentas ni extractos, y un vencimiento no garantiza que el cobro o pago ocurra en esa fecha. Antes de decidir pagos o necesidades de financiación se deben confirmar disponibilidad bancaria, certeza de recaudo y obligaciones fuera del modelo. Ver `backend/docs/adr/0020-agente-de-flujo-de-caja.md`.

### Agente y operación de conciliación bancaria

`POST /api/v1/companies/{company_id}/agents/bank-reconciliation/chat` explica únicamente métricas agregadas de conciliación: movimientos importados, sugerencias por confirmar, pendientes, ambigüedades, cobertura y entradas o salidas separadas por moneda. No devuelve descripciones, referencias, pagos ni cuentas individuales y no confirma decisiones desde el chat.

La vista **Conciliación operativa** ofrece el flujo autorizado:

- `GET|POST /api/v1/companies/{company_id}/bank-reconciliation/accounts` lista o crea alias de cuenta. La aplicación no solicita ni guarda el número completo; los alias rechazan correos y secuencias numéricas largas. Sólo `owner` y `admin` pueden crearlos.
- `POST /api/v1/companies/{company_id}/bank-reconciliation/accounts/{bank_account_id}/imports` importa extractos CSV UTF-8. Las columnas obligatorias son `fecha`/`date` y `valor`/`amount`; descripción, referencia y moneda son opcionales. Los valores positivos representan entradas y los negativos salidas. La moneda de cada fila debe coincidir con la del alias.
- `GET /api/v1/companies/{company_id}/bank-reconciliation/transactions` lista movimientos para revisión operativa. `PATCH /api/v1/companies/{company_id}/bank-reconciliation/transactions/{transaction_id}` permite confirmar, descartar, excluir o reabrir con `confirmed: true`. `owner`, `admin` y `operator` pueden importar y revisar; `viewer` sólo consulta.

El motor sugiere una coincidencia sólo cuando encuentra **un único** pago contable de igual importe absoluto y moneda, con dirección coherente —entrada para factura de venta, salida para compra— y fecha dentro de tres días antes o después. Una sugerencia nunca se considera conciliada hasta la confirmación humana; una coincidencia ambigua permanece pendiente y un pago no puede conciliarse dos veces. La huella de cada fila evita duplicados al reimportar el mismo extracto.

Esta primera versión admite CSV normalizado y coincidencias uno a uno. No calcula saldos bancarios, no conecta cuentas en línea, no divide ni agrupa movimientos, no crea pagos o comprobantes y no resuelve diferencias cambiarias. Las descripciones y referencias permanecen en la vista operativa y no llegan al agente. Ver `backend/docs/adr/0021-agente-de-conciliacion-bancaria.md`.

Para la revisión local con `contamind-demo.db`, puede cargarse `backend/examples/extracto-bancario-demo.csv`: contiene datos ficticios, una salida que coincide con el pago de compra de demostración y dos movimientos deliberadamente pendientes.

### Agente de tesorería y liquidez

`POST /api/v1/companies/{company_id}/agents/treasury/chat` combina la proyección de facturas abiertas a 30 días (incluidos vencidos) con la calidad de la conciliación bancaria. Presenta entradas, salidas y movimiento neto por moneda, facturas sin vencimiento y señales de conciliación que aún requieren revisión humana.

El agente es determinista y de solo lectura. No muestra documentos, cuentas, extractos, referencias, terceros o pagos individuales; tampoco registra, programa, prioriza ni autoriza pagos o transferencias. Cada consulta conserva sólo metadatos agregados de auditoría en `agent_executions`.

El diagnóstico **no calcula disponibilidad bancaria real ni responde si se puede pagar**: un extracto parcial no demuestra saldo actual y pueden existir obligaciones fuera del modelo. Antes de decidir pagos o financiación se debe contrastar el reporte con un saldo bancario verificado por moneda y completar las diferencias de conciliación. Ver `backend/docs/adr/0022-agente-de-tesoreria-y-liquidez.md`.

#### Capa LLM opcional y activación productiva

Esta capa aplica a los agentes que la integran explícitamente. Las versiones actuales de cuentas por pagar, flujo de caja y conciliación bancaria son deterministas y no llaman al LLM.

Por defecto `LLM_ENABLED=false`. Cuando se habilita y existe una clave configurada fuera del repositorio, la capa conversacional usa Responses API con `store: false`, identificador de seguridad HMAC, historial local reducido y una proyección agregada del reporte. No envía `company_id`, facturas, clientes, documentos, correos, credenciales ni permisos. La respuesta debe ajustarse a un esquema estructurado, citar códigos de hallazgo existentes y no puede ejecutar acciones. Las entradas y salidas se limitan y redactan por patrones conocidos; no son una garantía DLP.

`store: false` no equivale por sí solo a retención cero ni elimina todos los registros del proveedor: la documentación oficial de OpenAI explica la retención de estado y que, salvo controles aprobados, pueden existir registros de monitoreo de abuso. Revísese la [guía de controles de datos de OpenAI](https://developers.openai.com/api/docs/guides/your-data#default-usage-policies-by-endpoint) antes de activar el servicio.

Si el LLM está apagado, falta su configuración o falla/entrega una salida inválida, el agente responde con la explicación determinista aplicable y conserva el diagnóstico verificable. Si una narración habilitada falla, además audita la ejecución como degradada (`LLM_UNAVAILABLE`); las preguntas ya resueltas localmente no llaman al LLM y se auditan como exitosas. El chat no presenta la conversación como temporalmente no disponible ni inventa una interpretación.

Para activarlo en producción:

1. Complete la evaluación de privacidad, aviso al usuario, contrato y retención aplicables; confirme que el uso de agregados y mensajes cumple la política interna.
2. Guarde `OPENAI_API_KEY` exclusivamente en el gestor de secretos del ambiente; no la copie a `.env.example`, código, logs ni tickets.
3. Configure `AUTH_SECRET_KEY`, `OPENAI_MODEL`, límites de tiempo/salida y `FEATURE_FLAGS` con `LLM_ENABLED=true` en el ambiente de despliegue.
4. Ejecute pruebas funcionales y de seguridad con datos no productivos, incluyendo preguntas con PII, instrucciones de escritura, inyecciones y caídas del proveedor; habilite el cambio de forma gradual y supervise auditorías degradadas.

Ver `backend/docs/adr/0019-agente-de-cartera.md` para las decisiones y límites del diseño.

### Conexiones externas y sincronización

Las fuentes con proveedor se crean en estado `pending`. Un administrador configura credenciales mediante `PUT /api/v1/data-sources/{id}/credentials` y ejecuta `POST /api/v1/data-sources/{id}/connection-test`; solo una prueba exitosa habilita la fuente. Las credenciales se almacenan cifradas con Fernet y jamás aparecen en respuestas o auditorías.

`POST /api/v1/data-sources/{id}/sync/parties` crea un trabajo persistente y responde `202`; el worker lo procesa por páginas y conserva el cursor hasta completarlo. Se consulta con `GET /api/v1/data-sources/{id}/sync/jobs/{job_id}` o el listado de trabajos de la fuente. Hay un solo trabajo activo por fuente, reintentos con espera progresiva y una concesión recuperable si el worker se reinicia. Cada página queda además en `GET /api/v1/data-sources/{id}/connection-runs`, con actor, correlación, cursor, conteo y código de error, sin payloads sensibles. La primera referencia de API es Siigo, protegida por `SIIGO_INTEGRATION_ENABLED`; no hay proveedor prioritario y los conectores por archivo, agente local o base de datos usan el mismo ciclo. Ver `backend/docs/adr/0015-ciclo-de-vida-de-conexiones-externas.md` y `backend/docs/adr/0016-cola-persistente-de-sincronizacion.md`.
