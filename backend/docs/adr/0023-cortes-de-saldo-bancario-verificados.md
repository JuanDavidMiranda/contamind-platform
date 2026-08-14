# ADR-0023 — Cortes de saldo bancario verificados

**Fecha:** 2026-08-14
**Estado:** aceptado

## Contexto

La primera versión de tesorería reúne proyecciones de facturas abiertas y la
calidad de conciliación, pero no puede exponer un saldo bancario por falta de un
corte verificable. Un extracto parcial no es suficiente para inferirlo.

## Decisión

Se incorpora `bank_balance_snapshots`: un corte inmutable por cuenta bancaria,
fecha y moneda. La ruta operativa es:

`GET /api/v1/companies/{company_id}/bank-reconciliation/balance-snapshots`

`POST /api/v1/companies/{company_id}/bank-reconciliation/accounts/{bank_account_id}/balance-snapshots`

El POST exige `confirmed: true`, una cuenta activa y una fecha no futura. No se
pueden sobrescribir cortes del mismo día: la primera versión evita correcciones
silenciosas y exige revisar el dato antes de registrarlo.

Los roles de consulta pueden ver los últimos cortes disponibles. Sólo `owner`,
`admin` y `operator` de una empresa activa pueden registrarlos. El número de
cuenta nunca se solicita ni se guarda; se usa el alias bancario existente.

## Uso en tesorería

El agente consolida saldos únicamente cuando cada cuenta bancaria activa tiene
un corte y todos corresponden a la misma fecha. En ese caso devuelve saldos
agregados por moneda y la fecha de corte. Si falta una cuenta o las fechas no
coinciden, informa la cobertura y se niega a sumar importes de cortes
incomparables.

Un saldo verificado describe una posición en una fecha; no autoriza pagos ni
demuestra liquidez futura. Antes de cualquier decisión siguen siendo necesarias
la conciliación pendiente, las obligaciones fuera del modelo, la certeza de
recaudo y la aprobación humana correspondiente.
