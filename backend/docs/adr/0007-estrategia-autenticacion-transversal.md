# ADR-0007: Estrategia de autenticación transversal para proveedores

- **Estado:** Propuesto (pendiente de revisión)
- **Fecha:** 2026-08-06
- **Fase:** 1 (spike de viabilidad — directrices; mecanismo de almacenamiento en fase de seguridad)
- **Categoría:** Seguridad de integraciones
- **Relacionados:** ADR-0001, ADR-0002, ADR-0003, ADR-0004, ADR-0005, `spike-fase1.md`

## Contexto

Cada proveedor autentica de forma distinta:

| Proveedor | Esquema | Credencial | Vigencia | Notas |
|---|---|---|---|---|
| Siigo | OAuth2 (password) → JWT | `username` + `access_key` + `Partner-Id` | token de acceso corto; access_key de larga duración | Credenciales por cuenta de empresa; regenerables desde el portal |
| Alegra | Basic Auth | `email` + `token` (base64) | token de larga duración | Regenerar token rompe integraciones activas |
| World Office Cloud | JWT propio | `token` API | **12 horas** | Renovación por UI o `gestionarTokenAPILicencia` |
| DIAN | WS-Security (`UsernameToken` o firma) + certificado digital | ID software + contraseña; certificado con NIT en `subject` | certificado con vigencia (años); contraseñas gestionadas | SOAP; MTOM/zip |

Un único "esquema de autenticación" es imposible. La estrategia transversal no es un mecanismo único, sino **una capa común de gestión, rotación, renovación y revocación** alrededor de mecanismos específicos por proveedor.

## Decisión

### 1. Capa común de gestión de credenciales

- Toda credencial de proveedor se gestiona desde un **SecretStore** (secreto por `company_id` + proveedor). El código de negocio **nunca** recibe la credencial en claro: la inyecta la capa de integración al construir el transporte.
- **Variables previstas por proveedor** (nombres a usar cuando exista almacenamiento; **no** se añaden al `.env.example` en esta fase, por decisión del usuario):
  - Siigo: `SIIGO_USERNAME`, `SIIGO_ACCESS_KEY`, `SIIGO_PARTNER_ID`, `SIIGO_BASE_URL`
  - Alegra: `ALEGRA_EMAIL`, `ALEGRA_TOKEN`, `ALEGRA_BASE_URL`
  - World Office: `WORLDOFFICE_CLOUD_API_TOKEN`, `WORLDOFFICE_BASE_URL`
  - DIAN: `DIAN_*` (ID software, contraseña de software, rutas de certificado/almacén y contraseña del certificado; nombres concretos en la fase de seguridad)

### 2. Modelo de tokens por proveedor

- **Siigo (OAuth2 → JWT):** obtener token con las credenciales; **renovación** con margen de caducidad (refrescar antes de expirar, evita la latencia de reintentos). El `access_key` no se expone nunca fuera del SecretStore.
- **Alegra (Basic):** credencial estática; el header se construye por request. La **rotación** (regenerar token en Alegra) se documenta como operación soportada y rompe la integración activa hasta actualizar el SecretStore.
- **World Office (JWT 12 h):** el token se obtiene/renueva periódicamente (UI o `gestionarTokenAPILicencia`). Dado el riesgo de caducidad, se exige **obtención bajo demanda con caché corta + renovación automática** y se registra en la matriz de riesgo.
- **DIAN (WS-Security + certificado):** `UsernameToken` (ID software + SHA-256 de la contraseña) y/o **firma XML con certificado digital** (clave privada protegida). El certificado se almacena cifrado; las contraseñas del software y del certificado se tratan como secretos de primer nivel.

### 3. Renovación, rotación y revocación (operativa)

- **Renovación:** automática para tokens de corta duración (Siigo JWT, WO 12 h) antes de expirar; reintentos con backoff ante 401/429.
- **Rotación:** regeneración periódica de secrets estáticos (Alegra token, DIAN contraseñas) mediante proceso operativo que actualiza el SecretStore sin downtime (doble escritura temporal si el proveedor lo permite).
- **Revocación:** si se detecta filtración, se revoca del lado del proveedor y se actualiza el SecretStore; la capa común debe permitir **invalidación forzosa por empresa** (fail-closed hasta nueva credencial).

### 4. Almacenamiento y cifrado

- SecretStore cifrado en reposo (fase de seguridad: p. ej. proveedor de secretos o variables cifradas con gestión de claves); **nunca en claro** en `.env`, código, tests ni logs.
- Regla transversal (ya vigente en el repo): **prohibido loggear secretos** (existe `test_secrets_in_logs.py` como precedente).

### 5. Aislamiento por empresa y límites

- Las credenciales y los límites de rate son **por empresa** (Siigo: 100 rpm por empresa; Alegra: 150 rpm por cuenta; WO: por token). El registry/factory de proveedores resuelve credencial + límites por `company_id` (refuerza ADR-0001 y la suite de cumplimiento, tests 5-7, 10).

## Consecuencias

Positivas:

- Los adaptadores no conocen el origen de las credenciales: reciben un transporte ya autenticado o un token del SecretStore.
- Rotación/renovación/revocación centralizadas y auditables.
- Cada proveedor mantiene su mecanismo nativo sin "forzar" un estándar artificial.

Negativas / trade-offs:

- Diversidad de mecanismos = más código de la capa común (aunque cada pieza es pequeña).
- World Office 12 h y certificados DIAN añaden complejidad operativa.
- La fase de seguridad debe definir el proveedor de SecretStore concreto (dependencia).

## Alternativas consideradas

| Alternativa | Por qué se descarta |
|---|---|
| Un único mecanismo estándar para todos (p. ej. solo OAuth2) | Imposible: DIAN y WO tienen esquemas propios obligatorios. |
| Guardar credenciales en variables de entorno del proceso | No escala multiempresa; sin rotación ni revocación granular; riesgo de exposición. |
| Sin SecretStore (credenciales por empresa en BD en claro) | Riesgo crítico; prohibido por la norma interna y por las buenas prácticas. |

## Madurez / Evidencia

- **M1 (validado documentalmente):** esquemas y vigencias confirmados por la documentación oficial de los cuatro proveedores (ver tabla y ADRs 0002-0005).
- Implementación del SecretStore y de la rotación: fase de seguridad.

## Referencias

- ADR-0001 (arquitectura de proveedores), ADR-0002 a 0005 (evidencia por proveedor)
- `backend/docs/spike-fase1.md` (matriz de riesgo de autenticación)
- Precedente en el repo: `test_secrets_in_logs.py` (no loggear secretos)
