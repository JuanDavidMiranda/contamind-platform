# ADR-0016: Cola persistente para sincronizaciones externas

- **Estado:** Aceptado
- **Fecha:** 2026-08-11
- **Fase:** Conectividad multi-proveedor
- **Relacionados:** ADR-0001, ADR-0008, ADR-0015

## Contexto

Una fuente puede tener miles de terceros y los proveedores externos aplican límites, tiempos de espera y fallos transitorios. Ejecutar la sincronización en la solicitud HTTP mantiene recursos ocupados durante un tiempo no acotado y hace que un reinicio del servidor deje el proceso sin visibilidad ni reanudación.

## Decisión

1. `POST /data-sources/{id}/sync/parties` crea un trabajo en `provider_sync_jobs` y responde `202 Accepted`; no realiza llamadas al proveedor.
2. La propia base de datos es la cola inicial. Cada trabajo conserva fuente, proveedor, cursor, conteos, intento, hora disponible y correlación, pero nunca payloads ni secretos.
3. `active_data_source_id` tiene una restricción única mientras el trabajo está activo. Así hay como máximo una sincronización encolada o en ejecución por fuente, incluso con varios procesos worker.
4. El worker independiente (`python -m app.workers.provider_sync_worker`, o `scripts/run-sync-worker.ps1`) reclama un trabajo mediante una actualización atómica y procesa una página. Si el cursor continúa, vuelve a encolarlo; si termina, libera la fuente para una nueva sincronización.
5. Cada reclamación tiene una concesión temporal. Si un worker se cae, otro puede recuperar el trabajo una vez vencida, sin perder el cursor confirmado.
6. `PROVIDER_RATE_LIMITED`, `PROVIDER_UNREACHABLE`, `PROVIDER_ERROR` y `SERVICE_UNAVAILABLE` se reintentan con espera exponencial limitada. Al agotar intentos, el trabajo falla y la fuente pasa a `failed`; los errores de autenticación o configuración no se reintentan.
7. Cada página conserva una corrida de auditoría en `provider_sync_runs`. El estado agregado del trabajo se consulta por sus rutas específicas.

## Consecuencias

- El servidor HTTP responde rápido y puede escalar por separado de los workers.
- El despliegue debe ejecutar al menos un worker o programar `run-sync-worker.ps1 --once`; sin él, los trabajos quedan correctamente en `queued`, pero no se consumen.
- Rotar o revocar credenciales cancela los trabajos activos de la fuente para impedir que se ejecuten con una configuración obsoleta.
- La implementación evita depender de Redis, Celery u otro servicio antes de necesitar sus capacidades operativas. Si el volumen lo exige, se puede sustituir el consumidor conservando el contrato de trabajo y el cursor.
