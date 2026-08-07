# ADR-0005: Evaluación World Office — integración por modalidad de producto

- **Estado:** Propuesto (pendiente de revisión)
- **Fecha:** 2026-08-06
- **Fase:** 1 (spike de viabilidad)
- **Categoría:** Evaluación de proveedor financiero
- **Relacionados:** ADR-0001, ADR-0006, ADR-0007, `spike-fase1.md`

## Contexto

World Office es un sistema contable colombiano con dos familias de producto (Cloud/Enterprise y local). La integración **depende de la modalidad de instalación** de cada cliente; no existe un mecanismo único de integración. Este ADR clasifica las modalidades y define cómo se resuelve cada una dentro de la arquitectura (ADR-0001).

## Investigación (evidencia del 2026-08-06, documentación oficial World Office)

### Modalidades del producto
1. **Cloud (Enterprise SaaS):** plataforma multiusuario en la nube de World Office.
2. **On-premise / local:** instalaciones en servidores del cliente (clásico World Office en escritorio o en servidor propio).
3. **Modalidades híbridas / archivos:** intercambio por archivos planos o conectores.

### API oficial (solo Cloud / Enterprise)
- Base URL: `https://api.worldoffice.cloud/api`.
- Secciones documentadas: **Terceros, Ventas, Compras, Inventarios, Contabilidad, Carteras-Recaudos y Cuentas por Pagar**.
- Endpoints representativos:
  - `terceros/listarTerceros`
  - `ventas/documentos` / `ventas/getDocumentoVenta`
  - `compras/listarDocumentoCompra`
  - `documentos/getDocumentoId`
  - Contabilidad: asientos/comprobantes.
- Respuesta típica con estructura `{"datos": [...], "codigoRespuesta": ...}` y paginación por rangos.

### Autenticación (Cloud)
- Token **JWT con vigencia de 12 horas** obtenido de dos formas:
  1. **UI:** Configuración → General → API → "Generar token".
  2. **Servicio/licencia:** método `gestionarTokenAPILicencia` (se recomienda como opción; el proceso por licencia requiere verificar con el proveedor).
- Header de autorización: `Authorization: WO <token>`.
- El token se renueva manualmente o por rotación programática (máx. vigencia 12 h).

### Límites y documentación
- La sección "Límites de request" existe en la documentación pero **aparece con valores placeholder** (sin números confirmados). Se tratará como desconocido y se validará con credenciales reales.

### On-premise / local — sin API oficial
- No hay API oficial pública para instalaciones locales en las fuentes revisadas.
- Mecanismos alternativos documentados para esta modalidad:
  1. Conector desarrollado/validado por el OEM o integradores autorizados.
  2. Acceso autorizado a la **base de datos** (SQL) para lectura.
  3. Intercambio por **archivos planos / formatos** (import/export).
  4. Agente local / servicios de escritorio dentro de la red del cliente.

## Decisión

1. **No modelar World Office como un adaptador único.** Se clasifica por modalidad de instalación:
   - `WORLDOFFICE_CLOUD_API` → implementación del `FinancialProviderPort` vía la API REST oficial (JWT 12 h).
   - `WORLDOFFICE_ON_PREMISE` → **sin API oficial**: se resuelve con conector OEM autorizado, acceso a BD de solo lectura, archivos planos o agente local; NO se implementa como adaptador REST (riesgo alto; requiere análisis de seguridad y soporte del proveedor).
   - `WORLDOFFICE_FILE_EXCHANGE` → integración por archivos (formato específico) con preparación/asistencia.
   - `WORLDOFFICE_LOCAL_AGENT` → agente/servicio en la red del cliente (requiere diseño de despliegue y seguridad).
2. **Solo la modalidad `CLOUD_API` es candidata al primer adaptador financiero**, y queda **por debajo** de Siigo/Alegra en prioridad (menor madurez documental de límites y dependencia de renovación manual del token).
3. **Nombres previstos** de variables de credenciales (solo se documentan aquí; **no** se añaden al `.env.example` en esta fase):
   - `WORLDOFFICE_CLOUD_API_TOKEN`
   - `WORLDOFFICE_BASE_URL` (default `https://api.worldoffice.cloud/api`)
   - Para modalidades on-premise/local: variables de conexión a definir en la fase de seguridad según el mecanismo.
4. En la matriz comparativa se marca **dependencia comercial alta**: la renovación de token (12 h), los límites no confirmados y la falta de API para on-premise dependen del proveedor.

## Consecuencias

Positivas:

- La clasificación por modalidad evita diseñar un adaptador multimodal inviable.
- Cloud API permite evaluación real con token de 12 h (M3) si se obtienen credenciales.
- On-premise queda documentado como caso especial, no como adaptador estándar.

Negativas / trade-offs:

- Alta dependencia del proveedor (límites placeholder, renovación manual del token, ausencia de API on-premise).
- On-premise no es "adaptador": requiere un mecanismo distinto con análisis de seguridad (BD/red) antes de la Fase 2.
- El token de 12 h sin rotación automática documentada añade complejidad operativa.

## Madurez / Evidencia

- **M1 (validado documentalmente):** existencia de API Cloud, token JWT 12 h (`gestionarTokenAPILicencia` / UI), base URL, endpoints y secciones documentadas confirmados en la documentación oficial.
- **M0:** valores de límites (placeholder) y renovación programática del token sin confirmar; se validarán con credenciales reales (M3).

## Referencias

- World Office — documentación API: devapidoc.worldoffice.cloud (Introducción, Autenticación, Límites, secciones Terceros/Ventas/Compras/Inventarios/Contabilidad/Carteras-Recaudos/Cuentas por Pagar)
- World Office — Configuración General → API (generación de token)
