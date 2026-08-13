# ADR-0021: Conciliación bancaria determinista con revisión humana

- **Estado:** Aceptado
- **Fecha:** 2026-08-13
- **Fase:** Agentes de negocio
- **Supuestos:** Los pagos contables están registrados con fecha, importe, moneda y factura asociada. El extracto importado representa movimientos, no necesariamente el saldo completo de una cuenta.

## Contexto

Los agentes de cartera, cuentas por pagar y flujo de caja trabajan con hechos del
modelo contable, pero no pueden comprobar por sí solos si un cobro o pago aparece en
el banco. Para cerrar esa brecha se necesita un registro bancario separado, una
regla de coincidencia reproducible y una bandeja donde una persona autorizada acepte
o rechace la sugerencia.

Una similitud de fecha e importe no demuestra identidad. Puede haber pagos repetidos,
extractos parciales, cargos bancarios, movimientos internos o datos faltantes. Por
eso el agente no debe presentar una sugerencia como conciliación confirmada ni
convertirse en un ejecutor de pagos o asientos.

## Decisión

1. `bank_accounts` conserva sólo un alias, banco opcional, moneda, empresa, estado y
   auditoría. La API no solicita ni modela el número completo de cuenta. Los alias
   rechazan correos y secuencias numéricas largas que puedan contenerlo.
2. `bank_statement_imports` audita actor, cuenta, filas aceptadas, rechazadas y
   duplicadas. La primera versión recibe CSV UTF-8 con `date`/`fecha` y
   `amount`/`valor`; descripción, referencia y moneda son opcionales.
3. `bank_transactions` conserva un importe firmado: positivo para entrada y negativo
   para salida. También guarda fecha, moneda, descripción operativa, referencia,
   huella idempotente, estado y actores de revisión.
4. La huella usa cuenta, fecha, importe, moneda, referencia y descripción. Cuando no
   existe referencia también incorpora el número de fila para permitir movimientos
   iguales legítimos dentro del mismo archivo y detectar la reimportación del archivo.
5. Una coincidencia se sugiere sólo si existe exactamente un `PaymentRecord` de la
   empresa con igual moneda e importe absoluto, fecha dentro de ±3 días y factura de
   dirección coherente: `sale` para entradas, `purchase` para salidas.
6. Cero candidatos produce `pending`; más de uno produce `pending` ambiguo; uno
   produce `suggested`. Ninguno se transforma automáticamente en `reconciled`.
7. La operación exige `confirmed: true`. `confirm` fija el pago y bloquea su uso en
   otra conciliación; `dismiss` rechaza una sugerencia; `exclude` saca un movimiento
   no conciliado de la cobertura; `reopen` limpia la decisión y recalcula candidatos.
8. `owner`, `admin` y `operator` pueden importar y revisar. Sólo `owner` y `admin`
   crean alias de cuenta. `viewer` puede consultar la bandeja y el diagnóstico.
9. El chat `POST /api/v1/companies/{company_id}/agents/bank-reconciliation/chat`
   recibe sólo métricas, hallazgos y sumas agregadas por moneda. Rechaza datos
   sensibles, consultas individuales y solicitudes de escritura.
10. La tasa de conciliación es `reconciled / (imported - excluded)`. No constituye
    certificación bancaria ni prueba de integridad del período importado.
11. Cada ejecución del agente registra en `agent_executions` sólo actor, empresa,
    versión, correlación, estado y códigos de hallazgo. El mensaje, importes,
    referencias, movimientos y reporte no se persisten en esa auditoría.

## Consecuencias

- ContaMind distingue explícitamente movimiento importado, sugerencia y decisión
  humana confirmada.
- Las reglas uno a uno son explicables y fáciles de auditar, pero dejan pendientes
  los pagos agrupados, parciales, neteados o con diferencias de importe.
- La operación puede detectar faltantes entre banco y contabilidad sin crear pagos,
  asientos, transferencias ni ajustes automáticos.
- Incorporar OFX, XLSX, conexión bancaria, saldos inicial/final, división/agrupación o
  tolerancias configurables requerirá una extensión específica del contrato.

## Verificación

- La prueba integrada cubre entradas y salidas exactas, ambigüedad, ausencia de
  coincidencia, filas inválidas, reimportación idempotente y separación por empresa.
- También valida permisos de consulta, configuración y operación, confirmación
  humana, auditoría del agente y rechazo de consultas de saldo real.
- El frontend comprueba el selector, endpoint, bandeja operativa, confirmaciones y
  avisos de privacidad sin persistencia en el navegador.
