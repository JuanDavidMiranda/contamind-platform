# ADR-0025 — Importación auditable de evidencia de facturación electrónica

**Fecha:** 2026-08-18
**Estado:** aceptado

## Contexto

El agente de facturación electrónica detecta estados faltantes, pendientes o
rechazados, pero requería un mecanismo operativo para incorporar evidencia de
una fuente autorizada. Ese mecanismo debía permitir corregir el diagnóstico sin
mezclar detalles individuales con el chat ni presentar estados importados como
una consulta en línea a la DIAN.

## Decisión

Se incorpora una carga especializada para evidencia de facturas de venta:

- `POST /companies/{company_id}/electronic-invoicing/imports` recibe CSV UTF-8
  o XLSX. Requiere número de factura y estado electrónico; admite referencia
  electrónica y fecha de respuesta ISO 8601.
- Solo `owner`, `admin` y `operator` de una empresa activa pueden cargar. La
  factura se busca únicamente dentro de la misma empresa y entre facturas de
  venta existentes.
- El importador normaliza los estados permitidos, evita aplicar dos veces una
  evidencia idéntica y marca las filas repetidas en el mismo archivo como
  duplicadas. Una fila inválida no detiene el resto de la carga.
- Cada carga y cada resultado de fila se conserva en tablas de auditoría. Los
  resultados incluyen número de fila, desenlace y motivo; no se almacena el
  CUFE/CUDE, consecutivo ni otro valor original del archivo dentro de la fila de
  auditoría.
- Las excepciones individuales y la auditoría se consultan por rutas protegidas
  de solo lectura. La respuesta no incluye la referencia electrónica ni el
  adquiriente; expone el consecutivo disponible, el estado y códigos de revisión.

## Límites

La carga no crea facturas, no emite, firma, transmite, corrige ni anula
documentos. Tampoco consulta o valida documentos ante la DIAN. Un estado
importado continúa siendo evidencia proporcionada por una fuente autorizada,
no una confirmación en línea de la autoridad fiscal.

## Consecuencias

El diagnóstico puede pasar de agregado a una revisión operativa trazable sin
ampliar el alcance del chat ni revelar referencias sensibles. La integración
real con DIAN seguirá siendo una fase distinta: requiere habilitación,
credenciales, certificado, firma XML, transporte seguro, asincronía y pruebas
con el ambiente autorizado.
