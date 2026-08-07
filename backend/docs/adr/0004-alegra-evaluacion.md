# ADR-0004: Evaluación Alegra — sistema financiero alternativo

- **Estado:** Propuesto (pendiente de revisión)
- **Fecha:** 2026-08-06
- **Fase:** 1 (spike de viabilidad)
- **Categoría:** Evaluación de proveedor financiero
- **Relacionados:** ADR-0001, ADR-0003, ADR-0006, ADR-0007, `spike-fase1.md`

## Contexto

Evaluar Alegra como sistema financiero integrable para Colombia: autenticación, cobertura, paginación, límites, webhooks y operaciones de escritura. Es un **competidor directo de Siigo** y se evalúa para la matriz comparativa y la selección del primer adaptador financiero.

## Investigación (evidencia del 2026-08-06, documentación oficial Alegra)

### Autenticación y credenciales
- Esquema **Basic Auth**: header `Authorization: Basic base64(email:token)`, con el token generado en Alegra (Configuración → "API - Integraciones con otros sistemas").
- El token queda ligado a la cuenta/empresa; se puede regenerar (rompe integraciones activas).
- Respuesta **401** ante token ausente o inválido.

### Recursos expuestos (base `https://api.alegra.com/api/v1`)
- **Contactos:** `/contacts` (crear, consultar, borrar; tipo cliente/proveedor).
- **Ítems/productos:** `/items` (crear, actualizar, consultar; precios, inventario).
- **Facturas de venta:** `/invoices` (crear, consultar, actualizar, anular, borrar; con impuestos, descuentos, items).
- **Cotizaciones:** `/quotations` (crear, consultar, anular).
- **Number templates:** `/number-templates` (numeración por tipo de documento).
- **Pagos de facturas:** `/payments` (asociar pago/abono a facturas).
- **Términos de pago:** `/payment-terms`.
- **Notas crédito:** `/credit-notes`.
- **Remisiones:** `/remissions`.
- **Proveedores:** facturas de proveedor `/purchase-invoices`, órdenes de compra `/purchase-orders`, notas débito `/debit-notes`.
- **Bancos:** cuentas bancarias `/bank-accounts`, movimientos.
- **Impuestos:** `/taxes` (configuración de impuestos y retenciones).
- **Comprobantes contables:** `/journals` (crear y consultar asientos).
- Campos personalizados (custom fields) documentados en la API.

### Paginación
- Parámetros `start` (índice inicial, default 0) y `limit` (**máximo 30**, default 30).
- Respuestas de listado incluyen el total; se itera con `start += limit`.
- No hay parámetro `page` (a diferencia de Siigo).

### Límites y manejo de errores
- **Límite de solicitudes: 150 peticiones/minuto** por cuenta. Headers `X-Rate-Limit-Limit` / `X-Rate-Limit-Remaining` / `X-Rate-Limit-Reset` (o similar) disponibles en la respuesta.
- Respuesta **429** ante exceso de límite (retirada recomendada).
- Códigos HTTP estándar: 400 (request inválido), 401 (autenticación), 404 (recurso inexistente), 422 (validación de negocio) y 500 (error del servidor).
- Timeout: sin recomendación oficial concreta localizada; se usará el default del cliente (30 s) y retirada ante 429/5xx.

### Webhooks — documentados
- Suscripción por evento con **headers configurables** en cada webhook (cabeceras personalizadas con secretos).
- 12 eventos documentados (terceros, ventas, pagos, etc.).
- Registro vía endpoint propio de webhooks.

### Operaciones de escritura
- Creación/actualización/anulación de facturas de venta, notas, recibos, comprobantes contables, ítems, contactos y pagos.
- Sin idempotencia nativa documentada equivalente al `Idempotency-Key` de Siigo → la idempotencia de escrituras debe resolverse en el adaptador (detectar duplicados por número de documento y validación de negocio).

### Ambiente de pruebas
- **No** hay un sandbox formal documentado en las fuentes revisadas; la validación se hace contra una cuenta/empresa de pruebas real (mismo límite de 150 rpm).

## Decisión

1. Registrar a Alegra como **candidato alternativo** al primer adaptador financiero, con evidencia documental completa para la matriz comparativa y la matriz de riesgo.
2. **No** es selección definitiva: se confirma al completar la matriz, el riesgo y el acceso a credenciales de prueba.
3. **Nombres previstos** de variables de credenciales (solo se documentan aquí; **no** se añaden al `.env.example` en esta fase):
   - `ALEGRA_EMAIL`
   - `ALEGRA_TOKEN`
   - `ALEGRA_BASE_URL` (default `https://api.alegra.com/api/v1`)
4. El adaptador Alegra debe cumplir la suite de cumplimiento común (ver `spike-fase1.md`): autenticar (Basic), consultar/listar terceros, mapeo al canónico, paginación (`start`/`limit`, máx 30), rate limits (150 rpm + headers), credencial inválida (401), idempotencia (estrategia propia en el adaptador), auditoría y aislamiento por empresa.
5. Dado que Alegra **no ofrece idempotencia nativa**, el ADR-0006/0007 y la suite de cumplimiento deben reflejar la estrategia de duplicados del lado del adaptador (números de documento únicos por empresa + reintentos controlados).

## Consecuencias

Positivas:

- Cobertura contable completa y comparable con Siigo (ventas, compras, notas, comprobantes contables `/journals`, bancos, impuestos/retenciones).
- Autenticación simple (Basic) y límites generosos (150 rpm) documentados.
- Webhooks con headers configurables (permite secretos por webhook).

Negativas / trade-offs:

- **Sin idempotencia nativa** en escrituras → el adaptador debe implementar detección de duplicados.
- **Sin sandbox formal** → el desarrollo/validación requiere cuenta de pruebas real con datos.
- Paginación limitada a 30 por página (más requests por listado grande que Siigo).

## Madurez / Evidencia

- **M1 (validado documentalmente):** autenticación Basic, endpoints, paginación (start/limit máx 30), límite 150 rpm + headers `X-Rate-Limit-*`, webhooks con headers configurables y ausencia de idempotencia nativa confirmados en la documentación oficial.
- **M0:** comportamiento real (M2 manual / M3 con credenciales) pendiente de cuenta de pruebas.

## Referencias

- Alegra API — docs: developer.alegra.com (Guías, Referencia de la API, Límite de request, Webhooks)
- Alegra — Configuración "API - Integraciones con otros sistemas" (generación de token)
