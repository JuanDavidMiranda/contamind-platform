# Habilitación DIAN con software propio

Este módulo conecta a cada empresa con el ambiente oficial de **habilitación** de DIAN para facturación electrónica. Está diseñado para el modelo de software propio: la empresa es titular de su registro, certificado, software y pruebas. No activa producción ni reutiliza el piloto de consulta de adquirientes.

## Lo que hace

- Conserva por empresa el perfil fiscal, el rango de prueba, los estados y la trazabilidad de cada intento.
- Guarda `Software ID`, contraseña técnica, PFX y contraseña del PFX cifrados; las respuestas nunca devuelven esos valores.
- Recibe un ZIP con un único UBL ya firmado, cifra el XML y el ZIP en reposo y valida antes de encolarlo: tipo documental, `ProfileExecutionID=2`, consecutivo, fecha, moneda, total, NIT emisor, presencia de firma/certificado y política XAdES. Esta validación previa no sustituye la validación criptográfica y de esquema que realiza DIAN.
- Transmite la prueba mediante `SendTestSetAsync` a `https://vpfe-hab.dian.gov.co/WcfDianCustomerServices.svc` y consulta el resultado con `GetStatusZip` desde un worker separado.
- Si DIAN no confirma un envío, o si el worker pierde el lease durante un envío, el documento queda en revisión manual. El sistema no lo reenvía automáticamente. Solo después de un rechazo definitivo de DIAN puede cargarse una corrección vinculada con el mismo prefijo y consecutivo.

## Lo que permanece bloqueado

- Producción, numeración de operación y emisión comercial.
- Generación autónoma desde las facturas contables actuales: el documento de habilitación se carga ya firmado mientras se completa el generador UBL 1.9 y sus validaciones de negocio.
- El portal MUISCA y cualquier automatización de su inicio de sesión. Es un portal humano, no un API de integración.

No anuncies el producto como facturación electrónica productiva hasta que la empresa supere su set asignado y se implemente el flujo de operación correspondiente.

## Datos que debe aportar cada empresa

La persona titular debe obtenerlos en el portal oficial y cargarlos únicamente por la pantalla protegida de Habilitación DIAN:

1. Perfil fiscal de la empresa y NIT con dígito de verificación.
2. `Software ID`, contraseña técnica, certificado de firma PFX vigente y su contraseña.
3. `TestSetId` asignado por DIAN, política de firma vigente y su hash SHA-256 en Base64.
4. Rango de numeración de habilitación vigente.
5. ZIPs UBL 2.1 firmados para el set que DIAN asigne.

No se deben pegar PFX, claves, PIN ni contraseñas en el chat, tickets, repositorio o archivos `.env`.

## Operación del ambiente

1. Ejecuta la migración `b9f1a7d3e4c2` junto con las migraciones anteriores.
2. Mantén `DIAN_ELECTRONIC_HABILITATION_ENABLED=false` hasta que el perfil de la empresa esté completo y se vaya a realizar una prueba acompañada. Esta bandera es distinta de `DIAN_INTEGRATION_ENABLED`, usada por el piloto de consulta de adquirientes.
3. Habilita solo ese flag en el entorno de habilitación. La pila `compose.beta.local.yml` inicia y supervisa automáticamente `dian-habilitation-worker`; para una ejecución fuera de Docker, usa:

   ```powershell
   Set-Location backend
   .\.venv\Scripts\python.exe -m app.workers.dian_electronic_worker
   ```

4. En **Facturación electrónica → Habilitación DIAN**, registra el perfil, las credenciales técnicas, el rango y carga una prueba. Revisa los eventos hasta que DIAN la acepte o rechace.
5. Si aparece `manual_review` o `DIAN_SUBMISSION_UNKNOWN`, consulta el portal de habilitación antes de tomar cualquier decisión. Nunca cambies el estado ni cargues otra versión con ese consecutivo. Si DIAN marca el documento como `rejected`, puedes cargar una corrección trazable con el mismo consecutivo; el aplicativo conserva el vínculo con el rechazo original.
6. Al terminar la prueba, vuelve a desactivar el flag si no existe operación supervisada.

El worker debe ejecutarse como proceso supervisado y único por despliegue. Puede haber más de un worker solo cuando se coordine su cola en PostgreSQL y se monitoreen los leases.

## Referencias oficiales

- [Documentación técnica de facturación electrónica](https://micrositios.dian.gov.co/sistema-de-facturacion-electronica/documentacion-tecnica/)
- [Anexo Técnico de Factura Electrónica de Venta v1.9](https://www.dian.gov.co/impuestos/factura-electronica/Documents/Anexo-Tecnico-Factura-Electronica-de-Venta-vr-1-9.pdf)
- [Guía para consumo de Web Services](https://www.dian.gov.co/impuestos/factura-electronica/Documents/Guia-Herramienta-para-el-Consumo-de-Web-Services.pdf)
- [Proceso de registro y habilitación](https://micrositios.dian.gov.co/sistema-de-facturacion-electronica/proceso-de-registro-y-habilitacion-como-facturador-electronico/)

El set y sus cantidades se deben tomar del portal asignado a cada empresa; no se codifican en el aplicativo porque DIAN puede actualizarlos.
