# ADR-0020: Proyección determinista de flujo de caja por empresa

- **Estado:** Aceptado
- **Fecha:** 2026-08-13
- **Fase:** Agentes de negocio
- **Supuestos:** Las fuentes registran correctamente facturas, pagos, monedas y vencimientos. El reporte es una proyección de movimientos abiertos y no sustituye tesorería, conciliación bancaria ni asesoría financiera.

## Contexto

ContaMind ya separa la cartera de ventas y las obligaciones de compra, pero revisar
ambos diagnósticos por separado no muestra cuándo coinciden sus vencimientos. Una
primera vista conjunta debe ser verificable con el modelo canónico disponible y no
debe afirmar que existe efectivo que el sistema todavía no observa.

Las facturas pueden carecer de vencimiento, los pagos pueden estar registrados en
otra moneda y una cuenta vencida no equivale a un recaudo confirmado. Además, el
chat empresarial conserva una frontera de privacidad: responde con agregados y no
es un canal para consultar o modificar ítems individuales.

## Decisión

1. `CashFlowService` consulta únicamente facturas abiertas `sale` y `purchase` de
   la empresa. El saldo es el total menos los pagos asociados que tengan la misma
   moneda; los pagos en otra moneda no se compensan automáticamente.
2. Cada saldo de venta es una entrada proyectada y cada saldo de compra es una
   salida proyectada. Los importes se agrupan y presentan por código de moneda, sin
   conversión ni suma entre divisas.
3. La fecha de análisis clasifica los vencimientos en `overdue`, `due_today`,
   `next_7_days`, `days_8_30`, `days_31_60`, `days_61_90` y `beyond_90`.
4. El resumen de 90 días incluye los ítems vencidos todavía abiertos, los que vencen
   hoy y los que vencen hasta el día 90. Esto expresa exposición pendiente dentro
   del horizonte, no fecha garantizada de cobro o pago.
5. Los ítems sin fecha de vencimiento se cuentan como abiertos, pero quedan fuera de
   los períodos y de los importes proyectados. El hallazgo
   `CASH_FLOW_ITEMS_MISSING_DUE_DATE` exige completar el dato antes de usar el
   calendario para priorizar.
6. Un movimiento neto negativo en una moneda genera
   `NEGATIVE_NET_MOVEMENT_WITHIN_90_DAYS`. Su severidad es advertencia, no alerta de
   insolvencia, porque el sistema no conoce saldos bancarios ni otras fuentes de
   liquidez.
7. `POST /api/v1/companies/{company_id}/agents/cash-flow/chat` exige autenticación y
   uno de los roles de consulta de la empresa. El workflow queda fijado durante la
   conversación y sólo expone métricas, períodos, hallazgos y recomendaciones
   agregadas.
8. El agente rechaza preguntas con patrones sensibles, consultas por facturas,
   terceros o pagos individuales y solicitudes para registrar, programar o ejecutar
   movimientos. También declara fuera de alcance el efectivo disponible, el saldo
   bancario y la liquidez real.
9. La primera versión es completamente determinista y no invoca un LLM. Las sesiones
   temporales eliminan el mensaje y las entidades extraídas después de procesar el
   workflow.
10. Cada ejecución conserva en `agent_executions` sólo empresa, actor, versión,
    correlación, estado, cantidad y códigos de hallazgo. No persiste el mensaje, el
    reporte, importes ni datos personales.

## Consecuencias

- Finanzas puede comparar vencimientos de cobro y pago en una sola línea temporal
  sin mezclar monedas ni exponer detalle individual en el chat.
- La calidad de la proyección depende explícitamente de pagos y vencimientos
  actualizados; los faltantes permanecen visibles en vez de estimarse.
- La vista no reemplaza un módulo de tesorería. Incorporar saldos bancarios,
  recurrencias, presupuestos, escenarios o probabilidades de recaudo requerirá un
  contrato de datos y controles adicionales.
- No se requiere migración: se reutilizan las entidades canónicas y la auditoría de
  agentes existentes.

## Verificación

- La prueba de API crea entradas y salidas en COP y USD, descuenta un pago en moneda
  coincidente, verifica el neto y los períodos, y confirma advertencias por fechas
  faltantes y movimiento negativo.
- Los límites de todos los períodos se cubren con casos parametrizados.
- La cobertura valida el rechazo de consultas individuales y de saldo bancario, así
  como la creación de auditorías sin contenido conversacional.
- El frontend comprueba el endpoint, el selector del agente, el aviso de alcance y la
  presentación del neto, entradas y salidas por período.
