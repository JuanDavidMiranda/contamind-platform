# ADR-0019: Agente y operación de cartera de ventas por empresa

- **Estado:** Aceptado
- **Fecha:** 2026-08-12
- **Fase:** Agentes de negocio
- **Supuestos:** La fuente contable registra correctamente facturas de venta, pagos y monedas. El agente no sustituye conciliación bancaria, evaluación crediticia, cobranza ni asesoría contable, tributaria, jurídica o financiera.

## Contexto

El núcleo canónico conserva facturas de venta, pagos, monedas y contrapartes. Para
gestionar cartera con precisión también necesita una fecha de vencimiento verificable,
condiciones de pago y un seguimiento humano trazable. La primera versión sólo podía
entregar agregados; no identificaba antigüedad ni ofrecía un canal separado y
autorizado para corregir términos o registrar una promesa de pago.

El chat del agente debe seguir siendo una interfaz de diagnóstico sin datos
individuales. La operación de cartera sí requiere una vista de ítems abiertos, pero
no debe convertir al modelo de lenguaje en una fuente de datos personales ni en un
ejecutor de cobros.

## Decisión

1. Las facturas canónicas y sus persistencias contienen `due_date` y
   `payment_terms_days`. La captura manual y la importación CSV/XLSX los aceptan. Los
   días permitidos son de `0` a `3650`; si sólo se reciben días, se deriva el
   vencimiento desde la expedición. Si se reciben ambos, se exige coherencia. Un
   vencimiento anterior a la expedición o términos distintos entre líneas de la misma
   factura invalida la entrada.
2. `ReceivablesService` calcula de forma determinista, por empresa y sólo para
   facturas `sale`, los saldos, pagos parciales/superiores, pagos en moneda distinta,
   vencimientos y antigüedad. Los saldos y cada bloque de antigüedad se mantienen
   separados por moneda; no se realiza conversión ni compensación entre monedas.
3. La antigüedad se clasifica contra `as_of` en `not_due`, `due_today`,
   `overdue_1_30`, `overdue_31_60`, `overdue_61_90`, `overdue_91_plus` y
   `missing_due_date`. Las facturas sin vencimiento se advierten, no se declaran
   vencidas.
4. El reporte incluye promedios de días de recaudo sólo para facturas liquidadas en
   moneda coincidente, y métricas derivadas del último seguimiento de cada ítem abierto
   (pendientes, promesas abiertas e incumplidas). Es un indicador operativo, no DSO
   certificado ni conciliación bancaria.
5. `POST /api/v1/companies/{company_id}/agents/receivables/chat` usa
   `VIEW_COMPANY_ROLES` y conserva el agente seleccionado durante la conversación.
   Expone sólo agregados, códigos de hallazgo y recomendaciones; nunca números de
   factura, clientes, documentos, datos de contacto o identificadores internos.
6. Antes de invocar opcionalmente al LLM, el agente clasifica y responde de forma
   determinista las consultas agregadas cubiertas por el reporte: prioridades y
   alertas, conteos de facturas abiertas/sin pago/con pago parcial o superior,
   vencimientos y antigüedad, saldos por moneda, fechas faltantes, pagos en moneda
   incompatible, facturas sin tercero, promedio de recaudo y estado de seguimientos o
   promesas. También puede explicar un hallazgo y recomendar una revisión operativa.
7. Una pregunta por factura, cliente, tercero, pago, número, consecutivo, referencia
   u otro dato individual se rechaza como fuera del alcance del chat, sin enviarse al
   LLM, y se orienta al canal operativo autorizado. Este límite aplica aunque el
   usuario conozca el identificador o formule la consulta como una pregunta de
   vencimiento.
8. El chat no crea ni modifica facturas, términos, pagos, seguimientos, promesas,
   comunicaciones ni cobros. Las solicitudes de escritura, ejecución o gestión se
   declaran fuera de alcance y se remiten a las rutas operativas con RBAC y
   confirmación explícita. Las consultas tributarias, jurídicas, crediticias, de
   conciliación, intereses, proyección de caja u otros módulos se limitan del mismo
   modo.
9. Si se solicita una métrica que el reporte no calcula, o no puede determinarse con
   los datos disponibles, el agente lo informa de forma transparente, no estima ni
   inventa cifras y, cuando aplica, expone el hallazgo agregado de calidad de datos y
   la revisión sugerida. En particular, los importes permanecen separados por moneda.
10. La vista individual queda aislada en
   `GET /api/v1/companies/{company_id}/receivables/open-items`, con paginación y una
   fecha de corte opcional. Puede ser leída por `owner`, `admin`, `operator` y
   `viewer` autorizados de la empresa.
11. La corrección de términos se limita a
   `PATCH /api/v1/companies/{company_id}/receivables/invoices/{invoice_id}/terms`.
   Exige empresa activa, rol `owner`, `admin` u `operator` y `confirmed: true`.
   Persiste el actor y la fecha de actualización; no modifica pagos ni genera cobros.
12. Los seguimientos viven en `collection_follow_ups`, separados del núcleo contable,
   con factura, empresa, actor de creación/actualización y marcas de tiempo. Las rutas
   `GET|POST /api/v1/companies/{company_id}/collection-followups` y
   `PATCH /api/v1/companies/{company_id}/collection-followups/{followup_id}` exigen
   lectura o escritura según el rol. Crear o actualizar exige `confirmed: true`,
   empresa activa y rol operativo. Los estados permitidos son `pending`,
   `contacted`, `promise_to_pay`, `resolved` y `cancelled`; una promesa requiere
   fecha prometida.
13. Las notas de seguimiento son resúmenes operativos opcionales de máximo 280
   caracteres. Se rechazan correos, cadenas numéricas directas y enlaces conocidos;
   esta barrera no sustituye una política DLP, por lo que no se permiten nombres,
   contactos, documentos, cuentas, credenciales ni instrucciones de cobro en la nota.
14. La narración LLM es opcional. Con `LLM_ENABLED=true` y una clave configurada,
    `OpenAIReceivablesNarrator` usa Responses API con `store: false`, identificador
    de seguridad HMAC, historial local acotado y un esquema JSON estricto. Sólo recibe
    una lista blanca de agregados y hallazgos, sin `company_id`, filas, clientes,
    documentos, correos, credenciales ni permisos. Sus respuestas se validan contra
    códigos de hallazgo existentes, se rechazan cifras libres y no pueden ejecutar
    acciones. Las entradas/salidas se redactan por patrones conocidos, sin afirmar que
    sea una solución DLP completa.
15. Cuando el LLM está deshabilitado, no configurado, falla o entrega una salida no
    válida, el agente responde con la conclusión determinista aplicable. Si el LLM
    estaba habilitado, conserva además la auditoría `degraded` con
    `LLM_UNAVAILABLE`; no responde como temporalmente no disponible ni inventa una
    interpretación. Las consultas ya resueltas localmente no invocan el LLM y se
    auditan como exitosas.
16. Cada ejecución de agente registra en `agent_executions` sólo actor, empresa,
    conversación, versión, estado, correlación, cantidad y códigos de hallazgo. No se
    guardan allí el mensaje, prompt, respuesta del modelo ni el reporte completo.

## Seguridad y activación de LLM

`store: false` se utiliza para evitar estado de aplicación de Responses, pero no es
por sí mismo una garantía de retención cero. La [documentación oficial de controles de
datos de OpenAI](https://developers.openai.com/api/docs/guides/your-data#default-usage-policies-by-endpoint)
describe los registros de monitoreo de abuso y los controles que requieren aprobación.
Antes de producción se debe revisar la elegibilidad, contrato, retención, aviso al
usuario y base legal aplicables. La clave API va únicamente en el gestor de secretos
del ambiente; nunca en código, archivos de ejemplo, auditorías, logs o tickets.

La activación exige: (a) `AUTH_SECRET_KEY` y una clave API gestionada de forma segura,
(b) `LLM_ENABLED=true` en `FEATURE_FLAGS`, (c) límites de modelo, tiempo y salida
acordes al ambiente, y (d) pruebas con datos no productivos para PII, solicitudes de
escritura, inyección de instrucciones, respuestas no ancladas y caída del proveedor.
El despliegue debe comenzar de manera gradual y vigilar las auditorías degradadas.

## Consecuencias

- La gestión de cartera queda trazable sin permitir que el chat revele ítems
  individuales ni que el modelo genere cobros, facturas o pagos.
- Los datos de vencimiento pueden llegar desde captura manual o archivos y las
  inconsistencias se detectan antes de persistirlas. Las facturas antiguas sin fecha
  seguirán apareciendo en una categoría explícita hasta su saneamiento.
- Los indicadores multimoneda son deliberadamente conservadores: la aplicación no
  suma ni cruza monedas y señala las relaciones de pago incompatibles para revisión.
- Las notas de seguimiento reducen la exposición de información sensible, pero su
  uso sigue sujeto a controles organizacionales, formación de usuarios y auditoría.
- La disponibilidad o calidad de la capa LLM no puede alterar hechos de cartera ni
  bloquear el diagnóstico determinista; el sistema comunica y audita la degradación.

## Pruebas

La cobertura integrada valida creación manual, CSV y XLSX con términos de pago,
derivación de vencimiento, valor cero válido, rechazo de incoherencias y trazabilidad
del actor. También cubre antigüedad multimoneda, ítems abiertos paginados, RBAC,
confirmación obligatoria para términos/seguimientos, estados y notas de seguimiento,
promesas incumplidas, auditoría sin identificadores personales y conversación LLM:
payload `store: false`, proyección agregada, respuesta estructurada anclada, bloqueo
de PII/escritura e indisponibilidad degradada.
