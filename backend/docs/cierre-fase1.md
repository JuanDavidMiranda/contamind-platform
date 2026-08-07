# Cierre de Fase 1 — Spike de viabilidad de integraciones

Fecha: 2026-08-06
Estado: Fase 1 cerrada (solo documentación, sin código productivo). Árbol en verde (`ruff check . --select E9,F` limpio; `pytest` 61 tests, con PostgreSQL incluido).

La Fase 0 estabilizó el codebase (ver `docs/checkpoint1-fase0.md` y `docs/cierre-fase0.md`). Esta fase reduce la incertidumbre de integración con los cuatro proveedores evaluados (DIAN, Siigo, Alegra, World Office) y deja la línea base documental para la implementación de la Fase 2.

## 1. Alcance aprobado

- Investigación y documentación únicamente: **sin código productivo** (`app/providers/`, adaptadores, factory, migraciones, persistencia ni dependencias runtime nuevas).
- Sin credenciales de prueba: contratos mock + criterios de tests live documentados (sin secretos ni payloads reales en el repo).
- Sin variables de credenciales en `.env.example`; nombres previstos documentados en los ADR.

## 2. Entregables

- ADR-0001 a ADR-0007 (`docs/adr/`):
  - `0001-arquitectura-proveedores-neutral.md` — `FinancialProviderPort` vs `FiscalProviderPort` (DIAN), capas, registry/factory neutral.
  - `0002-dian-vertical-institucional.md` — GetAcquirer como primer vertical real (piloto SOAP controlado); facturación electrónica como fase propia; exógena sin API pública.
  - `0003-siigo-evaluacion.md` — candidato técnico inicial (idempotencia `Idempotency-Key`, límites 10/100 rpm, webhooks, Partner-Id).
  - `0004-alegra-evaluacion.md` — alternativa más cercana (Basic auth, 150 rpm, sin idempotencia nativa, sin sandbox formal).
  - `0005-worldoffice-evaluacion.md` — integración por modalidad (Cloud API / on-premise / archivos / agente local).
  - `0006-modelo-contable-canonico.md` — modelo agnóstico versionado (Tenant, Company, Party, Item, Invoice, Payment, JournalEntry, Tax, Currency).
  - `0007-estrategia-autenticacion-transversal.md` — capa común de SecretStore + mecanismos por proveedor (OAuth2, Basic, JWT 12 h, WS-Security/certificado).
- `docs/spike-fase1.md` — informe consolidado: matrices de capacidades, madurez M0-M5 y riesgo por proveedor; evidencia documental; payloads sanitizados; puertos conceptuales; suite de cumplimiento (10 tests); criterios de tests live; plan del vertical DIAN; riesgos/bloqueadores/feature flags.

## 3. Decisiones principales

- Arquitectura **ports-and-adapters con modelo canónico agnóstico** (ADR-0001, ADR-0006): el dominio queda aislado de los proveedores y es multiempresa desde el diseño.
- **Siigo = candidato técnico inicial** para el primer adaptador financiero, **no** selección definitiva (condicionado a base de clientes y credenciales).
- **DIAN = GetAcquirer** como primer vertical real; la facturación electrónica merece una fase propia.
- **World Office** no es un adaptador único: se clasifica por modalidad.
- Sin credenciales reales: la validación se hace con `httpx.MockTransport`; los tests live quedan como criterios habilitables (opt-in, deshabilitados por defecto).

## 4. Verificación y trazabilidad

- Commit de cierre: **`9b7ca39`** — `docs(adr): complete Phase 1 feasibility spike for DIAN and financial providers` (9 archivos, 845 inserciones).
- `git status` limpio; `ruff check . --select E9,F` → "All checks passed!"; `pytest` con `RUN_POSTGRES_TESTS=1` + `POSTGRES_TEST_DATABASE_URL` (127.0.0.1:5433) → **61 passed**.
- ADR-0001 a 0007 quedan referenciados desde `docs/spike-fase1.md` y cada ADR referencia el informe (relación bidireccional).

## 5. Puerta de la siguiente fase

**Fase 2 — Infraestructura de proveedores** (implementación, ya no investigación): `FinancialProviderPort` y `FiscalProviderPort`, modelo canónico como código, contratos Pydantic, `ProviderContext`, `ProviderFactory`, infraestructura HTTP común (autenticación, reintentos, rate limiting, errores), suite de cumplimiento automatizada, mocks reutilizables por proveedor y feature flags por proveedor. **No** se implementa ningún adaptador concreto (Siigo/Alegra/World Office) hasta validar esta base.

Secuencia: Fase 0 ✅ cerrada → Fase 1 ✅ cerrada → Fase 2 infraestructura de proveedores → Fase 3 primer adaptador financiero → Fase 4 primer vertical DIAN.

## Referencias

- `docs/adr/0001..0007-*.md` y `docs/spike-fase1.md`
- `docs/cierre-fase0.md` (precedentes de calidad, error catalog y patrones reutilizables)
