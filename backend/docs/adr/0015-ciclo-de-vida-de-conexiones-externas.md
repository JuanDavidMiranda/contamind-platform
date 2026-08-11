# ADR-0015: Ciclo de vida de conexiones externas por fuente

- **Estado:** Aceptado
- **Fecha:** 2026-08-10
- **Fase:** Conectividad multi-proveedor
- **Relacionados:** ADR-0001, ADR-0007, ADR-0008, ADR-0009, ADR-0010

## Contexto

Una fuente de software contable no puede pasar a operar solo porque se haya creado su registro. Cada empresa debe aportar credenciales propias, probarlas contra el proveedor y conservar evidencia de los intentos y sincronizaciones. La credencial no puede vivir en claro en la base de datos, en logs ni en respuestas HTTP. Además, las APIs y conectores locales tienen mecanismos distintos, por lo que el ciclo no debe depender de una marca.

## Decisión

1. Las fuentes con `provider_id` nacen en estado `pending`, aunque el cliente solicite `active`. Solo una prueba de conexión exitosa las activa.
2. Cada fuente tiene a lo sumo una credencial vigente. Se guarda cifrada con **Fernet** y con alcance `tenant_id + company_id + data_source_id + provider_id`. La API recibe, rota o revoca secretos, pero nunca los devuelve ni los incorpora a la bitácora.
3. `PROVIDER_CREDENTIALS_MASTER_KEY` es una clave Fernet administrada por el despliegue y es obligatoria en `staging` y `production`. Desarrollo y pruebas derivan una clave temporal de `AUTH_SECRET_KEY`; no es una alternativa operativa para despliegues persistentes.
4. Las pruebas de conexión y las sincronizaciones crean una fila de auditoría con operación, estado, cursor antes/después, número procesado, código de error, actor y correlación. No se persisten payloads, tokens, mensajes de excepción ni credenciales.
5. La sincronización de terceros se ejecuta por una página y guarda un cursor opaco en la fuente. `ProviderHttpClient` aplica reintentos cortos por solicitud y la cola persistente reprograma los fallos transitorios; el cursor solo avanza al confirmar una página. Al agotar intentos o ante un error no recuperable, deja una corrida `failed` y desactiva operativamente la fuente hasta una nueva prueba de conexión.
6. Los puertos `ProviderConnectionPort` y `ProviderPartySyncPort` expresan capacidades. Un adaptador puede implementar una, ambas o capacidades futuras, sin obligar a proveedores por archivo, agente local o base de datos a aparentar una API REST.
7. Se incluye un adaptador inicial de solo lectura para Siigo (`/auth` y `/v1/customers`) porque su contrato público permite validar el ciclo completo. Está detrás de `SIIGO_INTEGRATION_ENABLED` y no es una prioridad de producto ni un proveedor predeterminado. Novasoft, SysCafé y cualquier proveedor adicional se incorporan con el mismo ciclo cuando exista su mecanismo autorizado.

## Rutas

- `PUT /api/v1/data-sources/{id}/credentials` — configura o rota credenciales (`owner`/`admin`).
- `DELETE /api/v1/data-sources/{id}/credentials` — revoca y deja la fuente fail-closed (`owner`/`admin`).
- `POST /api/v1/data-sources/{id}/connection-test` — prueba autenticación y actualiza salud (`owner`/`admin`).
- `POST /api/v1/data-sources/{id}/sync/parties` — encola una sincronización de terceros y responde `202` (`owner`/`admin`/`operator`).
- `GET /api/v1/data-sources/{id}/sync/jobs` y `GET /api/v1/data-sources/{id}/sync/jobs/{job_id}` — consulta los trabajos de la fuente (`owner`/`admin`/`operator`/`viewer`).
- `GET /api/v1/data-sources/{id}/connection-runs` — consulta auditoría sin secretos para miembros autorizados.

## Consecuencias

- Un operador puede sincronizar únicamente las fuentes de su empresa, pero no cambiar credenciales ni configuración.
- La rotación o revocación no requiere exponer valores anteriores y bloquea la operación hasta revalidar la conexión.
- Las sincronizaciones se encolan de forma persistente y el worker confirma una página por vez. La cola, los reintentos y la recuperación tras un reinicio se detallan en ADR-0016.
- La capacidad de Siigo cubierta en esta iteración es autenticación y terceros de lectura. Facturas, pagos y comprobantes requerirán completar sus mapeos y pruebas de contrato antes de habilitar escritura.
