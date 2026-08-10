# ADR-0013: Captura manual del núcleo contable

- **Estado:** Aceptado
- **Fecha:** 2026-08-10
- **Fase:** 2 (ingesta contable)
- **Relacionados:** ADR-0006, ADR-0009, ADR-0010, ADR-0012

## Contexto

Un cliente puede no contar con software contable o requerir registrar ajustes que aún no existen en su sistema externo. Después de persistir empresas, fuentes y terceros, se necesita capturar información contable útil sin introducir un modelo paralelo para formularios manuales.

## Decisión

Las fuentes `manual_entry` activas exponen captura de impuestos, ítems, facturas, pagos y comprobantes contables. El servidor deriva siempre empresa y fuente desde la ruta; el cuerpo de la solicitud nunca incluye un `company_id` modificable.

| Entidad | Ruta |
|---|---|
| Impuesto | `POST /api/v1/data-sources/{id}/manual/taxes` |
| Ítem | `POST /api/v1/data-sources/{id}/manual/items` |
| Factura | `POST /api/v1/data-sources/{id}/manual/invoices` |
| Pago | `POST /api/v1/data-sources/{id}/manual/payments` |
| Comprobante | `POST /api/v1/data-sources/{id}/manual/journal-entries` |

Todas las rutas requieren el encabezado `Idempotency-Key`, único por empresa, fuente y tipo de entidad. Repetir una solicitud con la misma llave retorna el registro original y evita duplicados. Las fuentes deben declarar explícitamente la capacidad necesaria (`taxes`, `items`, `invoices`, `payments` o `journals`).

## Reglas de integridad

- Impuestos, ítems, terceros y facturas referenciados deben pertenecer a la misma empresa.
- El subtotal de una factura se calcula desde sus líneas; el total se calcula como subtotal más impuestos menos retenciones.
- Un pago solo puede referenciar una factura de la misma empresa.
- Un comprobante requiere débitos y créditos iguales, mayores que cero; una línea no puede tener débito y crédito simultáneamente.
- Cada entidad guarda `company_id`, `data_source_id`, autor y fecha. Los secretos no forman parte de ningún registro.

## Consecuencias

- Clientes sin ERP pueden alimentar el mismo modelo canónico que utilizarán futuras importaciones y conectores.
- Los adaptadores de Siigo, Novasoft, SysCafé u otro proveedor pueden reutilizar tablas y validaciones, en vez de crear modelos específicos de marca.
- La siguiente ampliación podrá añadir importadores CSV/XLSX para estas entidades y el primer adaptador externo real sobre el mismo contrato.
