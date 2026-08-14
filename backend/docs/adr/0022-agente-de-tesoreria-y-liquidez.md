# ADR-0022 — Agente de tesorería y liquidez

**Fecha:** 2026-08-14
**Estado:** aceptado

## Contexto

ContaMind ya distingue cartera, cuentas por pagar, flujo de caja proyectado y
conciliación bancaria. Es útil revisar esas señales conjuntamente para la
operación de tesorería, pero los extractos importados pueden cubrir períodos
parciales y el sistema no guarda un saldo inicial o final verificado. Por eso
no es posible deducir la disponibilidad bancaria real ni decidir pagos a partir
de los datos actuales.

## Decisión

Se implementa el agente determinista y de solo lectura `treasury`, expuesto en
`POST /api/v1/companies/{company_id}/agents/treasury/chat`.

El reporte usa los datos existentes, sin crear una nueva fuente de verdad:

- proyección de facturas abiertas de venta y compra con vencimiento dentro de
  30 días, incluidos vencidos, separada por moneda;
- facturas abiertas sin vencimiento y cuentas por cobrar vencidas;
- cuentas, movimientos y cobertura de conciliación, incluidas sugerencias,
  pendientes, movimientos sin coincidencia y ambiguos.

Los montos de diferentes monedas nunca se convierten ni compensan. El reporte
siempre declara que el saldo bancario verificado y obligaciones fuera del modelo
son necesarios para conocer disponibilidad real o autorizar pagos.

## Límites y controles

- El chat no devuelve cuentas, extractos, referencias, facturas, pagos,
  clientes o proveedores individuales.
- El chat no registra, programa, prioriza ni autoriza pagos, cobros o
  transferencias. Las acciones siguen en las vistas operativas con sus roles y
  confirmaciones correspondientes.
- Las sugerencias de conciliación no cuentan como conciliadas. Una decisión
  humana sigue siendo obligatoria.
- Cada consulta registra únicamente metadatos de ejecución y códigos de
  hallazgo en `agent_executions`; no persiste la pregunta, respuesta ni reporte.
- El agente no usa LLM ni llama a servicios externos.

## Consecuencias

El diagnóstico permite priorizar qué evidencia debe revisarse antes de una
decisión de tesorería, pero no responde «¿puedo pagar?» ni presenta una cifra de
liquidez disponible. Una futura capacidad de disponibilidad real requerirá un
modelo explícito de saldos bancarios verificados, fecha de corte y controles de
operación separados.
