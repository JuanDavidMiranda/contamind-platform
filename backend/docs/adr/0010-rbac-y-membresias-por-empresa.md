# ADR-0010: RBAC y membresías por empresa

- **Estado:** Aceptado
- **Fecha:** 2026-08-10
- **Fase:** 2 (ingesta y conectividad)
- **Relacionados:** ADR-0006, ADR-0009

## Contexto

Las fuentes de datos, los perfiles de importación y los terceros pertenecen a una empresa canónica. Un mismo usuario puede colaborar con varias empresas y no debe poder consultar, importar ni capturar información fuera de aquellas a las que fue asignado. El indicador global `is_platform_admin` no expresa ese alcance y no sirve para la operación diaria de los clientes.

## Decisión

Se incorpora `CompanyMembership`, que relaciona un `User` con un `company_id` canónico y uno de estos roles:

| Rol | Fuentes | Importación y captura manual | Membresías |
|---|---|---|---|
| `owner` | Configura y consulta | Opera | Gestiona |
| `admin` | Configura y consulta | Opera | No |
| `operator` | Consulta | Opera | No |
| `viewer` | Consulta | No | No |

El administrador de plataforma conserva un bypass explícito para soporte y para asignar el primer propietario de una empresa. No se incluyen roles de empresa dentro del JWT: cada solicitud consulta la membresía vigente en la base de datos, por lo que un cambio o revocación tiene efecto inmediato.

Las rutas de fuentes están bajo `/api/v1/data-sources`; la ruta anterior `/api/v1/admin/data-sources` se conserva temporalmente como alias no documentado. En las operaciones que reciben una fuente por ID, el servidor resuelve primero su empresa y aplica el permiso sobre ella. La captura manual recibe solo datos del tercero: el `company_id` y la fuente se derivan en el servidor, con lo que el cliente no puede redirigir el registro a otra empresa.

## Consecuencias

- Los usuarios no administradores pueden trabajar con las fuentes de sus empresas sin recibir privilegios globales.
- Un operador puede importar archivos y crear/actualizar terceros en una fuente manual; no puede cambiar conectores ni perfiles.
- La configuración inicial requiere un administrador de plataforma que asigne un `owner`; después ese propietario puede administrar las membresías de su empresa.
- La tabla de empresas todavía no es local porque su identidad canónica puede provenir de distintas fuentes. `CompanyMembership.company_id` mantiene el UUID usado por fuentes y terceros; cuando exista una tabla de empresas, se añadirá la clave foránea sin cambiar el contrato de autorización.
