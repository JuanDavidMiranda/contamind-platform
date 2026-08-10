# ADR-0009: Fuentes de datos por empresa

- **Estado:** Propuesto
- **Fecha:** 2026-08-10
- **Fase:** 2 (ingesta y conectividad)
- **Relacionados:** ADR-0001, ADR-0006, ADR-0007, ADR-0008

## Contexto

Una empresa cliente puede utilizar Novasoft, SysCafé, otro software contable o ninguno. En todos los casos ContaMind debe obtener información contable de forma segura, auditable y aislada por empresa. Una arquitectura centrada únicamente en proveedores API no cubre exportaciones de archivos, instalaciones locales, bases de datos autorizadas ni captura manual.

## Decisión

La unidad de integración es `CompanyDataSource`, una fuente configurada por empresa. Una fuente describe su conector, modalidad, capacidades, estado y una **referencia** opaca a credenciales; nunca guarda secretos en el modelo de dominio.

| Tipo de fuente | Modalidad | Ejemplo | Regla |
|---|---|---|---|
| Software contable | API cloud, agente local o conector de BD | Siigo, Novasoft, ERP propio | Implementa un adaptador autorizado por el software. |
| Importación de archivos | Carga CSV/XLSX/exportación nativa | SysCafé u hoja de cálculo | Usa un perfil de mapeo explícito y valida cada fila. |
| Base de datos | Conector local autorizado | Instalación on-premise | Solo mediante agente/conector con permisos mínimos. |
| Captura manual | Formulario asistido | Empresa sin software | Alimenta el mismo modelo canónico. |
| Autoridad fiscal | Servicio fiscal | DIAN | Mantiene su port institucional especializado. |

El flujo común es:

```text
CompanyDataSource → extraer/cargar → validar → mapear al canónico
                  → deduplicar → auditar → workflows de ContaMind
```

Los conectores se resuelven por `connector_id`, no por condicionales de marca. Las primeras implementaciones universales son `csv_import` y `xlsx_import`: reciben contenido cargado por el cliente, aplican un `ImportProfile` de columnas, persisten terceros canónicos y retornan rechazos por fila. El lector XLSX opera en modo de solo lectura, no ejecuta fórmulas ni macros y limita el tamaño descomprimido del libro.

## Consecuencias

- Un cliente puede operar sin software contable mediante importación de archivos o captura manual.
- Las credenciales del software se almacenan solo detrás de `SecretStore`; `CompanyDataSource` conserva una referencia, no el valor secreto.
- Novasoft o SysCafé podrán conectarse por API, agente, BD o archivo cuando exista contrato técnico y autorización; no se presupone un protocolo.
- Fuentes, perfiles, lotes importados y terceros ya se persisten; las sincronizaciones productivas requieren conectores y autorizaciones específicos.

## Criterios de seguridad

- Credenciales, tokens, contraseñas de BD y certificados no aparecen en archivos cargados, logs, modelos ni respuestas HTTP.
- Las conexiones locales usan un agente autenticado y privilegios mínimos; nunca se expone una BD del cliente directamente a internet.
- Cada importación registra origen, empresa, correlación, filas aceptadas y rechazadas, sin almacenar el contenido sensible del archivo en el evento de auditoría.
