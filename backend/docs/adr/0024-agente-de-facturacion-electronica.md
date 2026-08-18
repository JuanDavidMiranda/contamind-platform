# ADR-0024 — Agente de facturación electrónica de solo lectura

**Fecha:** 2026-08-18
**Estado:** aceptado

## Contexto

ContaMind necesita detectar problemas de facturación electrónica sin atribuir a
la aplicación una conexión DIAN que todavía no existe. El modelo contable ya
registra facturas de venta, pero no diferenciaba la evidencia electrónica de
los estados contables generales ni conservaba una referencia CUFE/CUDE.

## Decisión

Se incorpora un agente determinista de solo lectura disponible en:

`POST /api/v1/companies/{company_id}/agents/electronic-invoicing/chat`

El modelo de factura incorpora tres campos opcionales y trazables por fuente:

- `electronic_status`: estado recibido de la fuente electrónica.
- `electronic_reference`: CUFE, CUDE u otro identificador externo equivalente.
- `electronic_status_at`: fecha y hora informada por la fuente para ese estado.

El agente analiza solo facturas de venta y presenta conteos agregados de
aceptadas, pendientes, rechazadas o con error, faltantes de estado o referencia,
consecutivos, adquirientes, diferencias de total y fechas futuras. Cada consulta
deja metadatos de auditoría en `agent_executions`, sin guardar el mensaje ni el
reporte.

## Límites

El agente no consulta la DIAN, no transmite XML, no firma documentos, no emite,
no reenvía, no corrige y no anula facturas. Los estados y referencias son
evidencia importada y nunca una afirmación de validación en tiempo real.

El chat no expone facturas, referencias, CUFE/CUDE ni datos de adquirientes
individuales. Las solicitudes de escritura o consulta individual se rechazan y
las preguntas con patrones sensibles deben reformularse.

## Consecuencias

La solución aporta priorización verificable antes de construir el adaptador
DIAN. La conexión real requerirá una fase posterior con habilitación, secretos,
certificado digital, firma XML, numeración autorizada, envíos asíncronos,
consulta de estados, manejo de rechazos y pruebas controladas.
