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
  const [page, api, layout, component, operations, bankOperations, electronicOperations, exogenousOperations, dianOperations, dianHabilitationOperations, onboardingOperations, initialDataOperations, passwordOperations, betaAccessOperations, styles, betaStyles, cashFlowStyles, bankStyles, electronicStyles, exogenousStyles, dianStyles, dianHabilitationStyles, environment, betaEnvironment, packageJson, tsconfig, partiesTemplate, invoicesTemplate, paymentsTemplate] = await Promise.all([
    readFile(new URL("../app/page.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/health-agent/api.ts", import.meta.url), "utf8"),
    readFile(new URL("../app/layout.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/health-agent/HealthAgentApp.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/health-agent/ReceivablesOperations.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/health-agent/BankReconciliationOperations.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/health-agent/ElectronicInvoicingOperations.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/health-agent/ExogenousInformationOperations.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/health-agent/DianConfigurationOperations.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/health-agent/DianElectronicHabilitationDraft.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/health-agent/CompanyOnboarding.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/health-agent/InitialDataOperations.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/health-agent/PasswordChangeOperations.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/health-agent/BetaAccessOperations.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/health-agent/health-agent.css", import.meta.url), "utf8"),
    readFile(new URL("../app/health-agent/beta-setup.css", import.meta.url), "utf8"),
    readFile(new URL("../app/health-agent/cash-flow.css", import.meta.url), "utf8"),
    readFile(new URL("../app/health-agent/bank-reconciliation.css", import.meta.url), "utf8"),
    readFile(new URL("../app/health-agent/electronic-invoicing.css", import.meta.url), "utf8"),
    readFile(new URL("../app/health-agent/exogenous-information.css", import.meta.url), "utf8"),
    readFile(new URL("../app/health-agent/dian-configuration.css", import.meta.url), "utf8"),
    readFile(new URL("../app/health-agent/dian-electronic-habilitation-draft.css", import.meta.url), "utf8"),
    readFile(new URL("../.env.example", import.meta.url), "utf8"),
    readFile(new URL("../.env.beta.example", import.meta.url), "utf8"),
    readFile(new URL("../package.json", import.meta.url), "utf8"),
    readFile(new URL("../tsconfig.json", import.meta.url), "utf8"),
    readFile(new URL("../public/plantilla-terceros-beta.csv", import.meta.url), "utf8"),
    readFile(new URL("../public/plantilla-facturas-beta.csv", import.meta.url), "utf8"),
    readFile(new URL("../public/plantilla-pagos-beta.csv", import.meta.url), "utf8"),
  ]);

  assert.match(page, /HealthAgentApp/);
  assert.match(api, /\/auth\/login/);
  assert.match(api, /\/auth\/change-password/);
  assert.match(api, /\/admin\/beta-access/);
  assert.match(api, /\/companies\/mine/);
  assert.match(api, /\/companies\/onboarding/);
  assert.match(api, /\/companies\/\$\{companyId\}\/agents\/accounting-health\/chat/);
  assert.match(api, /\/companies\/\$\{companyId\}\/agents\/receivables\/chat/);
  assert.match(api, /\/companies\/\$\{companyId\}\/agents\/payables\/chat/);
  assert.match(api, /\/companies\/\$\{companyId\}\/agents\/cash-flow\/chat/);
  assert.match(api, /\/companies\/\$\{companyId\}\/agents\/electronic-invoicing\/chat/);
  assert.match(api, /\/companies\/\$\{companyId\}\/agents\/exogenous-information\/chat/);
  assert.match(api, /\/companies\/\$\{companyId\}\/agents\/bank-reconciliation\/chat/);
  assert.match(api, /\/companies\/\$\{companyId\}\/agents\/treasury\/chat/);
  assert.match(api, /\/companies\/\$\{companyId\}\/bank-reconciliation\/accounts/);
  assert.match(api, /\/companies\/\$\{companyId\}\/bank-reconciliation\/balance-snapshots/);
  assert.match(api, /\/companies\/\$\{companyId\}\/bank-reconciliation\/transactions/);
  assert.match(api, /\/companies\/\$\{companyId\}\/electronic-invoicing\/exceptions/);
  assert.match(api, /\/companies\/\$\{companyId\}\/electronic-invoicing\/imports/);
  assert.match(api, /\/companies\/\$\{companyId\}\/dian\/acquirers\/lookup/);
  assert.match(api, /\/companies\/\$\{companyId\}\/dian\/acquirers\/lookups/);
  assert.match(api, /\/companies\/\$\{companyId\}\/dian\/electronic-invoicing\/habilitation/);
  assert.match(api, /\/habilitation\/access/);
  assert.match(api, /\/habilitation-parameters/);
  assert.match(api, /\/technical-credentials/);
  assert.match(api, /\/numbering-ranges/);
  assert.match(api, /\/test-documents/);
  assert.match(api, /\/data-sources/);
  assert.match(api, /\/profiles/);
  assert.match(api, /\/imports\/parties/);
  assert.match(api, /\/imports\/accounting/);
  assert.match(api, /\/companies\/\$\{companyId\}\/exogenous-information\/exceptions/);
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
  assert.match(component, /AGENTE DE FACTURACIÓN ELECTRÓNICA/);
  assert.match(component, /AGENTE DE INFORMACIÓN EXÓGENA/);
  assert.match(component, /AGENTE DE CONCILIACIÓN BANCARIA/);
  assert.match(component, /AGENTE DE TESORERÍA Y LIQUIDEZ/);
  assert.match(component, /BankReconciliationOperations/);
  assert.match(component, /ElectronicInvoicingOperations/);
  assert.match(component, /DianConfigurationOperations/);
  assert.match(component, /CompanyOnboarding/);
  assert.match(component, /InitialDataOperations/);
  assert.match(component, /PasswordChangeOperations/);
  assert.match(component, /BetaAccessOperations/);
  assert.match(component, /Carga inicial/);
  assert.match(component, /Accesos de beta/);
  assert.match(component, /Consulta adquirientes/);
  assert.match(component, /Habilitación DIAN/);
  assert.match(component, /ExogenousInformationOperations/);
  assert.match(component, /ReceivablesOperations/);
  assert.match(component, /Qué puedes consultar:[\s\S]*saldos, vencimientos y antigüedad, pagos/);
  assert.match(component, /seguimientos, promesas y alertas, siempre de forma agregada/);
  assert.match(component, /detalle de una factura, cliente o pago/);
  assert.match(component, /¿Cómo se distribuye la antigüedad de la cartera\?/);
  assert.match(component, /¿Hay pagos parciales, seguimientos o promesas incumplidas\?/);
  assert.match(component, /cash-flow-chat-scope/);
  assert.match(component, /electronic-invoicing-chat-scope/);
  assert.match(component, /exogenous-information-chat-scope/);
  assert.match(component, /no\s+emite, firma ni transmite documentos ante la DIAN/);
  assert.match(component, /Movimiento neto a 90 días/);
  assert.match(component, /No representa saldo bancario disponible/);
  assert.match(component, /Entradas: \{unsignedAmountsText/);
  assert.match(component, /bank-reconciliation-chat-scope/);
  assert.match(component, /treasury-chat-scope/);
  assert.match(component, /Movimiento neto proyectado a 30 días/);
  assert.match(component, /No representa disponibilidad bancaria real/);
  assert.match(component, /Saldos bancarios verificados/);
  assert.match(component, /<b>\{finding\.message\}<\/b>/);
  assert.match(component, /Qué hacer: \{finding\.recommendation\}/);
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
  assert.match(bankStyles, /\.bank-balance-summary/);
  assert.match(operations, /canManage/);
  assert.match(operations, /confirmed: true/);
  assert.match(operations, /No incluyas datos personales/);
  assert.match(bankOperations, /No guardamos el número completo de la cuenta/);
  assert.match(bankOperations, /Registrar saldo verificado/);
  assert.match(bankOperations, /Cortes bancarios verificados/);
  assert.match(bankOperations, /window\.confirm/);
  assert.match(bankOperations, /window\.confirm[\s\S]*handleReview/);
  assert.match(electronicOperations, /Evidencia y excepciones/);
  assert.match(electronicOperations, /La conexión en tiempo real con la DIAN aún no está habilitada/);
  assert.match(electronicOperations, /no comparte referencias electrónicas ni datos de adquirientes/);
  assert.match(electronicOperations, /Se conserva el resultado por fila, no el contenido sensible del archivo/);
  assert.match(electronicStyles, /\.electronic-exception-list/);
  assert.match(dianOperations, /Consulta de adquirientes/);
  assert.match(dianOperations, /No cargues archivos ni secretos en el chat/);
  assert.match(dianOperations, /electronic_invoice_issuance/);
  assert.match(dianOperations, /formRef\.current\?\.reset/);
  assert.match(dianStyles, /\.dian-operations/);
  assert.match(dianHabilitationOperations, /Cargar prueba firmada/);
  assert.match(dianHabilitationOperations, /Producción bloqueada/);
  assert.match(dianHabilitationOperations, /saveDianTechnicalCredentials/);
  assert.match(dianHabilitationOperations, /saveDianHabilitationParameters/);
  assert.match(dianHabilitationOperations, /canManageHabilitation/);
  assert.match(dianHabilitationOperations, /AbortController/);
  assert.match(dianHabilitationOperations, /clearSensitiveData\(\);\s*await onSaved/);
  assert.match(dianHabilitationOperations, /certificatePfxBase64 = ""/);
  assert.match(dianHabilitationOperations, /No se enviarán nuevas pruebas/);
  assert.match(api, /safeValidationMessage/);
  assert.doesNotMatch(api, /item\.input/);
  assert.match(dianHabilitationStyles, /\.dian-habilitation-draft__documents/);
  assert.match(onboardingOperations, /Crea el espacio de tu empresa/);
  assert.match(onboardingOperations, /Confirmo que estoy autorizado/);
  assert.match(initialDataOperations, /plantilla-terceros-beta\.csv/);
  assert.match(initialDataOperations, /window\.confirm/);
  assert.match(initialDataOperations, /safeRejectionMessage/);
  assert.match(initialDataOperations, /no adjuntes certificados, contraseñas/i);
  assert.match(passwordOperations, /Las demás sesiones activas se cerrarán/);
  assert.match(betaAccessOperations, /canal seguro/);
  assert.match(betaAccessOperations, /nunca muestra ni conserva la contraseña/);
  assert.match(betaStyles, /\.initial-data-steps/);
  assert.match(betaEnvironment, /VITE_REQUIRE_API_URL=true/);
  assert.match(packageJson, /@cloudflare\/workers-types/);
  assert.match(tsconfig, /@cloudflare\/workers-types/);
  assert.match(partiesTemplate, /Nombre,Tipo documento,Documento/);
  assert.match(invoicesTemplate, /Numero,Tipo,Fecha emision/);
  assert.match(paymentsTemplate, /Fecha pago,Valor,Moneda,Factura/);
  assert.match(exogenousOperations, /Datos pendientes por depurar/);
  assert.match(exogenousOperations, /no define obligación, formatos o conceptos DIAN/);
  assert.match(exogenousStyles, /\.exogenous-exception-list/);
  assert.doesNotMatch(component, /localStorage|sessionStorage/);
  assert.doesNotMatch(component, /finding\.code\.replaceAll/);
  assert.doesNotMatch(operations, /localStorage|sessionStorage/);
  assert.doesNotMatch(bankOperations, /localStorage|sessionStorage/);
  assert.doesNotMatch(electronicOperations, /localStorage|sessionStorage/);
  assert.doesNotMatch(exogenousOperations, /localStorage|sessionStorage/);
  assert.doesNotMatch(dianOperations, /localStorage|sessionStorage/);
  assert.doesNotMatch(dianHabilitationOperations, /localStorage|sessionStorage/);
  assert.doesNotMatch(initialDataOperations, /localStorage|sessionStorage/);
  assert.doesNotMatch(passwordOperations, /localStorage|sessionStorage/);
  assert.doesNotMatch(betaAccessOperations, /localStorage|sessionStorage/);

  await access(new URL("../public/og-agentes.png", import.meta.url));
});
