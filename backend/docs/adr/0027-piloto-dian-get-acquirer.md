# ADR-0027: Piloto DIAN GetAcquirer con consulta individual auditada

- **Estado:** Implementado; pendiente de validación controlada en habilitación
- **Fecha:** 2026-08-19
- **Relacionados:** ADR-0001, ADR-0002, ADR-0007

## Decisión

ContaMind implementa `GetAcquirer` como el primer adaptador fiscal DIAN. Se conserva fuera de los agentes conversacionales y de la sincronización de terceros: se expone como una operación individual, explícitamente confirmada y limitada al propósito `electronic_invoice_issuance`.

La integración usa una fuente por empresa de tipo `fiscal_authority` y modo `fiscal_service`, con `provider_id=dian`. Los campos `software_id`, `software_password`, `certificate_pfx_base64` y `certificate_password` se guardan exclusivamente en el almacén cifrado de secretos. El adaptador carga el PKCS#12 en memoria, valida que esté vigente y genera el mensaje SOAP 1.2 descrito en la guía: Basic Auth, `wsa:Action`, `wsa:To` firmado, `BinarySecurityToken`, firma RSA/SHA-256, canonicalización exclusiva, digest SHA-256 y `Timestamp` de 60 segundos con milisegundos. Aplica además el `Content-Type` con la acción `IWcfDianCustomerServices/GetAcquirer` requerida por DIAN.

La operación es:

`POST /api/v1/companies/{company_id}/dian/acquirers/lookup`

Solo acepta los tipos documentales DIAN autorizados, un número de documento de formato acotado, el propósito fijo de emisión y `confirmed: true`. No acepta listas, archivos ni llamadas desde chat. Requiere una empresa activa y rol `owner`, `admin` u `operator`.

## Datos y auditoría

La respuesta efímera se limita a nombre/razón social y correo. No se persiste la respuesta, el XML SOAP, el certificado, las contraseñas ni el número de documento. La tabla `dian_acquirer_lookups` conserva el actor, la empresa, la fuente, el tipo de documento, el resultado, el código de fallo, correlación y un HMAC del número consultado para trazabilidad sin revelar el valor.

## Límites y activación

`DIAN_INTEGRATION_ENABLED` sigue apagado por defecto. Para una prueba se debe registrar el software en DIAN, obtener habilitación y certificado de pertenencia vigente, configurar `DIAN_ACQUIRER_URL` con la URL HTTPS expuesta en `Participants > Facturador` y ejecutar primero pruebas controladas de contrato, seguridad, respuesta y error. La URL WSDL puede cargarse tal como aparece en el catálogo; el adaptador usa el endpoint `.svc` para la operación. No se habilita producción ni facturación electrónica completa con este cambio.

GetAcquirer no es consulta de RUT ni mecanismo de enriquecimiento de bases de datos. La información obtenida solo puede utilizarse para la generación de la factura, de uno en uno, conforme a la Resolución 000202 de 2025.

## Referencias

- [Guía para el consumo de Web Services](https://www.dian.gov.co/impuestos/factura-electronica/Documents/Guia-Herramienta-para-el-Consumo-de-Web-Services.pdf)
- [Documentación técnica de facturación electrónica](https://micrositios.dian.gov.co/sistema-de-facturacion-electronica/documentacion-tecnica/)
- [Resolución 000202 de 2025](https://normograma.dian.gov.co/dian/compilacion/docs/resolucion_dian_0202_2025.htm)
