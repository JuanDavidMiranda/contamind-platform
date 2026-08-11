# ADR-0018: Capa LLM conversacional para salud contable

- **Estado:** Aceptado
- **Fecha:** 2026-08-11
- **Fase:** Agentes de negocio
- **Relacionados:** ADR-0010, ADR-0012 y ADR-0017

## Contexto

El reporte de salud contable ya ofrece datos confiables y agregados, pero una selección de palabras clave no permite una conversación natural sobre prioridades, interpretación de hallazgos o remediación. El objetivo es que un usuario autorizado pueda hacer preguntas libres relacionadas con la salud contable sin convertir al modelo de lenguaje en la fuente de verdad ni darle acceso a datos o acciones sensibles.

## Decisión

1. AccountingHealthService sigue calculando el reporte determinista antes de cualquier llamada al modelo. Las métricas, severidades, hallazgos y permisos continúan siendo responsabilidad exclusiva del backend.
2. La capa conversacional usa OpenAI Responses API solo cuando LLM_ENABLED está activo y OPENAI_API_KEY está configurada. El modelo por defecto es gpt-5.6-terra, configurable por ambiente.
3. La proyección del reporte transmitida al modelo excluye company_id, filas, nombres, documentos, correos, credenciales, payloads de proveedores, SQL, permisos e identificadores internos. La pregunta y el historial se limitan, se redactan por patrones conocidos y se bloquean localmente cuando incluyen identificadores frecuentes. Esto no es una solución DLP completa: nombres, direcciones u otros datos personales escritos libremente pueden no ser reconocidos. La activación productiva requiere análisis de privacidad, aviso al usuario y el acuerdo de tratamiento aplicable.
4. La solicitud usa store=false y un safety_identifier estable generado mediante HMAC del actor autenticado. No se usa previous_response_id ni estado remoto de conversación de la aplicación. `store=false` no sustituye las políticas de retención, monitoreo de abuso o el acuerdo de datos del proveedor.
5. El modelo produce una salida JSON estructurada con resultado, explicación, códigos de hallazgo y preguntas sugeridas. El backend descarta códigos inexistentes, rechaza respuestas aplicadas a la empresa que no estén ancladas a hallazgos y rechaza cifras libres en la narración; después redacta identificadores sensibles de salida y entrega el reporte determinista junto con la narración.
6. La conversación se mantiene solo en la sesión temporal ya namespaceada por usuario, empresa y conversación. Se conservan como máximo ocho mensajes sanitizados; agent_executions no almacena pregunta, prompt, respuesta, reporte ni response_id.
7. La capa LLM no puede leer la base directamente, invocar proveedores, modificar registros, decidir RBAC ni exponer datos individuales. POST /api/v1/companies/{company_id}/agents/accounting-health/chat fija este alcance durante toda la conversación. Preguntas fuera de salud contable, solicitudes de escritura, documentos o asesoría fiscal o jurídica concluyente se rechazan dentro del alcance conversacional.
8. Si el flag está apagado, falta la clave, ocurre timeout, rate limit o error del proveedor, se conserva el diagnóstico determinista y no se filtra el error remoto.

## Consecuencias

- El endpoint explícito del agente admite preguntas libres de salud contable sin depender de palabras clave. El chat general de empresa conserva selección por intención, y el chat heredado anónimo mantiene su comportamiento general sin acceder a datos empresariales.
- La experiencia es conversacional, pero la interfaz también devuelve evidencia y el reporte estructurado para que la UI muestre hechos verificables.
- La continuidad no sobrevive un reinicio ni se comparte entre réplicas. Un historial persistente requerirá una decisión explícita de retención, cifrado, borrado y tratamiento de datos antes de implementarse.
- La configuración se mantiene desactivada por defecto. En staging y producción, habilitar LLM_ENABLED sin OPENAI_API_KEY impide iniciar la aplicación.

## Verificación

- Las pruebas usan un transporte HTTP simulado: comprueban store=false, safety_identifier no reversible, ausencia de company_id y datos sensibles en la solicitud, salida estructurada, rechazo de respuestas no ancladas o con cifras libres, degradación ante 429 y redacción de identificadores.
- Las pruebas de API validan que una pregunta libre en el endpoint explícito llega al agente, conserva el reporte determinista, bloquea identificadores antes de invocar el narrador y puede incorporar un narrador simulado sin ampliar permisos.
- La suite SQLite completa pasa con 129 pruebas y 1 omitida; no se requiere una clave real para ejecutar las pruebas.
