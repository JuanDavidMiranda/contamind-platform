# ADR-0011: Empresas persistidas y onboarding transaccional

- **Estado:** Aceptado
- **Fecha:** 2026-08-10
- **Fase:** 2 (multiempresa)
- **Relacionados:** ADR-0006, ADR-0009, ADR-0010

## Contexto

Las fuentes y las membresías ya se autorizan por `company_id`, pero ese identificador podía llegar como un UUID sin una empresa persistida. Esto impedía ofrecer un onboarding completo, listar las empresas disponibles para un usuario y garantizar la integridad entre tenant, empresa, fuentes y membresías.

## Decisión

Se persisten `TenantRecord` y `CompanyRecord`, manteniendo los contratos canónicos `Tenant` y `Company` como representación de dominio. El endpoint `POST /api/v1/companies/onboarding` crea, en una sola transacción:

1. el tenant;
2. su primera empresa;
3. una membresía `owner` para el usuario autenticado.

`GET /api/v1/companies/mine` devuelve solo las empresas a las que el usuario tiene acceso. El administrador de plataforma las puede consultar todas para soporte. Las APIs de fuentes verifican que la empresa exista y que corresponda al tenant enviado; las APIs de membresías rechazan empresas inexistentes.

La migración crea las entidades y conserva los datos previos: si encuentra fuentes, lotes, terceros o membresías sin empresa persistida, genera registros marcados como migrados antes de activar las llaves foráneas.

## Auditoría de operaciones

Se registran referencias de usuario en:

| Recurso | Campos |
|---|---|
| Fuente de datos | `created_by_user_id` |
| Lote de importación | `created_by_user_id` |
| Tercero | `created_by_user_id`, `updated_by_user_id` |

La autoría se obtiene del token autenticado y se pasa a los casos de uso; no se acepta desde el cliente. Esto cubre tanto importaciones como captura manual.

## Consecuencias

- El flujo de una nueva empresa es autocontenido y deja un propietario listo para gestionar su acceso.
- Las referencias de empresa dejan de depender de UUIDs no validados.
- El historial puede atribuir la creación de cada fuente, lote y tercero a un usuario concreto.
- La siguiente ampliación será permitir a los propietarios crear empresas adicionales dentro de un tenant existente y exponer el historial de auditoría en la interfaz.
