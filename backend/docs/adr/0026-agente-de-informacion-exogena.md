# ADR-0026 — Agente de preparación de información exógena

**Fecha:** 2026-08-18
**Estado:** aceptado

## Contexto

La información exógena exige datos contables y de terceros consistentes, pero
las obligaciones, formatos, conceptos y plazos dependen de la normativa vigente
y de las características concretas de cada obligado. El producto no contaba con
una parametrización normativa verificable para decidir esas condiciones ni con
un mecanismo autorizado para generar o presentar archivos ante la DIAN.

## Decisión

Se incorpora un agente determinista de solo lectura disponible en:

`POST /api/v1/companies/{company_id}/agents/exogenous-information/chat`

El agente recibe un año gravable opcional desde la pregunta —o usa el año actual—
y analiza preparación de datos agregada:

- identificación, ciudad y dirección de terceros registrados;
- consecutivo, contraparte y consistencia de total de facturas del año;
- pagos del año sin factura vinculada.

La vista protegida `GET /companies/{company_id}/exogenous-information/exceptions`
devuelve los casos pendientes por año gravable a usuarios con acceso de lectura.
No muestra nombre, documento, correo, dirección, importes ni referencias de un
tercero; solo el tipo de registro, una etiqueta segura, fecha cuando corresponde
y códigos de corrección.

## Límites

La primera versión no decide si una empresa está obligada a reportar, no infiere
formatos, conceptos, fechas ni plazos DIAN, y no sustituye la revisión de un
responsable tributario. No genera, firma, transmite, carga ni presenta archivos
oficiales y no consulta servicios de la DIAN.

## Consecuencias

La empresa puede corregir tempranamente faltantes de su información fuente sin
recibir una falsa garantía de cumplimiento. Una etapa posterior deberá incorporar
una base normativa versionada y revisada, determinación explícita de obligación,
parametrización por año gravable y mecanismos de preparación de archivos con
controles, aprobación humana y pruebas reguladas.
