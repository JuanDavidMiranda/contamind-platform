# ContaMind Frontend

Cliente React para el agente de salud contable. Permite autenticar un usuario de ContaMind, elegir una empresa autorizada y conversar con el agente mientras muestra el reporte verificable de hallazgos y métricas.

## Desarrollo local

1. Inicia el backend de ContaMind en `http://localhost:8000`.
2. Copia `.env.example` como `.env` si necesitas cambiar la URL de la API.
3. Ejecuta `pnpm install` y luego `pnpm run dev` desde esta carpeta.

El frontend consume `POST /api/v1/companies/{company_id}/agents/accounting-health/chat`. El token de acceso se conserva solamente en memoria del navegador: se elimina al recargar o cerrar sesión.

No ingreses información personal, documentos de identidad ni credenciales en el chat. El agente es de solo lectura y está limitado a salud contable.
