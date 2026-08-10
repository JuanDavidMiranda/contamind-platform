# ADR-0008: Proveedores configurables y modalidades de integración

- **Estado:** Propuesto
- **Fecha:** 2026-08-10
- **Fase:** 2 (infraestructura multi-proveedor)
- **Relacionados:** ADR-0001, ADR-0003 a ADR-0007, `spike-fase1.md`

## Contexto

ContaMind no puede depender de un proveedor prioritario. La base de clientes puede usar Siigo, Novasoft, SysCafé u otros sistemas con mecanismos de conexión distintos. Limitar el registry a un enum cerrado o asumir que todos los proveedores ofrecen una API REST impide incorporar soluciones legítimas de nómina, punto de venta, archivos o conectores locales.

La evidencia pública revisada para Novasoft confirma soluciones web de nómina/ERP e integración con ERP, HCM y contabilidad, pero no una API pública de desarrolladores con contrato verificable. SysCafé documenta exportación e importación de catálogos por archivo y su módulo Master table para sincronización entre puntos; tampoco se confirmó una API pública general. Por tanto, ninguno debe modelarse como REST por defecto.

## Decisión

1. El identificador del proveedor es un valor configurable (`provider_id`), no una lista cerrada en el dominio. Los aliases conocidos (`siigo`, `alegra`, `worldoffice_cloud`, `dian`, `novasoft`, `syscafe`) solo ayudan a la configuración inicial.
2. Cada proveedor se registra con `ProviderDescriptor`: nombre visible, modalidad y capacidades. La factory resuelve cualquier `provider_id` registrado; la habilitación se inyecta por configuración de despliegue, no se codifica en el dominio.
3. Modalidades soportadas:
   - `cloud_api`: API remota autenticada.
   - `file_exchange`: importación/exportación de archivos validada y auditable.
   - `local_agent`: agente instalado en la red del cliente.
   - `database_connector`: conector local de solo las tablas/consultas autorizadas.
   - `vendor_managed`: integración mediada por el proveedor mientras se confirma su mecanismo técnico.
4. Los ports se definen por capacidad común, no por marca. Un proveedor de nómina no se fuerza al `FinancialProviderPort` hasta que exista un contrato canónico de nómina. Las extensiones se añaden como ports versionados.
5. Ningún proveedor se considera seleccionado o prioritario. El orden de implementación dependerá de la modalidad confirmada, las credenciales/autorizaciones disponibles y el valor para clientes, manteniendo el mismo contrato de cumplimiento.

## Matriz inicial por modalidad

| Proveedor | Modalidad inicial | Capacidades confirmadas públicamente | Estado técnico |
|---|---|---|---|
| Siigo | `cloud_api` | Terceros, facturas, pagos, comprobantes | Documentado en ADR-0003; sin prioridad de producto |
| Alegra | `cloud_api` | Terceros, facturas, pagos, comprobantes | Documentado en ADR-0004 |
| World Office Cloud | `cloud_api` | Terceros, ventas, compras, contabilidad | Documentado en ADR-0005 |
| DIAN | Port fiscal especializado | Consulta institucional y servicios fiscales | Documentado en ADR-0002 |
| Novasoft | `vendor_managed` (por confirmar) | Nómina, ERP, HCM e integración contable interna | Solicitar contrato/API o mecanismo aprobado al proveedor |
| SysCafé | `file_exchange` | Exportación/importación de catálogos y sincronización de puntos | Confirmar formatos, permisos y alcance de lectura/escritura |

## Consecuencias

- Añadir un proveedor no exige cambiar el modelo canónico ni condicionales por marca.
- Los conectores por archivo o agente local se pueden implementar con la misma auditoría, aislamiento por empresa y controles de secretos.
- La integración real de Novasoft y SysCafé queda bloqueada hasta tener autorización, contrato técnico y datos de prueba sanitizados.
- La suite mock de cumplimiento sigue siendo el requisito previo para cualquier adaptador concreto.

## Evidencia inicial

- Novasoft: [Software de Nómina](https://www.novasoft.com.co/software-de-nomina-novasoft/) y [Software ERP](https://www.novasoft.com.co/software-erp-novasoft/), consultados el 2026-08-10.
- SysCafé: [Preguntas frecuentes sobre importación/exportación](https://doc.syscafe.com/preguntas-frecuentes) y [Master table y Master doc](https://doc.syscafe.com/post/master-table), consultados el 2026-08-10.
