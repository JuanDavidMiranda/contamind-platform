# ADR-0006: Modelo contable canónico (dominio agnóstico de integraciones)

- **Estado:** Propuesto (pendiente de revisión)
- **Fecha:** 2026-08-06
- **Fase:** 1 (spike de viabilidad — versión conceptual; implementación en Fase 2)
- **Categoría:** Modelo de dominio canónico
- **Relacionados:** ADR-0001, ADR-0002, ADR-0003, ADR-0004, ADR-0005, `spike-fase1.md`

## Contexto

Cada proveedor (Siigo, Alegra, World Office, DIAN) expone modelos distintos para conceptos que son el mismo negocio: terceros, ítems/productos, facturas, notas, pagos, comprobantes contables, impuestos y monedas. Sin un modelo intermedio agnóstico, el dominio y los agentes dependerían de las diferencias de cada proveedor.

Además, el negocio de ContaMind AI es **multiempresa**: un mismo tenant operaría con un proveedor (o varios) y con múltiples empresas dentro de él. El modelo canónico debe soportar ese aislamiento.

## Decisión

### 1. Principios del modelo canónico

1. **El modelo canónico es propiedad del dominio, no de los proveedores.** Es la única representación que el dominio conoce.
2. **No espeja ningún proveedor.** Nace del análisis de capacidades comunes y de las obligaciones tributarias colombianas que ContaMind AI debe resolver (exógena, facturación, asistencia).
3. **Agnóstico de protocolo y transporte.** No contiene tipos SOAP ni REST de ningún proveedor.
4. **Versionado explícito** del propio modelo canónico (semver). Un adaptador declara la versión del canónico que emite/consume; el registry valida compatibilidad.
5. **El canónico es un contrato de negocio**: si un proveedor no cubre un campo, el campo viaja como "no disponible" (ausente / `None`), nunca como dato inventado.
6. **Los identificadores externos viven en el mapeo del adaptador, no en las entidades de negocio**, pero se conservan en campos separados para rastreabilidad (ver §3).

### 2. Entidades núcleo (v1 conceptual)

| Entidad | Campos núcleo | Notas |
|---|---|---|
| `Tenant` | id, nombre, país (CO), proveedores habilitados por empresa | Aislamiento multiempresa |
| `Company` | id, tenant_id, código interno del proveedor (empresa), moneda funcional | Una empresa se asocia a un proveedor y su id externo |
| `Party` (tercero) | id, tipo (cliente/proveedor/ambos), tipo de documento DIAN, número de documento, nombre/razón social, correo, teléfono, ciudad, direcciones, régimen/responsabilidad fiscal | Mapeo desde `/customers` (Siigo), `/contacts` (Alegra), `terceros` (WO), `GetAcquirer` (DIAN: solo nombre/razón social + correo) |
| `Item` (producto/servicio) | id, código, nombre, tipo (producto/servicio), unidad, precio, impuestos, cuenta contable | Impuestos como referencia (ver §5) |
| `Invoice` | id, tipo (venta/compra/nota crédito/nota débito/documento soporte), número, fecha, emisor, receptor, items/líneas, impuestos, retenciones, totales, moneda, estados, electrónico (CUFE/CUDE o ref. DIAN) | Modelo genérico cubre ventas, compras, notas, cotizaciones, remisiones |
| `Payment` | id, tipo (caja/egreso/abono), fecha, monto, moneda, referencia (invoice_id), método de pago | Soporta recibos de caja (Siigo) y payments (Alegra) |
| `JournalEntry` (comprobante contable) | id, fecha, concepto, líneas débito/crédito (cuenta, tercero, monto, centro de costo), totales, referencia origen | `/journals` Siigo y Alegra, Contabilidad WO |
| `Tax` / `Withholding` | id, código, nombre, tipo (IVA/retención/ICA/CREE), tasa, aplicable | Configuración por empresa, mapeada por código al proveedor |
| `Currency` | código ISO 4217, tasa de conversión vigente, fecha | Moneda funcional por empresa + operaciones en moneda extranjera |

> v1 solo modela lo común y lo que ContaMind AI consume hoy; entidades de inventario avanzado o de eventos de webhook se añaden por extensión versionada (§6) cuando un vertical lo requiera.

### 3. Identificadores

- **Id interno (`id`):** UUID generado por ContaMind AI, inmutable. Es la clave primaria en nuestra persistencia (la persistencia llega en Fase 2).
- **Id externo (`external_id`):** identificador nativo del proveedor (p. ej. id de cliente Siigo, id de contacto Alegra, id de tercero WO). Se conserva en un campo separado del id interno. Un mismo registro nunca mezcla id interno y externo en el mismo campo.
- **Id de integración (`integration_id`):** compuesto por `(company_id, proveedor, id_externo)` para resolver conflictos multiempresa y evitar colisiones entre proveedores distintos.
- Regla: **el dominio nunca genera ni depende de id_externo**; solo el adaptador lo traduce y lo expone para rastreabilidad y reconciliación.

### 4. Mapeo (adaptadores como traducción pura)

- Cada adaptador implementa un mapeo bidireccional: `ProviderDTO ⇄ Canónico`.
- Mapa de terceros (patrón que se replica para el resto):
  - Siigo `customer` → `Party`: `identification` (número) + `type` (tipo doc) → `Party.document_number` / `Party.document_type`; `name` / `first_name + last_name` → `Party.name`; `email` → `Party.email`; `address.city` → `Party.city`.
  - Alegra `contact` → `Party`: `type` (client/provider) → `Party.party_type`; `name` → `Party.name`; `identification` → `Party.document_*`.
  - World Office `tercero` → `Party`: campos análogos según docs.
  - DIAN `GetAcquirerResponse` → `Party` parcial: solo `nombre/razón social` y `correo electrónico` que el servicio autoriza; **no** se rellenan datos prohibidos ni se infiere responsabilidad.
- El mapeo es **puro y testeable**: sin I/O, sin lógica de negocio, sin acceso a red.

### 5. Impuestos, retenciones y monedas

- Los impuestos se modelan como entidades de referencia configuradas **por empresa** (código canónico ↔ código del proveedor).
- En facturas, cada línea lleva `taxes` con los impuestos aplicados (IVA) y `withholdings` (retención de renta, ICA, CREE). Los totales son consistentes: `subtotal + impuestos − retenciones = total`.
- Moneda: ISO 4217 + tasa por fecha. Operaciones en moneda extranjera se almacenan en moneda de la operación y se expone la conversión a la moneda funcional de la empresa (la conversión exacta se valida contra la configuración del proveedor).

### 6. Versionado y extensibilidad

- El canónico se versiona (ej. `canonical:1.0.0`); cambios compatibles = minor/patch, cambios incompatibles = major (obligan a coexistir versiones o migrar adaptadores).
- Extensibilidad por **entidades nuevas o campos opcionales versionados**, no por campos polimórficos ni "dumps" JSON arbitrarios.
- Los conceptos específicos de un proveedor que no tienen equivalente canónico **no entran al canónico**: quedan en el adaptador (p. ej. opciones de impresión de un proveedor).

### 7. Sobre la "unidad de negocio" de ContaMind AI

- El aislamiento por empresa (tenant) es transversal: los agentes, la auditoría y los límites operan por `company_id`. La suite de cumplimiento valida el aislamiento (test 10).

## Consecuencias

Positivas:

- El dominio y los agentes quedan aislados de los proveedores (refuerza ADR-0001).
- La suite de cumplimiento puede validar el mapeo (test 3) sin credenciales.
- Multiempresa soportada desde el diseño.

Negativas / trade-offs:

- Costo inicial de definir y mantener el canónico.
- Riesgo de sobredimensionar: por eso v1 es mínima y se extiende por versionado.
- Los campos "no disponibles" por proveedor obligan a decisiones de UI/workflow (qué hacer cuando el dato no existe).

## Alternativas consideradas

| Alternativa | Por qué se descarta |
|---|---|
| Modelo = esquema del proveedor dominante (Siigo) | Violenta la neutralidad; Sesga a un proveedor. |
| Entidades "tipo diccionario" (dumps JSON por proveedor) | Sin tipos, sin validación, sin versionado; imposible razonar el dominio. |
| Un DTO por proveedor usado directamente por los agentes | Acopla el dominio; no hay traducción común. |

## Madurez / Evidencia

- **M1 (validado documentalmente):** la definición conceptual del canónico se deriva de los recursos reales de cada proveedor (ADR-0003/0004/0005/0002).
- Implementación, contratos y versionado concretos: Fase 2 (puertos + modelos canónicos como código).

## Referencias

- ADR-0001 (arquitectura de proveedores), ADR-0002 (DIAN), ADR-0003 (Siigo), ADR-0004 (Alegra), ADR-0005 (World Office)
- `backend/docs/spike-fase1.md` (matrices de capacidades → de ahí salen las entidades v1)
