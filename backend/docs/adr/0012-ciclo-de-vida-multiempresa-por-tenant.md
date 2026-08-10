# ADR-0012: Ciclo de vida multiempresa por tenant

- **Estado:** Aceptado
- **Fecha:** 2026-08-10
- **Fase:** 2 (multiempresa)
- **Relacionados:** ADR-0010, ADR-0011

## Contexto

El onboarding crea una primera empresa, pero un despacho, grupo empresarial o cliente con varias razones sociales necesita crear más empresas dentro del mismo tenant. La pertenencia a una empresa no debe por sí sola otorgar el poder de crear otras empresas ni de desactivar una razón social completa.

## Decisión

Se introduce `TenantMembership` con el rol `owner`. El onboarding asigna este rol al creador del tenant. Solo ese propietario —o un administrador de plataforma— puede usar `POST /api/v1/tenants/{tenant_id}/companies` para crear otra empresa. El creador recibe automáticamente una membresía `owner` de la nueva empresa.

Una empresa tiene estado `active` o `disabled`:

| Acción | Autorización |
|---|---|
| Crear empresa en tenant | `tenant owner` |
| Editar datos básicos | `company owner` o `tenant owner` |
| Desactivar / reactivar | `tenant owner` |
| Configurar, importar o capturar datos | Empresa activa y permiso de empresa |
| Consultar empresa y auditoría | Cualquier miembro de la empresa |

No existe eliminación de empresas. La desactivación conserva fuentes, terceros, importaciones y su trazabilidad, pero bloquea nuevas operaciones sobre sus fuentes hasta que se reactive.

`GET /api/v1/companies/{company_id}/audit` entrega las fuentes creadas, lotes de importación y terceros de captura manual, junto con sus referencias de autor y fechas. No entrega secretos, contenido de archivos ni datos de credenciales.

## Consecuencias

- Un tenant owner puede gestionar varias razones sociales de forma explícita y auditable.
- Los operadores continúan limitados a las empresas donde recibieron membresía, incluso si comparten tenant.
- Los propietarios de tenant acceden a todas sus empresas, incluida una creada por otro propietario.
- La reactivación es deliberada; una empresa desactivada no puede volver a ingerir datos por accidente.
