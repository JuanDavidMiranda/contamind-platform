import assert from "node:assert/strict";
import { access, readFile } from "node:fs/promises";
import test from "node:test";

async function render() {
  const workerUrl = new URL("../dist/server/index.js", import.meta.url);
  workerUrl.searchParams.set("test", `${process.pid}-${Date.now()}`);
  const { default: worker } = await import(workerUrl.href);

  return worker.fetch(
    new Request("http://localhost/", { headers: { accept: "text/html" } }),
    {
      ASSETS: { fetch: async () => new Response("Not found", { status: 404 }) },
    },
    { waitUntil() {}, passThroughOnException() {} },
  );
}

test("server-renders the ContaMind sign-in experience", async () => {
  const response = await render();
  assert.equal(response.status, 200);
  assert.match(response.headers.get("content-type") ?? "", /^text\/html\b/i);

  const html = await response.text();
  assert.match(html, /<title>ContaMind \| Agentes contables<\/title>/i);
  assert.match(html, /CONTAMIND · AGENTES CONTABLES/);
  assert.match(html, /Ingresa a tu espacio/);
  assert.match(html, /Correo electrónico/);
  assert.match(html, /Contraseña/);
  assert.doesNotMatch(html, /react-loading-skeleton|Building your site|codex-preview/i);
});

test("keeps the accounting-agent contracts and privacy boundary in the client", async () => {
  const [page, api, layout, component, operations, bankOperations, styles, cashFlowStyles, bankStyles, environment] = await Promise.all([
    readFile(new URL("../app/page.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/health-agent/api.ts", import.meta.url), "utf8"),
    readFile(new URL("../app/layout.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/health-agent/HealthAgentApp.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/health-agent/ReceivablesOperations.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/health-agent/BankReconciliationOperations.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/health-agent/health-agent.css", import.meta.url), "utf8"),
    readFile(new URL("../app/health-agent/cash-flow.css", import.meta.url), "utf8"),
    readFile(new URL("../app/health-agent/bank-reconciliation.css", import.meta.url), "utf8"),
    readFile(new URL("../.env.example", import.meta.url), "utf8"),
  ]);

  assert.match(page, /HealthAgentApp/);
  assert.match(api, /\/auth\/login/);
  assert.match(api, /\/companies\/mine/);
  assert.match(api, /\/companies\/\$\{companyId\}\/agents\/accounting-health\/chat/);
  assert.match(api, /\/companies\/\$\{companyId\}\/agents\/receivables\/chat/);
  assert.match(api, /\/companies\/\$\{companyId\}\/agents\/payables\/chat/);
  assert.match(api, /\/companies\/\$\{companyId\}\/agents\/cash-flow\/chat/);
  assert.match(api, /\/companies\/\$\{companyId\}\/agents\/bank-reconciliation\/chat/);
  assert.match(api, /\/companies\/\$\{companyId\}\/bank-reconciliation\/accounts/);
  assert.match(api, /\/companies\/\$\{companyId\}\/bank-reconciliation\/transactions/);
  assert.match(api, /\/companies\/\$\{companyId\}\/receivables\/open-items/);
  assert.match(api, /\/companies\/\$\{companyId\}\/payables\/open-items/);
  assert.match(api, /\/companies\/\$\{companyId\}\/collection-followups/);
  assert.match(api, /Authorization: `Bearer \$\{token\}`/);
  assert.match(environment, /VITE_API_BASE_URL=http:\/\/localhost:8000\/api\/v1/);
  assert.match(layout, /title: "ContaMind \| Agentes contables"/);
  assert.match(layout, /images: \["\/og-agentes\.png"\]/);
  assert.match(component, /No incluyas NIT, correos, documentos ni\s+credenciales/);
  assert.match(component, /No tienes empresas disponibles/);
  assert.match(component, /Esta empresa está desactivada/);
  assert.match(component, /AGENTE DE CARTERA/);
  assert.match(component, /AGENTE DE CUENTAS POR PAGAR/);
  assert.match(component, /AGENTE DE FLUJO DE CAJA/);
  assert.match(component, /AGENTE DE CONCILIACIÓN BANCARIA/);
  assert.match(component, /BankReconciliationOperations/);
  assert.match(component, /ReceivablesOperations/);
  assert.match(component, /Qué puedes consultar:[\s\S]*saldos, vencimientos y antigüedad, pagos/);
  assert.match(component, /seguimientos, promesas y alertas, siempre de forma agregada/);
  assert.match(component, /detalle de una factura, cliente o pago/);
  assert.match(component, /¿Cómo se distribuye la antigüedad de la cartera\?/);
  assert.match(component, /¿Hay pagos parciales, seguimientos o promesas incumplidas\?/);
  assert.match(component, /cash-flow-chat-scope/);
  assert.match(component, /Movimiento neto a 90 días/);
  assert.match(component, /No representa saldo bancario disponible/);
  assert.match(component, /Entradas: \{unsignedAmountsText/);
  assert.match(component, /bank-reconciliation-chat-scope/);
  assert.match(component, /fallbackResponseFor/);
  assert.match(component, /serviceNoticeFor/);
  assert.match(component, /conversationDetailText/);
  assert.match(component, /canUseAgent && !busy/);
  assert.match(component, /Preguntas sugeridas para continuar/);
  assert.match(component, /Consulta protegida/);
  assert.match(component, /temporarily_unavailable: "Modo de respaldo"/);
  assert.match(styles, /\.service-notice/);
  assert.match(styles, /\.scope-hint/);
  assert.match(styles, /\.scope-link:focus-visible/);
  assert.match(styles, /\.follow-up-suggestions/);
  assert.match(cashFlowStyles, /\.cash-flow-periods/);
  assert.match(bankStyles, /\.bank-transaction-list/);
  assert.match(operations, /canManage/);
  assert.match(operations, /confirmed: true/);
  assert.match(operations, /No incluyas datos personales/);
  assert.match(bankOperations, /No guardamos el número completo de la cuenta/);
  assert.match(bankOperations, /window\.confirm/);
  assert.match(bankOperations, /window\.confirm[\s\S]*handleReview/);
  assert.doesNotMatch(component, /localStorage|sessionStorage/);
  assert.doesNotMatch(operations, /localStorage|sessionStorage/);
  assert.doesNotMatch(bankOperations, /localStorage|sessionStorage/);

  await access(new URL("../public/og-agentes.png", import.meta.url));
});
