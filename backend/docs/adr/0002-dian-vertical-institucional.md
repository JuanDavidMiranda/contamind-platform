# ADR-0002: DIAN como vertical institucional y selección del primer vertical real

- **Estado:** Propuesto (pendiente de revisión)
- **Fecha:** 2026-08-06
- **Fase:** 1 (spike de viabilidad)
- **Categoría:** Vertical DIAN / FiscalProviderPort
- **Relacionados:** ADR-0001, `spike-fase1.md`

## Contexto

La DIAN es la autoridad fiscal de Colombia. ContaMind hoy tiene un flujo de "exógena" como workflow de chat y un agente DIAN dormido. Para el spike se evaluó qué capacidades públicas y autenticadas ofrece la DIAN, qué operaciones están confirmadas, pendientes o inviables, y cuál debe ser el **primer vertical DIAN real**.

## Investigación (evidencia del 2026-08-06)

### 1. Facturación electrónica (validación previa) — completa, alta complejidad
- Web services **SOAP 1.2 / WSDL 1.1**, comunicación HTTPS, WS-Security.
- Autenticación: `UsernameToken` (identificador del software + SHA-256 de la contraseña del software) y **certificado digital** para validación previa (certificado de "Pertenencia empresa", NIT en `subject`).
- Flujo **asíncrono**: envío (`SendTestSetAsync`/`SendBillAsync`) → `trackId` → consulta de estado (`GetStatusAsync`), en ambiente de habilitación primero.
- Adjuntos comprimidos **MTOM** (ZIP) con el XML del documento.
- Cobertura: facturas, notas débito/crédito, documento soporte, eventos; requiere numeración, firma, estados e idempotencia propios.
- **Conclusión:** es el vertical de mayor valor fiscal pero implica habilitación, firma, numeración, documentos, eventos, estados e idempotencia. **Merece una fase propia** y no debe ser el primer vertical.

### 2. GetAcquirer (consulta de información del adquiriente) — real, acotada, ideal como piloto
- Regulado por la **Resolución 000202 del 31 de marzo de 2025** (modifica arts. 69-70 de la Res. 165 de 2023). Disponible desde la segunda semana de abril de 2025 para software propio y proveedores tecnológicos.
- Servicio SOAP (`IWcfDianCustomerServices/GetAcquirer`) que, dado **tipo** y **número** de documento, completa del adquiriente: **nombre/razón social** y **correo electrónico** para la factura.
- Autenticación: WS-Security **Signature + Timestamp** + autenticación básica + **certificado digital** vigente.
- Tipos de documento permitidos: 11, 12, 13, 21, 22, 31, 41, 42, 47, 48, 50, 91.
- Base de datos: registros de adquirientes 2023-2024. En ambiente de **habilitación** solo devuelve las tablas de prueba predefinidas; en **producción** consulta la base real.
- Restricciones normativas: uso **exclusivo** para la emisión de FEV/DEE; prohibido el **uso masivo** o distribución (art. 4, Res. 000202/2025); consulta uno-a-uno controlada.
- Header obligatorio en implementación propia: `Content-Type: action="http://wcf.dian.colombia/IWcfDianCustomerServices/GetAcquirer"`.
- Advertencia comunitaria (foro de integradores): la respuesta puede ser "errática" según los datos; nunca usar como fuente general de datos de terceros.

### 3. Exógena — sin API pública (portal/archivos)
- La exógena se entrega por el **portal MUISCA** mediante archivos (formatos 2276 y relacionados). No existe un web service público de transmisión de exógena.
- **Conclusión:** permanece como **flujo de preparación de archivos y asistencia** (lo que ya hace el workflow de chat), no como integración por web service.

### 4. RUT / consulta de NIT
- Existen servicios de consulta/validación de NIT, pero **no** deben confundirse con `GetAcquirer` ni usarse para inferir responsabilidades, régimen ni estado tributario. Requiere confirmación de disponibilidad y credenciales en la fase de implementación.

## Decisión

1. **Primer vertical DIAN real = `GetAcquirer` (consulta de adquirientes) como piloto SOAP controlado**, bajo estas condiciones:
   - Confirmar que el servicio sigue disponible y documentado en el ambiente aplicable (habilitación/producción).
   - Confirmar habilitación y credenciales (software activado + certificado digital o credenciales de habilitación).
   - Confirmar que el uso corresponde al caso funcional de la plataforma (completar datos del comprador en facturación).
   - **No** presentarlo como validación general de RUT ni inferir responsabilidades, régimen o estado tributario desde su respuesta.
   - El piloto debe validar de forma controlada: construcción del cliente SOAP, contratos XML, autenticación, WS-Security, timeouts, manejo de errores DIAN, sanitización, auditoría, mapeo a modelos internos, y pruebas mock y live.

2. **Facturación electrónica completa (validación previa): fase propia posterior**, no el primer vertical.

3. **Exógena:** flujo de preparación de archivos y asistencia; sin integración web service.

4. **Diseño:** DIAN se implementa bajo el `FiscalProviderPort` (ADR-0001), separado de los sistemas financieros. Modelo canónico de tercero comparte el canónico general (ADR-0006) pero el adaptador DIAN solo expone lo que el servicio autoriza (nombre/razón social + correo, sin datos prohibidos).

## Consecuencias

Positivas:

- El piloto `GetAcquirer` valida la columna vertebral técnica SOAP/WS-Security con alcance acotado.
- Se respeta la norma (uso exclusivo para facturación, sin uso masivo).
- La facturación electrónica se aborda cuando exista credenciales de habilitación y una fase dedicada.

Negativas / trade-offs:

- `GetAcquirer` por sí solo no aporta valor de negocio aislado; su valor es habilitar la facturación electrónica.
- Requiere certificado digital y credenciales de habilitación (bloqueador).
- Riesgo de respuestas erráticas del servicio (documentado como riesgo).

## Madurez / Evidencia

- **M1 (validado documentalmente):** `GetAcquirer` confirmado por guías oficiales DIAN y Res. 000202/2025. Facturación electrónica documentada (anexo técnico, guía de consumo de web services). Exógena clasificada como portal/archivos.
- **M0:** para las URLs/ambientes exactos de habilitación del `GetAcquirer` (la URL del WS se publica en el catálogo de participante del facturador), que se confirmarán con credenciales.

## Referencias

- DIAN — Guía herramienta para el consumo de web services (PDF, dian.gov.co)
- DIAN — Paso a paso servicio de consulta para completar la información (PDF)
- DIAN — Resolución 000202 del 31 de marzo de 2025 (modifica arts. 69-70 Res. 165/2023)
- DIAN — Comunicado de prensa 026 (2025-04-01)
- Anexo técnico Factura Electrónica de Venta v1.9 y caja de herramientas
