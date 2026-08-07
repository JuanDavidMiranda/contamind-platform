# ADR-0003: Evaluación Siigo — candidato técnico inicial

- **Estado:** Propuesto (pendiente de revisión)
- **Fecha:** 2026-08-06
- **Fase:** 1 (spike de viabilidad)
- **Categoría:** Evaluación de proveedor financiero
- **Relacionados:** ADR-0001, ADR-0006, ADR-0007, `spike-fase1.md`

## Contexto

Evaluar Siigo Nube como sistema financiero integrable: autenticación, cobertura, paginación, límites, idempotencia, webhooks y operaciones de escritura. Siigo es candidato técnico inicial, **no** una selección definitiva hasta completar la matriz y confirmar credenciales.

## Investigación (evidencia del 2026-08-06, documentación oficial Siigo)

### Autenticación y credenciales
- Esquema **OAuth2** (grant `password`) con credenciales `username` (usuario API) + `access_key` → token de acceso **JWT**.
- Credenciales emitidas por Siigo Nube (menú Alianzas → "Mi credencial API" / "Credenciales de integración a plataformas digitales (Siigo API)"), solo usuarios administrador, máx. 5 aplicaciones registradas, con `Restablecer credenciales` para regenerar el access key.
- **Partner-Id** obligatorio en **todos** los requests: header con el nombre del software/aplicación integrado (3-100 caracteres alfanuméricos, sin espacios). Siigo monitorea y **bloquea** usuarios API con datos no reales. Mismo valor para todas las empresas integradas.
- El endpoint exacto de token (históricamente `connect/token`; la doc vigente de México usa `/auth`) se confirmará al implementar.

### Recursos expuestos (Colombia, base `https://api.siigo.com/v1`)
- `/products` (productos/servicios: crear, consultar, actualizar, borrar)
- `/customers` (terceros: crear, consultar, actualizar)
- `/invoices` (facturas de venta: crear, editar, enviar por mail, anular, borrar, consultar, PDF)
- `/purchases` (facturas de compra)
- `/credit-notes` (notas crédito, con PDF)
- `/vouchers` (recibos de caja)
- `/payment-receipts` (recibos de pago/egreso)
- `/journals` (comprobantes contables)
- `/quotations` (cotizaciones)
- `/purchase-support-documents` (documento soporte)
- Reportes financieros y contables (balance de prueba, balance por tercero, CxP)
- Datos de referencia: tipos de documento, impuestos, retenciones, centros de costo, monedas, bodegas, vendedores, métodos de pago, entre otros.

### Paginación
- Listados con parámetros `page` / `page_size`; respuesta con `pagination` (`page`, `page_size`, `total_results`) y `__links` (`previous`, `self`, `next`).
- Filtros por fechas (created/updated/date), identificación, nombre, documento, etc.

### Límites y manejo de errores
- **Límite de solicitudes:** 100 peticiones/min por empresa en **producción**; **10 peticiones/min** en la **empresa de pruebas**.
- Error `requests_limit` / HTTP **429** (Too Many Requests): retirada exponencial recomendada.
- HTTP **504** (Timed Out) ante sobrecarga; recomiendan timeouts de **120 segundos o más** para creaciones de comprobantes.
- HTTP **401** ante credenciales inválidas/vencidas.

### Idempotencia — documentada por Siigo
- Header **`Idempotency-Key`** para peticiones **POST** de comprobantes: facturas de venta, notas crédito, comprobantes contables y recibos de caja.
- Características: opcional, alfanumérico, sin caracteres especiales ni espacios, **máx. 30 caracteres**.
- Reintento seguro: si se reenvía la misma key y el comprobante ya existe, devuelve el comprobante previamente creado (sin duplicar).
- **No** enviar en GET/PUT/DELETE.

### Webhooks — documentados
- `POST /v1/webhooks` para suscribirse por evento (topic tipo `public.siigoapi.products.create`).
- Respuesta con `id`, `application_id`, `url`, `topic`, `company_key`, `active`, `created_at`.

### Operaciones de escritura
- Creación de facturas de venta/compra, notas, recibos, comprobantes, productos y terceros; envío electrónico a la DIAN y por mail desde la creación (o manual desde Siigo Nube).

## Decisión

1. Registrar a Siigo como **candidato técnico inicial** para el primer adaptador financiero (evidencia: API completa, ambiente de pruebas real, idempotencia nativa, límites y webhooks documentados).
2. **No** es selección definitiva: se confirma al completar la matriz comparativa, la matriz de riesgo y el acceso a **credenciales de prueba** (empresa de pruebas: 10 req/min).
3. Los **nombres previstos** de variables de credenciales se documentan aquí (el mecanismo de almacenamiento definitivo pertenece a la fase de seguridad e integraciones; **no** se añaden al `.env.example` en esta fase):
   - `SIIGO_USERNAME`
   - `SIIGO_ACCESS_KEY`
   - `SIIGO_PARTNER_ID`
   - `SIIGO_BASE_URL` (default `https://api.siigo.com/v1`)
4. El adaptador Siigo debe cumplir la suite de cumplimiento común (ver `spike-fase1.md`): autenticar, consultar/listar terceros, mapeo al canónico, paginación, rate limits, credencial inválida, idempotencia (usar `Idempotency-Key`), auditoría y aislamiento por empresa.

## Consecuencias

Positivas:

- Cobertura contable amplia para Colombia (ventas, compras, notas, recibos, comprobantes contables, documento soporte).
- Idempotencia nativa en los comprobantes clave → riesgo de duplicados controlado por el proveedor.
- Límites claros y ambiente de pruebas con límite reducido (10 req/min) útil para desarrollo.
- Webhooks reales para sincronización de eventos.

Negativas / trade-offs:

- Autenticación OAuth2 con credenciales de larga duración (username/access_key) + Partner-Id: requiere gestión de secretos por empresa (ADR-0007).
- Límites por empresa (no por aplicación): la suma de integraciones comparte el tope de 100 req/min.
- La selección final depende de la disponibilidad de credenciales de prueba y de la matriz de riesgo (dependencia comercial: credenciales gestionadas por Siigo con proceso de registro).

## Madurez / Evidencia

- **M1 (validado documentalmente):** autenticación, endpoints, paginación, límites (10/100 rpm), timeout 120s, idempotencia (`Idempotency-Key`), webhooks y bloqueo de usuarios confirmados en la documentación oficial.
- **M0:** comportamiento real (M2 manual / M3 con credenciales) pendiente de acceso a la empresa de pruebas.

## Referencias

- Siigo API Colombia — docs: developers.siigo.com/docs/siigoapi (Introducción, Manejo de errores, Códigos de estado HTTP, Partner Id, Idempotencia, Bloqueo de usuarios, Facturación electrónica)
- Siigo API México — Autenticación (patrón de token vigente)
- Portal de clientes Siigo — Generar credenciales API (proceso y Partner-Id)
