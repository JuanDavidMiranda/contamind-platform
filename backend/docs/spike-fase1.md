# Spike de viabilidad — DIAN, Siigo, Alegra, World Office (Fase 1)

Fecha: 2026-08-06
Estado: **Spike de investigación + ADRs (sin código productivo).** Pendiente de revisión y aprobación de la puerta de Fase 2.
Alcance: solo documentación. No se crearon `app/providers/`, adaptadores, factory, migraciones, persistencia ni dependencias runtime nuevas (regla de oro de Fase 1).

## 1. Objetivo

Reducir la incertidumbre de integración con los cuatro proveedores evaluados (DIAN, Siigo, Alegra, World Office) y producir el material necesario para decantar, en Fase 2, los puertos, el modelo canónico y el primer adaptador financiero.

Entregables:

- ADR-0001 a ADR-0007 (`backend/docs/adr/`).
- Este informe consolidado con matrices de capacidades, madurez y riesgo, evidencia, payloads, puertos conceptuales y recomendación.
- Criterios para la suite de cumplimiento (10 tests) y para los tests live.

## 2. Resumen ejecutivo

1. **SIigo es el candidato técnico inicial** para el primer adaptador financiero (API REST completa, idempotencia nativa, límites y webhooks documentados, ambiente de pruebas real). **No es selección definitiva**: queda condicionada a la matriz de riesgo, a la base de clientes (sin definir) y a la disponibilidad de credenciales de prueba.
2. **DIAN**: el primer vertical real es **GetAcquirer** (consulta de información del adquiriente) como piloto SOAP/WS-Security controlado. La **facturación electrónica completa merece una fase propia**. La **exógena no tiene API pública** (portal MUISCA/archivos) → permanece como flujo de preparación de archivos y asistencia.
3. **World Office** no es un adaptador único: se clasifica por modalidad (Cloud API, on-premise, archivos, agente local); solo la modalidad Cloud API es candidata y con prioridad inferior a Siigo/Alegra.
4. La arquitectura se decide como **ports-and-adapters con modelo canónico agnóstico** (ADR-0001, ADR-0006): dominio aislado de los proveedores, multiempresa desde el diseño.
5. La falta de credenciales reales es condición planificada: la validación se hará con contratos mock (`httpx.MockTransport`) y los tests live quedan como criterios documentados, habilitables cuando existan credenciales.

## 3. Matriz de capacidades por proveedor

| Capacidad | Siigo | Alegra | World Office (Cloud) | DIAN |
|---|---|---|---|---|
| Terceros (crear/consultar) | Sí (`/customers`) | Sí (`/contacts`) | Sí (`terceros/listarTerceros`) | Solo consulta de adquiriente (GetAcquirer) |
| Productos/ítems | Sí (`/products`) | Sí (`/items`) | Sí (Inventarios) | — |
| Facturas de venta | Sí (`/invoices`) | Sí (`/invoices`) | Sí (Ventas) | Emisión vía SOAP (fase propia) |
| Facturas de compra | Sí (`/purchases`) | Sí (`/purchase-invoices`) | Sí (Compras) | — |
| Notas crédito | Sí (`/credit-notes`) | Sí (`/credit-notes`) | — | — |
| Recibos / pagos | Sí (`/vouchers`, `/payment-receipts`) | Sí (`/payments`) | Sí (Carteras-Recaudos, CxP) | — |
| Comprobantes contables | Sí (`/journals`) | Sí (`/journals`) | Sí (Contabilidad) | — |
| Cotizaciones | Sí (`/quotations`) | Sí (`/quotations`) | — | — |
| Impuestos / retenciones | Configuración (`/taxes`, retenciones) | Sí (`/taxes`) | Configuración | Régimen normativo propio |
| Webhooks | Sí (topic `public.siigoapi.*`) | Sí (12 eventos, headers configurables) | No confirmado | — |
| Idempotencia nativa | Sí (`Idempotency-Key`) | No (a resolver en el adaptador) | No confirmado | trackId en envío electrónico |
| Sandbox/pruebas | Empresa de pruebas (10 rpm) | Sin sandbox formal | No confirmado | Ambiente de habilitación (GetAcquirer: solo tablas de prueba) |

Fuente: ver §8 (evidencia documental).

## 4. Matriz de madurez M0–M5

| Nivel | Definición |
|---|---|
| **M0** | Solo documentación pública disponible (sin validar). |
| **M1** | Validado documentalmente (guias oficiales, especificación). |
| **M2** | Probado manualmente (sin credenciales reales, con datos/contratos mock). |
| **M3** | Probado con credenciales reales (ambiente de pruebas del proveedor). |
| **M4** | Integrado mediante prototipo (código de prueba conectado). |
| **M5** | Listo para producción. |

Estado actual por proveedor:

| Proveedor | Madurez alcanzada | Próximo hito para subir |
|---|---|---|
| DIAN — GetAcquirer | M1 | M3 con habilitación + credenciales + certificado |
| DIAN — Facturación electrónica | M1 | Fase propia (habilitación, firma, numeración) |
| DIAN — Exógena | M0 | No aplica web service (portal/archivos) |
| Siigo | M1 | M2/M3 con credenciales de la empresa de pruebas |
| Alegra | M1 | M2/M3 con cuenta de pruebas real |
| World Office Cloud | M1 | M3 con token de 12 h |
| World Office on-premise | M0 | Requiere decisión de mecanismo (BD/conector/archivos) |

## 5. Matriz de riesgo por proveedor

Escala: 🔴 alto / 🟡 medio / 🟢 bajo. No aplica (—) cuando el riesgo no existe.

| Riesgo | DIAN | Siigo | Alegra | World Office |
|---|---|---|---|---|
| Cambios de API | 🟡 (servicios SOAP estables; normas nuevas) | 🟢 (documentación estable) | 🟢 | 🟡 (límites aún placeholder) |
| Rate limit | 🟢 (consultas uno-a-uno) | 🟡 (10 rpm pruebas / 100 rpm prod por empresa) | 🟢 (150 rpm cuenta) | 🟡 (límites desconocidos) |
| Sandbox | 🟢 (habilitación real) | 🟢 (empresa de pruebas) | 🟡 (sin sandbox formal) | 🟡 (no confirmado) |
| Webhooks | — | 🟢 (topic documentados) | 🟢 (headers configurables) | 🔴 (no confirmados) |
| Autenticación | 🔴 (WS-Security + certificado, alta complejidad) | 🟢 (OAuth2 documentado) | 🟢 (Basic simple) | 🟡 (JWT 12 h, renovación) |
| Documentación | 🟡 (guías densas, foros de integradores) | 🟢 (buena) | 🟢 (buena) | 🟡 (límites placeholder) |
| Complejidad de integración | 🔴 (SOAP/MTOM, asíncrono) | 🟢 | 🟢 | 🟡 |
| Dependencia comercial | 🟡 (relación DIAN) | 🟡 (credenciales gestionadas por Siigo) | 🟢 | 🔴 (token 12 h manual, sin API on-premise) |
| Riesgo de mantenimiento | 🟡 (normas cambiantes) | 🟢 | 🟢 | 🟡 (rotación manual) |

## 6. Comparativa y recomendación provisional

Ponderación cualitativa (evidencia de §8; no es aún una decisión de producto):

| Criterio | Siigo | Alegra | World Office Cloud |
|---|---|---|---|
| Cobertura contable | Alta | Alta | Media-Alta |
| Idempotencia | Alta (nativa) | Baja (a implementar) | Baja/desconocida |
| Límites conocidos | Sí (10/100 rpm) | Sí (150 rpm) | No (placeholder) |
| Sandbox | Sí | No | No confirmado |
| Webhooks | Sí | Sí | No confirmado |
| Complejidad auth | Baja (OAuth2) | Baja (Basic) | Media (JWT 12 h) |
| Madurez documental | Alta | Alta | Media |

**Recomendación provisional: Siigo como candidato técnico inicial**, confirmable (o no) al completar la base de clientes y obtener credenciales de la empresa de pruebas. Alegra es la alternativa más cercana. World Office queda condicionado a la modalidad Cloud y a confirmar límites/renovación.

## 7. Estrategia de autenticación transversal

Resumen (detalle en ADR-0007):

- Capa común de SecretStore (secreto por `company_id` + proveedor) con cifrado en reposo, rotación, renovación automática de tokens cortos y revocación forzosa por empresa.
- Por proveedor: OAuth2→JWT (Siigo), Basic (Alegra), JWT 12 h (World Office Cloud), WS-Security + certificado digital (DIAN).
- Regla transversal (vigente en el repo): nunca loggear secretos (precedente `test_secrets_in_logs.py`).
- **Sin variables de credenciales en `.env.example`** en esta fase (decisión del usuario); los nombres previstos están documentados en cada ADR (0002-0005, 0007).

## 8. Evidencia documental

| Proveedor | Fuente | Fecha de consulta | Confirmado |
|---|---|---|---|
| DIAN | Guía herramienta para el consumo de Web Services (dian.gov.co, PDF) | 2026-08-06 | GetAcquirer SOAP `IWcfDianCustomerServices`; autenticación WS-Security; ambiente de habilitación; MTOM/zip |
| DIAN | Resolución 000202 del 31/03/2025 (modifica arts. 69-70, Res. 165/2023) | 2026-08-06 | Uso exclusivo para FEV/DEE; prohibido uso masivo; datos de adquiriente 2023-2024; tipos de documento permitidos |
| DIAN | Comunicado de prensa 026 (2025-04-01) | 2026-08-06 | Disponibilidad del servicio |
| Siigo | developers.siigo.com/docs/siigoapi (intro, errores, Partner Id, idempotencia, bloqueo, facturación electrónica) | 2026-08-06 | Endpoints, paginación, límites 10/100 rpm, timeout 120s, `Idempotency-Key` (POST, máx 30 chars), Partner-Id obligatorio, webhooks `public.siigoapi.*` |
| Siigo | Portal de clientes (generar credenciales API) | 2026-08-06 | `username` + `access_key` → JWT; máx 5 aplicaciones; restablecer credenciales |
| Alegra | developer.alegra.com (guías, referencia, límite de request, webhooks) | 2026-08-06 | Basic auth (`email:token`), endpoints, paginación `start`/`limit` (máx 30), 150 rpm + `X-Rate-Limit-*`, 12 eventos de webhook con headers configurables, ausencia de idempotencia nativa |
| World Office | devapidoc.worldoffice.cloud (intro, auth, secciones Terceros/Ventas/Compras/Inventarios/Contabilidad/Carteras/CxP) | 2026-08-06 | Base `api.worldoffice.cloud/api`, JWT 12 h (`gestionarTokenAPILicencia` o UI), `Authorization: WO <token>`, endpoints (ej. `compras/listarDocumentoCompra`), límites placeholder |

## 9. Payloads sanitizados (ejemplos de mapeo al canónico)

Ejemplo — tercero canónico desde tres proveedores (datos ficticios):

```json
{
  "integration_id": "cmp_01:siigo:12345",
  "company_id": "cmp_01",
  "document_type": "13",
  "document_number": "900123456",
  "name": "DISTRIBUCIONES EJEMPLO SAS",
  "email": "contacto@ejemplo.co",
  "city": "BOGOTA D.C."
}
```

- Siigo `POST /v1/customers` → `{ "type": "13", "identification": "900123456", "name": { "trade_name": "DISTRIBUCIONES EJEMPLO SAS" }, "address": { "city": { "name": "BOGOTA D.C." } }, "emails": ["contacto@ejemplo.co"] }`
- Alegra `GET /api/v1/contacts` → `{ "type": "client", "name": "DISTRIBUCIONES EJEMPLO SAS", "identification": "900123456", "email": "contacto@ejemplo.co", "address": { "city": "Bogotá" } }`
- World Office `terceros/listarTerceros` → `{ "datos": [{ "tipoDocumento": "13", "documento": "900123456", "nombre": "DISTRIBUCIONES EJEMPLO SAS", "correo": "contacto@ejemplo.co" }], "codigoRespuesta": 0 }`
- DIAN `GetAcquirer` (respuesta) → solo aporta `nombre/razón social` + `correo electrónico` (ver ADR-0002; no se rellenan datos prohibidos).

> Los payloads reales y completos se consolidan en la fase de implementación con credenciales; estos ejemplos solo fijan el patrón de mapeo canónico.

## 10. Puertos conceptuales (pseudocódigo de referencia)

```text
interface FinancialProviderPort:
    authenticate() -> Transport                    # inyecta credencial desde SecretStore
    get_party(company, external_id) -> Party
    list_parties(company, page) -> Page[Party]
    create_invoice(company, InvoiceCanonical) -> InvoiceCanonical
    get_journals(company, date_range) -> Page[JournalEntry]
    # extensiones opcionales: webhooks suscripción (interface opcional)

interface FiscalProviderPort:
    get_acquirer_information(company, document_type, number) -> Party  # DIAN GetAcquirer

adapters: SiigoAdapter, AlegraAdapter, WorldOfficeCloudAdapter  (implementan FinancialProviderPort)
          DianAcquirerAdapter                                    (implementa FiscalProviderPort)

registry(proveedor, company_id) -> port   # resuelve credenciales y límites por empresa
```

El dominio y los agentes solo consumen los ports y el modelo canónico (ADR-0001, ADR-0006).

## 11. Diseño de la suite de cumplimiento (10 tests)

Suite parametrizada por proveedor contra contratos mock (`httpx.MockTransport`), sin red ni credenciales:

| # | Test | Verifica |
|---|---|---|
| 1 | `autenticar` | Obtención de transporte autenticado (JWT/Basic/WS-Security según proveedor) |
| 2 | `consultar_tercero` | `get_party` → mapeo a `Party` canónico |
| 3 | `listar_terceros` | `list_parties` → mapeo de lista |
| 4 | `mapear_tercero_canonico` | Redondeo canónico→proveedor→canónico sin pérdida en campos núcleo |
| 5 | `paginacion` | Iteración con la estrategia propia (Siigo `page/page_size`; Alegra `start/limit` máx 30) |
| 6 | `rate_limits` | Detección de 429 y backoff según límites del proveedor |
| 7 | `credencial_invalida` | 401/403 → error `PROVIDER_AUTH_FAILED` sin filtrar secretos |
| 8 | `idempotencia` | Siigo `Idempotency-Key` (POST, máx 30 chars); Alegra estrategia de duplicados del adaptador |
| 9 | `auditoria` | Registro de la operación con `company_id` y correlación (sin datos sensibles) |
| 10 | `aislar_por_empresa` | `company_id` A no ve datos de `company_id` B (aislamiento multiempresa) |

Códigos de error nuevos que la suite consumirá (a añadir al catálogo en Fase 2): `PROVIDER_AUTH_FAILED`, `PROVIDER_RATE_LIMITED`, `PROVIDER_UNREACHABLE`, `PROVIDER_ERROR`.

## 12. Criterios de los tests live (habilitables cuando existan credenciales)

- **Opt-in y deshabilitados por defecto** (env flag dedicado, separados de la suite normal).
- Condicionados por entorno (nunca se ejecutan en CI sin credenciales).
- **Sin secretos ni payloads reales en el repo**; las credenciales se leen solo del entorno/SecretStore del ejecutor.
- Suben el nivel de madurez de M2 → M3 (probado con credenciales reales).

## 13. Plan del vertical DIAN (primera iteración: GetAcquirer)

1. Confirmar disponibilidad del servicio y credenciales (habilitación + certificado o credenciales de ambiente) — **bloqueador**.
2. Construir cliente SOAP (WSDL `IWcfDianCustomerServices/GetAcquirer`) con WS-Security, `Content-Type: action="http://wcf.dian.colombia/IWcfDianCustomerServices/GetAcquirer"`.
3. Validar: contratos XML, timeouts, errores DIAN, sanitización, auditoría, mapeo a canónico (`Party` parcial).
4. Suite de cumplimiento (mock) primero; luego live (M3) con casos controlados.
5. **No** presentar como validación de RUT ni inferir responsabilidades/régimen/estado tributario (ADR-0002).
6. La facturación electrónica completa queda como fase propia posterior.

## 14. Riesgos, bloqueadores y feature flags

Bloqueadores actuales:

- Credenciales de prueba (Siigo empresa de pruebas, Alegra cuenta de pruebas, World Office token 12 h, DIAN habilitación + certificado).
- Base de clientes por definir (condiciona la selección definitiva del proveedor).
- World Office: confirmar límites reales y mecanismo de renovación del token; decisión de mecanismo para on-premise.

Feature flags previstos para Fase 2 (patrón ya existente en `settings.py`): `DIAN_INTEGRATION_ENABLED`, `SIIGO_INTEGRATION_ENABLED`, `ALEGRA_INTEGRATION_ENABLED`, `WORLDOFFICE_INTEGRATION_ENABLED`, `MOCK_EXTERNAL_SERVICES` (existente). Los adaptadores mock se activan con `MOCK_EXTERNAL_SERVICES` (patrón de `consultar_obligaciones.py`).

## 15. Conclusión y puerta de Fase 2

Con la aprobación de estos hallazgos se autoriza la Fase 2: **infraestructura de proveedores** (ports, modelo canónico como código, contracts/mappers, factory neutral, catálogo de errores de proveedor) sin adaptadores reales productivos ni credenciales. El primer adaptador financiero y el primer vertical DIAN se ejecutan en Fases 3 y 4 respectivamente.

## Referencias

- ADR-0001 a ADR-0007 (`backend/docs/adr/`)
- `backend/docs/cierre-fase0.md` (precedentes de calidad, error catalog y patrones reutilizables)
