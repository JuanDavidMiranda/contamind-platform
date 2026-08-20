# Guía de beta privada de ContaMind

Esta versión está preparada para una **beta privada y acompañada**, no para una beta pública ni para operación productiva. El objetivo es que un primer cliente pueda cargar información propia y comprobar el valor de los diagnósticos, cartera, cuentas por pagar, flujo de caja, conciliación y tesorería con revisión humana.

## Alcance que sí se puede probar

- Alta controlada de una persona usuaria por un administrador de plataforma.
- Cambio obligatorio de la contraseña temporal antes de cualquier operación; al cambiarla se invalidan las sesiones previas.
- Creación autónoma de la primera empresa del cliente en COP, USD o EUR.
- Carga guiada mediante CSV UTF-8 de terceros, facturas de venta/compra y pagos registrados.
- Diagnósticos deterministas, separados por moneda, para salud contable, cartera, obligaciones, flujo de caja, conciliación y tesorería.
- Confirmación humana para correcciones operativas y conciliación bancaria.
- Habilitación DIAN por empresa, únicamente para enviar y seguir documentos de prueba ya firmados al set oficial, con producción bloqueada.

## Límites que deben comunicarse antes de invitar al cliente

- No emite facturas comerciales en producción ni habilita rangos de operación. La conexión DIAN disponible se limita al ambiente de habilitación y requiere el registro, certificado y set oficial propios de cada empresa.
- No genera ni presenta archivos oficiales de información exógena.
- No programa pagos, no se conecta a bancos en línea y no autoriza transferencias.
- La consulta DIAN `GetAcquirer` es un piloto controlado y debe permanecer deshabilitada hasta tener habilitación, URL y credenciales autorizadas.
- El chat no debe recibir NIT, documentos, correos, contraseñas ni certificados. La carga de archivos se usa únicamente en las vistas operativas autorizadas.

## Preparación segura del ambiente

1. Para el backend, copia `backend/.env.beta.example` a un archivo `.env` **fuera del repositorio** y completa todos los campos vacíos desde el gestor de secretos. En `staging` y `production` la aplicación rechaza el arranque si faltan la base de datos, administrador, secretos, CORS HTTPS, flags explícitos o si `DEBUG`/mocks están activos.
2. Para el frontend, copia `frontend/.env.beta.example` y asigna la URL HTTPS pública del backend a `VITE_API_BASE_URL`. `VITE_REQUIRE_API_URL=true` hace que la compilación de beta falle si se omite esa URL.
3. Provisiona una base PostgreSQL exclusiva para la prueba; no reutilices la base de desarrollo ni datos de otros clientes.
4. Ejecuta las migraciones antes de iniciar el backend:

   ```powershell
   Set-Location backend
   .\scripts\migrate.ps1
   ```

5. Crea el primer administrador sin utilizar los scripts de datos de demostración:

   ```powershell
   Set-Location backend
   .\.venv\Scripts\python.exe scripts\provision_platform_admin.py --email operador@tu-dominio.example --full-name "Operador ContaMind"
   ```

   El script solicita una contraseña de forma oculta y nunca la imprime. El correo debe estar también en `PLATFORM_ADMIN_EMAILS`.

## Recorrido de prueba para el cliente

1. El administrador entra en **Accesos de beta**, crea la cuenta del cliente con una contraseña temporal robusta y la comparte por un canal seguro.
2. La persona invitada inicia sesión y usa **Cambiar contraseña** antes de cargar datos.
3. Si todavía no tiene una empresa, completa el formulario de creación de empresa. Queda como propietaria de ese espacio y la beta permite una empresa por acceso.
4. En **Carga inicial**, descarga y completa las plantillas en este orden:

   - `plantilla-terceros-beta.csv`
   - `plantilla-facturas-beta.csv`
   - `plantilla-pagos-beta.csv`

   Conserva los encabezados y usa fechas `AAAA-MM-DD`, `sale` para ventas y `purchase` para compras. Los importes no deben llevar separadores de miles. En una venta registra el cliente en `Documento receptor`; en una compra, el proveedor en `Documento emisor`. Cada pago necesita su tipo de factura y una `Referencia de pago` única. Esos terceros deben existir previamente en la misma empresa.

5. Tras cada carga, revisa filas aceptadas y rechazadas; si hay errores, descarga el informe de rechazos. Los terceros con el mismo documento se actualizan. Para evitar duplicados, una factura o pago ya aceptado se reporta y no se reemplaza automáticamente; su corrección requiere el flujo asistido de soporte de la beta. El sistema conserva el resultado de cada carga para auditoría, no una copia completa del archivo.
6. Abre **Salud contable**, **Cartera**, **Cuentas por pagar**, **Flujo de caja** y **Tesorería** para validar las señales generadas. Para tesorería, importa un extracto y registra un corte de saldo bancario verificado antes de tomar decisiones de pagos.

## Gates antes de exponerla por Internet

No se debe abrir la beta a Internet hasta completar estos controles operativos:

- Desplegar backend, frontend y worker de sincronización como procesos supervisados, con health checks y reinicio controlado.
- Configurar HTTPS, `TrustedHost`, límites de solicitud, protección de documentación de API y monitoreo de errores.
- Definir copias de seguridad, restauración probada y retención de datos para la base PostgreSQL.
- Ejecutar migraciones y un smoke test en una base PostgreSQL vacía; las pruebas rápidas de desarrollo usan SQLite y no sustituyen ese paso.
- Actualizar y revisar las dependencias de construcción del frontend antes de publicar un entorno público.
- Mantener las integraciones externas y las funciones DIAN en `false` hasta superar sus pruebas de habilitación y seguridad.

La guía específica de esta integración está en [Habilitación DIAN con software propio](dian-habilitacion-software-propio.md).

Para una prueba local reproducible ya existe [la guía de operación con Docker](../deploy/beta/README.md). No publica puertos fuera del equipo y no sustituye los controles anteriores.

## Verificación del código antes de una demo

```powershell
Set-Location backend
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check app tests scripts

Set-Location ..\frontend
pnpm run lint
pnpm exec tsc --noEmit
pnpm test
```

La prueba de PostgreSQL y las migraciones en una base limpia son obligatorias antes de cualquier despliegue externo.
