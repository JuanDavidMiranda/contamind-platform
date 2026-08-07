# ADR-0001: Arquitectura de proveedores neutral (fiscal vs financiero)

- **Estado:** Propuesto (pendiente de revisión con los hallazgos del spike de Fase 1)
- **Fecha:** 2026-08-06
- **Fase:** 1 (spike de viabilidad — solo investigación y diseño conceptual)
- **Categoría:** Arquitectura de integraciones
- **Relacionados:** ADR-0002 (DIAN), ADR-0003 (Siigo), ADR-0004 (Alegra), ADR-0005 (World Office), ADR-0006 (modelo canónico), ADR-0007 (autenticación)

## Contexto

ContaMind AI debe automatizar obligaciones tributarias y operación contable de sus clientes. Los sistemas financieros disponibles en el mercado colombiano son heterogéneos (Siigo, Alegra, World Office), con APIs, formatos y modelos de negocio distintos. A la vez, la DIAN es un proveedor de naturaleza distinta: no es un sistema contable sino la autoridad fiscal con servicios oficiales propios.

Riesgos de diseño si se actúa sin port:

- El dominio de negocio (agentes, workflows, módulos) quedaría acoplado al esquema de un proveedor concreto.
- Añadir o reemplazar un proveedor implicaría cambios en el dominio.
- Una integración "de una sola pieza" por proveedor duplicaría transporte, autenticación, paginación, rate limits y auditoría.
- World Office no ofrece un mecanismo homogéneo (ver ADR-0005): modelarlo como una sola API sería incorrecto.

## Decisión

1. **Separar dos dominios de integración:**
   - `FinancialProviderPort` — sistemas financieros (Siigo, Alegra, World Office). Operaciones contables y comerciales: terceros, productos, facturas, notas, pagos, comprobantes contables.
   - `FiscalProviderPort` — DIAN (vertical institucional). Servicios oficiales de la autoridad tributaria (facturación electrónica, consulta de adquirientes), con protocolos SOAP/WS-Security propios.

2. **Capas obligatorias (de arriba hacia abajo):**
   ```
   Agentes de negocio (orquestador, workflows, módulos)
        │
        ▼
   Modelo contable canónico (agnóstico; ver ADR-0006)
        │
        ▼
   FinancialProviderPort / FiscalProviderPort (interfaces)
        ├── SiigoAdapter
        ├── AlegraAdapter
        ├── WorldOfficeAdapter (por modalidad; ver ADR-0005)
        └── FutureProviderAdapter
   ```

3. **Neutralidad del diseño:**
   - El dominio conoce únicamente el modelo canónico y los ports. Nunca tipos, DTOs ni constantes de un proveedor.
   - Los adaptadores son traducción pura: transporte/formato → canónico y viceversa. Sin lógica de negocio.
   - La selección del proveedor se resuelve por un **registry/factory neutral** (mapa por nombre), sin condicionales de proveedor en el dominio.
   - Los identificadores externos de cada proveedor se conservan en campos separados del identificador interno (ver ADR-0006).
   - El modelo canónico no espeja el esquema de ningún proveedor (ver ADR-0006).

4. **World Office no es un único adaptador:** se clasifica por modalidad de instalación (`CLOUD_API`, `ON_PREMISE`, `FILE_EXCHANGE`, `LOCAL_AGENT`) y cada modalidad se resuelve como una implementación del port o como un mecanismo fuera de port (ver ADR-0005).

5. **DIAN queda fuera de `FinancialProviderPort`:** se modela con su propio port fiscal, porque su protocolo (SOAP + WS-Security + certificados), su ciclo (habilitación vs producción, asincronía) y su régimen normativo difieren estructuralmente de las APIs REST financieras.

## Consecuencias

Positivas:

- El dominio es estable ante cambios o incorporación de proveedores.
- Se puede implementar un adaptador a la vez y validarlo con la misma suite de cumplimiento (ver `spike-fase1.md`).
- La investigación y el ADR por proveedor (0003-0005) aíslan el conocimiento técnico de cada integración.
- La separación fiscal/financiero permite avanzar el vertical DIAN sin acoplarse a los sistemas contables.

Negativas / trade-offs:

- Costo inicial de definir el modelo canónico y los ports (una capa más).
- Riesgo de sobredimensionar el canónico si se incluyen capacidades que ningún proveedor ofrece.
- Los adaptadores de modalidad (World Office) pueden necesitar interfaces específicas adicionales; el port debe prever extensiones opcionales.

## Alternativas consideradas

| Alternativa | Por qué se descarta |
|---|---|
| Un único "provider port" para DIAN y sistemas financieros | Protocolos, ciclo de vida y propósitos distintos; forzaría una interfaz genérica pobre para ambos. |
| Acoplar el dominio al modelo del proveedor dominante (p. ej. Siigo) | Viola la neutralidad y encarece el reemplazo; contradice el requisito de no favorecer a Siigo. |
| Un adaptador único con condicionales por proveedor | No escala; duplica la complejidad de transporte/auth/paginación; dificulta probar un proveedor sin los demás. |
| Sin port (llamadas directas a cada API desde los módulos) | Acoplamiento directo del dominio a proveedores; inviable para multiempresa y multi-provider. |

## Madurez / Evidencia

- **M1 (validado documentalmente):** el concepto de ports-and-adapters aplicado a esta arquitectura se valida contra la documentación oficial de los cuatro proveedores (ver ADRs 0002-0005 y `spike-fase1.md`). No hay aún prototipo ni credenciales (M2-M5 pendientes).
- Este ADR establece el contenedor en el que se implementará la Fase 2 (puertos, modelo canónico, contratos) tras la aprobación de los hallazgos.

## Referencias

- `backend/docs/spike-fase1.md` (matrices, evidencia, recomendación)
- ADR-0002 a ADR-0007
- Precedente en el repo: patrón ABC + inyección (`SessionStore` / `InMemorySessionStore` en `app/ai/session/manager.py`)
