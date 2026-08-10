# ADR-0014: Importación tabular del núcleo contable

- **Estado:** Aceptado
- **Fecha:** 2026-08-10
- **Fase:** 2 (ingesta contable)
- **Relacionados:** ADR-0009, ADR-0013

## Contexto

La captura manual resuelve el caso sin software contable, pero muchos clientes tienen exportaciones CSV o XLSX de un ERP, una hoja de cálculo o una base local. Importar únicamente terceros no permite reconstruir su operación contable ni reutilizar los datos para automatización.

## Decisión

`ImportProfile` ahora admite perfiles para `taxes`, `items`, `invoices`, `payments` y `journal_entries`, además de `parties`. Las rutas genéricas usan:

```text
POST /api/v1/data-sources/{id}/imports/accounting
```

El perfil determina entidad y formato. La fuente debe ser de archivos, usar el conector del formato (`csv_import` o `xlsx_import`) y declarar la capacidad de la entidad. Se mantienen los límites de tamaño y la lectura XLSX en modo seguro y de solo valores.

## Mapeos y dependencias

Los perfiles relacionan cada campo canónico con una columna. Además de UUIDs, el importador resuelve referencias naturales por código o número:

| Entidad | Referencias admitidas |
|---|---|
| Ítems | `tax_codes` |
| Facturas | `recipient_document_number`, `issuer_document_number`, `item_code`, `tax_codes` |
| Pagos | `invoice_number` |
| Comprobantes | `party_document_number` |

Facturas se agrupan por `number` y comprobantes por `source_reference`, de forma que varias filas constituyen una sola factura o asiento. El orden recomendado es: impuestos, ítems, terceros, facturas, pagos y comprobantes.

## Integridad y auditoría

- Cada fila usa el mismo servicio canónico de captura manual; aplica las validaciones de empresa, referencias, totales y partida doble.
- Una fila inválida genera un rechazo con número de fila sin descartar las filas válidas del mismo lote. Si una factura o comprobante agrupado es inválido, se rechazan sus filas completas.
- La llave de idempotencia se deriva del hash del contenido, entidad y fila o grupo. Repetir exactamente el mismo archivo no duplica impuestos, ítems, facturas, pagos ni comprobantes.
- Cada carga crea un `ImportBatch` con hash, filas aceptadas, rechazos y usuario autor; el contenido del archivo no se persiste.

## Consecuencias

- Un cliente puede migrar datos desde prácticamente cualquier software capaz de exportar tabulares, aun sin API.
- Los futuros adaptadores de Siigo, Novasoft, SysCafé u otro sistema convergen en las mismas entidades y validaciones.
- Cargas incrementales modificadas deben emplear una nueva exportación; la actualización semántica de registros existentes se resolverá mediante sincronización/adaptadores y no sobrescribiendo silenciosamente una importación histórica.
