# ADR-0017: Agente de salud contable por empresa

- **Estado:** Aceptado
- **Fecha:** 2026-08-11
- **Fase:** Agentes de negocio
- **Relacionados:** ADR-0006, ADR-0009, ADR-0010, ADR-0012, ADR-0013, ADR-0014 y ADR-0016
- **Actualización:** ADR-0018 añade una capa conversacional LLM sin alterar la fuente determinista de hechos.

## Contexto

La plataforma ya conserva datos contables canónicos, fuentes, lotes de importación y trazabilidad por empresa. El siguiente paso no depende de credenciales reales de Siigo: puede entregar valor al detectar cobertura insuficiente, datos incompletos e inconsistencias en los registros disponibles.

El chat histórico (POST /api/v1/chat) no autentica al usuario y sus sesiones son temporales en memoria. Por tanto, no puede ser el canal para un agente que consulte datos empresariales. El sistema de ejecución activo es ChatService → Orchestrator → WorkflowManager; los componentes de dispatcher y task executor no participan aún en el camino de producción.

## Decisión

1. Se implementa AccountingHealthAgent, activado por el workflow accounting_health. Su fuente de hechos es determinista y de solo lectura; ADR-0018 permite una capa LLM opcional de redacción, sin herramientas de escritura.
2. El acceso explícito al agente se expone mediante POST /api/v1/companies/{company_id}/agents/accounting-health/chat. El controlador exige JWT, resuelve la empresa en el servidor y verifica VIEW_COMPANY_ROLES. La consulta está permitida para owner, admin, operator y viewer; no depende de que la empresa esté activa, pues es una lectura de auditoría. POST /api/v1/companies/{company_id}/chat conserva el chat general y selecciona workflow por intención.
3. El servidor genera un conversation_id UUID cuando no se envía uno. La sesión interna se namespacea por empresa, usuario y conversación. En cada solicitud se reconstruyen user_id y company_id; no se aceptan como datos confiables del cliente ni se guardan permisos o sesiones SQLAlchemy dentro del contexto persistido.
4. AccountingHealthService consulta solo agregados filtrados desde el origen por company_id. El reporte estable contiene métricas, estado global y hallazgos con código, severidad, evidencia numérica y recomendación. No incluye nombres, documentos, correos, payloads de proveedor, credenciales ni filas crudas.
5. La primera versión evalúa fuentes no activas o no disponibles, rechazos de importación, terceros sin identificación, documentos de tercero duplicados, ítems sin cuenta contable, facturas sin contraparte, pagos no vinculados y comprobantes descuadrados. Estos controles complementan, pero no sustituyen, las validaciones de captura e importación.
6. Cada ejecución se registra en agent_executions mediante la migración d6f2a9c8b4e1. La auditoría conserva tenant, empresa, actor, conversación, agente y versión, estado, correlación, cantidad y códigos de hallazgo, y tiempos. No almacena el mensaje, prompt, reporte ni datos personales.
7. El endpoint explícito fija accounting_health incluso en seguimientos con palabras de otros workflows. El chat heredado permanece disponible para conversación general, pero el orquestador bloquea la intención accounting_health cuando no existe una empresa autenticada. Así se mantiene compatibilidad sin abrir una ruta anónima hacia los datos.

## Consecuencias

- El agente puede entregarse y probarse sin depender de la integración real con Siigo; mejora su alcance a medida que se cargan fuentes y entidades canónicas.
- La selección por palabras clave sigue siendo predecible y auditable en el chat general. El endpoint explícito habilita conversación libre con la capa opcional de ADR-0018, sin reemplazar reglas ni ampliar permisos.
- Las sesiones siguen siendo temporales y locales al proceso. La clave compuesta impide cruces entre usuarios o empresas en una instancia, pero la continuidad entre réplicas requerirá un store compartido y control de concurrencia por conversación.
- Los hallazgos son señales de revisión, no correcciones automáticas ni certificaciones fiscales. Las acciones de escritura siguen requiriendo sus flujos, permisos e idempotencia propios.

## Verificación

- Pruebas de API cubren autenticación obligatoria, RBAC de lectura, aislamiento entre empresas, respuesta estructurada sin PII, auditoría agregada y la imposibilidad de activar el agente desde el chat heredado.
- La suite SQLite pasa con 129 pruebas y 1 omitida. La validación de migraciones PostgreSQL permanece opt-in y requiere el contenedor de desarrollo.
