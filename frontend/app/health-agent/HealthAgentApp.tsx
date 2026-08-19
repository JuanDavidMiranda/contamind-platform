"use client";

import { type FormEvent, useState } from "react";

import { ApiError, askBankReconciliation, askCashFlow, askElectronicInvoicing, askExogenousInformation, askHealth, askPayables, askReceivables, askTreasury, companies, login } from "./api";
import { BankReconciliationOperations } from "./BankReconciliationOperations";
import { DianConfigurationOperations } from "./DianConfigurationOperations";
import { ElectronicInvoicingOperations } from "./ElectronicInvoicingOperations";
import { ExogenousInformationOperations } from "./ExogenousInformationOperations";
import { ReceivablesOperations } from "./ReceivablesOperations";
import type { CashFlowAmount, Company, Conversation, Finding, Report, ReportMetricValue } from "./types";
import "./health-agent.css";
import "./receivables.css";
import "./cash-flow.css";
import "./bank-reconciliation.css";
import "./electronic-invoicing.css";
import "./exogenous-information.css";
import "./dian-configuration.css";

type Session = { token: string; userId: number };
type AgentKey = "accounting-health" | "receivables" | "payables" | "cash-flow" | "electronic-invoicing" | "exogenous-information" | "bank-reconciliation" | "treasury";
type AgentView = "diagnostic" | "operations" | "dian";
type Message = {
  id: string;
  role: "user" | "assistant";
  content: string;
  outcome?: Conversation["outcome"];
  llmUsed?: boolean;
};

const agentDetails: Record<AgentKey, {
  label: string;
  eyebrow: string;
  title: string;
  description: string;
  emptyTitle: string;
  emptyDescription: (companyName: string) => string;
  placeholder: string;
  fallback: string;
  prompts: string[];
  metrics: Array<[string, string]>;
}> = {
  "accounting-health": {
    label: "Salud contable",
    eyebrow: "AGENTE DE SALUD CONTABLE",
    title: "Una conversación para revisar lo importante.",
    description: "Consulta prioridades, interpreta alertas y revisa la calidad de tus datos contables desde un único espacio.",
    emptyTitle: "¿Por dónde quieres empezar?",
    emptyDescription: (companyName) => `Revisaré los hallazgos actuales de ${companyName} y te devolveré la evidencia disponible.`,
    placeholder: "Pregunta sobre la salud contable…",
    fallback: "No fue posible consultar la salud contable.",
    prompts: ["¿Qué debo revisar primero?", "¿Qué significa cada alerta?", "¿Cómo corrijo un comprobante descuadrado?"],
    metrics: [["data_sources", "Fuentes"], ["parties", "Terceros"], ["invoices", "Facturas"], ["payments", "Pagos"], ["journal_entries", "Comprobantes"]],
  },
  receivables: {
    label: "Cartera",
    eyebrow: "AGENTE DE CARTERA",
    title: "Entiende qué saldos requieren seguimiento.",
    description: "Analiza facturas de venta y pagos registrados para orientar la gestión de cobro, sin modificar tu contabilidad.",
    emptyTitle: "¿Qué quieres revisar de la cartera?",
    emptyDescription: (companyName) => `Analizaré los saldos de venta disponibles de ${companyName} por moneda, sin exponer datos de clientes.`,
    placeholder: "Pregunta sobre cartera y saldos…",
    fallback: "No fue posible consultar la cartera.",
    prompts: [
      "¿Qué debo revisar primero?",
      "¿Qué saldos pendientes hay por moneda?",
      "¿Cuántas facturas vencen hoy o están vencidas?",
      "¿Cómo se distribuye la antigüedad de la cartera?",
      "¿Hay pagos parciales, seguimientos o promesas incumplidas?",
      "¿Qué significa cada alerta de cartera?",
    ],
    metrics: [
      ["sales_invoices", "Facturas de venta"],
      ["open_sales_invoices", "Con saldo"],
      ["overdue_sales_invoices", "Vencidas"],
      ["seriously_overdue_sales_invoices", "Vencidas +90 días"],
      ["sales_invoices_missing_due_date", "Sin vencimiento"],
      ["broken_payment_promises", "Promesas incumplidas"],
      ["partially_paid_sales_invoices", "Pago parcial"],
      ["average_days_to_collect", "Promedio de recaudo (días)"],
    ],
  },
  payables: {
    label: "Cuentas por pagar",
    eyebrow: "AGENTE DE CUENTAS POR PAGAR",
    title: "Prioriza obligaciones con evidencia.",
    description: "Analiza facturas de compra y pagos registrados sin modificar tu contabilidad.",
    emptyTitle: "¿Qué quieres revisar de las obligaciones?",
    emptyDescription: (companyName) => `Analizaré los saldos de compra disponibles de ${companyName} por moneda, sin exponer datos de proveedores.`,
    placeholder: "Pregunta sobre obligaciones y vencimientos…",
    fallback: "No fue posible consultar las cuentas por pagar.",
    prompts: ["¿Qué obligaciones debo revisar primero?", "¿Qué saldos pendientes hay por moneda?", "¿Cuántas facturas de compra están vencidas?", "¿Cómo se distribuye la antigüedad?"],
    metrics: [["purchase_invoices", "Facturas de compra"], ["open_purchase_invoices", "Con saldo"], ["overdue_purchase_invoices", "Vencidas"], ["seriously_overdue_purchase_invoices", "Vencidas +90 días"], ["purchase_invoices_missing_due_date", "Sin vencimiento"], ["partially_paid_purchase_invoices", "Pago parcial"], ["average_days_to_pay", "Promedio de pago (días)"]],
  },
  "cash-flow": {
    label: "Flujo de caja",
    eyebrow: "AGENTE DE FLUJO DE CAJA",
    title: "Anticipa movimientos antes de que venzan.",
    description: "Combina cartera y cuentas por pagar para proyectar entradas y salidas abiertas, siempre separadas por moneda.",
    emptyTitle: "¿Qué quieres revisar del flujo de caja?",
    emptyDescription: (companyName) => "Proyectaré los vencimientos abiertos de " + companyName + " sin asumir recaudos, pagos ni saldos bancarios.",
    placeholder: "Pregunta sobre entradas, salidas y vencimientos…",
    fallback: "No fue posible generar la proyección de flujo de caja.",
    prompts: [
      "¿Qué movimientos debo revisar primero?",
      "¿Qué entradas y salidas hay en los próximos 30 días?",
      "¿Cuál es el movimiento neto proyectado por moneda?",
      "¿Qué datos faltan para completar la proyección?",
    ],
    metrics: [
      ["open_receivables", "Cuentas por cobrar"],
      ["open_payables", "Cuentas por pagar"],
      ["scheduled_receivables", "Entradas con fecha"],
      ["scheduled_payables", "Salidas con fecha"],
      ["receivables_missing_due_date", "Cobros sin fecha"],
      ["payables_missing_due_date", "Pagos sin fecha"],
      ["currencies", "Monedas"],
      ["horizon_days", "Horizonte (días)"],
    ],
  },
  "electronic-invoicing": {
    label: "Facturación electrónica",
    eyebrow: "AGENTE DE FACTURACIÓN ELECTRÓNICA",
    title: "Revisa la evidencia antes de transmitir.",
    description: "Analiza los estados electrónicos importados y la calidad de las facturas de venta, sin emitir ni consultar documentos ante la DIAN.",
    emptyTitle: "¿Qué quieres revisar de facturación electrónica?",
    emptyDescription: (companyName) => `Revisaré los estados electrónicos disponibles de ${companyName}, sin mostrar facturas ni referencias individuales.`,
    placeholder: "Pregunta sobre estados, rechazos y trazabilidad electrónica…",
    fallback: "No fue posible generar el diagnóstico de facturación electrónica.",
    prompts: [
      "¿Qué debo revisar primero en facturación electrónica?",
      "¿Cuántas facturas están pendientes o rechazadas?",
      "¿Qué datos faltan para tener trazabilidad electrónica?",
      "¿El aplicativo ya valida documentos ante la DIAN?",
    ],
    metrics: [
      ["sales_invoices", "Facturas de venta"],
      ["electronic_status_recorded", "Con estado electrónico"],
      ["accepted_electronic_invoices", "Aceptadas"],
      ["pending_electronic_invoices", "Pendientes"],
      ["rejected_electronic_invoices", "Rechazadas o con error"],
      ["invoices_without_electronic_status", "Sin estado electrónico"],
      ["invoices_without_electronic_reference", "Sin referencia electrónica"],
      ["electronic_status_coverage", "Cobertura de estado (%)"],
    ],
  },
  "exogenous-information": {
    label: "Información exógena",
    eyebrow: "AGENTE DE INFORMACIÓN EXÓGENA",
    title: "Prepara los datos antes de consolidar.",
    description: "Revisa la calidad de terceros, facturas y pagos por año gravable, sin definir obligaciones ni generar archivos oficiales para la DIAN.",
    emptyTitle: "¿Qué quieres revisar para información exógena?",
    emptyDescription: (companyName) => `Revisaré la preparación de datos disponible de ${companyName} sin mostrar terceros, facturas ni pagos individuales en el chat.`,
    placeholder: "Pregunta sobre preparación, terceros y trazabilidad…",
    fallback: "No fue posible generar el diagnóstico de información exógena.",
    prompts: [
      "¿Qué debo revisar primero para información exógena?",
      "¿Qué datos faltan en los terceros?",
      "¿Qué facturas o pagos requieren trazabilidad?",
      "¿El aplicativo ya genera archivos para la DIAN?",
    ],
    metrics: [
      ["tax_year", "Año gravable"],
      ["registered_parties", "Terceros"],
      ["party_identification_coverage", "Cobertura de identificación (%)"],
      ["parties_missing_document_number", "Sin número de documento"],
      ["invoices_in_tax_year", "Facturas del año"],
      ["invoices_missing_counterparty", "Facturas sin contraparte"],
      ["payments_in_tax_year", "Pagos del año"],
      ["payments_without_invoice", "Pagos sin factura"],
    ],
  },
  "bank-reconciliation": {
    label: "Conciliación bancaria",
    eyebrow: "AGENTE DE CONCILIACIÓN BANCARIA",
    title: "Contrasta el banco con tu contabilidad.",
    description: "Importa extractos, revisa coincidencias exactas y mantiene cada confirmación bajo control humano.",
    emptyTitle: "¿Qué quieres revisar de la conciliación?",
    emptyDescription: (companyName) => `Analizaré la cobertura agregada de ${companyName} sin mostrar movimientos ni referencias individuales en el chat.`,
    placeholder: "Pregunta sobre cobertura y diferencias bancarias…",
    fallback: "No fue posible consultar la conciliación bancaria.",
    prompts: [
      "¿Qué debo revisar primero en la conciliación?",
      "¿Cuántos movimientos siguen sin conciliar?",
      "¿Cuál es la cobertura de conciliación?",
      "¿Qué entradas y salidas fueron importadas por moneda?",
    ],
    metrics: [
      ["bank_accounts", "Cuentas"],
      ["statement_imports", "Extractos cargados"],
      ["imported_transactions", "Movimientos"],
      ["reconciled_transactions", "Conciliados"],
      ["suggested_matches", "Sugeridos"],
      ["unmatched_transactions", "Sin coincidencia"],
      ["ambiguous_transactions", "Ambiguos"],
      ["reconciliation_rate", "Cobertura (%)"],
    ],
  },
  treasury: {
    label: "Tesorería y liquidez",
    eyebrow: "AGENTE DE TESORERÍA Y LIQUIDEZ",
    title: "Decide con señales, no con supuestos.",
    description: "Relaciona la proyección de cobros y pagos con la calidad de conciliación bancaria, siempre bajo revisión humana.",
    emptyTitle: "¿Qué quieres revisar de tesorería?",
    emptyDescription: (companyName) => `Contrastaré la proyección y la conciliación de ${companyName}, sin asumir un saldo bancario disponible.`,
    placeholder: "Pregunta sobre tesorería, proyección y conciliación…",
    fallback: "No fue posible generar el diagnóstico de tesorería.",
    prompts: [
      "¿Qué debo revisar primero para tesorería?",
      "¿Qué movimiento neto se proyecta a 30 días por moneda?",
      "¿La conciliación permite usar la señal bancaria?",
      "¿Qué impide conocer la disponibilidad real?",
    ],
    metrics: [
      ["horizon_days", "Horizonte (días)"],
      ["overdue_receivable_invoices", "Cobros vencidos"],
      ["receivables_missing_due_date", "Cobros sin fecha"],
      ["payables_missing_due_date", "Pagos sin fecha"],
      ["bank_accounts", "Cuentas configuradas"],
      ["verified_balance_accounts", "Cuentas con corte"],
      ["bank_accounts_without_verified_balance", "Cuentas sin corte"],
      ["verified_balance_coverage", "Cobertura de saldos (%)"],
      ["imported_bank_transactions", "Movimientos bancarios"],
      ["reconciled_bank_transactions", "Conciliados"],
      ["reconciliation_rate", "Cobertura (%)"],
    ],
  },
};

export function HealthAgentApp() {
  const [session, setSession] = useState<Session | null>(null);
  const [availableCompanies, setAvailableCompanies] = useState<Company[]>([]);
  const [companyId, setCompanyId] = useState("");
  const [activeAgent, setActiveAgent] = useState<AgentKey>("accounting-health");
  const [agentView, setAgentView] = useState<AgentView>("diagnostic");
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [report, setReport] = useState<Report | null>(null);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [question, setQuestion] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [serviceNotice, setServiceNotice] = useState<string | null>(null);
  const company = availableCompanies.find((item) => item.id === companyId);
  const canUseAgent = company?.status === "active";
  const agent = agentDetails[activeAgent];
  const hasOperationalView = activeAgent === "receivables" || activeAgent === "payables" || activeAgent === "electronic-invoicing" || activeAgent === "exogenous-information" || activeAgent === "bank-reconciliation";
  const showingDianConfiguration = activeAgent === "electronic-invoicing" && agentView === "dian";
  const showingOperations = (hasOperationalView && agentView === "operations") || showingDianConfiguration;

  async function signIn(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    setServiceNotice(null);

    try {
      const auth = await login(email.trim(), password);
      const companyList = await companies(auth.access_token);
      setSession({ token: auth.access_token, userId: auth.user_id });
      setAvailableCompanies(companyList);
      setCompanyId(companyList[0]?.id || "");
      setPassword("");
    } catch (cause) {
      setError(messageFor(cause, "No fue posible iniciar sesión."));
    } finally {
      setBusy(false);
    }
  }

  function chooseCompany(nextId: string) {
    setCompanyId(nextId);
    setConversationId(null);
    setMessages([]);
    setReport(null);
    setQuestion("");
    setError(null);
    setServiceNotice(null);
  }

  function chooseAgent(nextAgent: AgentKey) {
    setActiveAgent(nextAgent);
    setAgentView("diagnostic");
    setConversationId(null);
    setMessages([]);
    setReport(null);
    setQuestion("");
    setError(null);
    setServiceNotice(null);
  }

  async function send(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const text = question.trim();
    if (!session || !companyId || !text || busy || !canUseAgent) return;

    setError(null);
    setBusy(true);
    setMessages((current) => [
      ...current,
      { id: `u-${Date.now()}`, role: "user", content: text },
    ]);

    try {
      const answer = activeAgent === "accounting-health"
        ? await askHealth(session.token, companyId, text, conversationId)
        : activeAgent === "receivables"
          ? await askReceivables(session.token, companyId, text, conversationId)
          : activeAgent === "payables"
            ? await askPayables(session.token, companyId, text, conversationId)
            : activeAgent === "cash-flow"
              ? await askCashFlow(session.token, companyId, text, conversationId)
              : activeAgent === "electronic-invoicing"
                ? await askElectronicInvoicing(session.token, companyId, text, conversationId)
              : activeAgent === "exogenous-information"
                ? await askExogenousInformation(session.token, companyId, text, conversationId)
              : activeAgent === "bank-reconciliation"
                ? await askBankReconciliation(session.token, companyId, text, conversationId)
                : await askTreasury(session.token, companyId, text, conversationId);
      setConversationId(answer.conversation_id);
      if (answer.report) setReport(answer.report);
      setQuestion("");
      setServiceNotice(null);

      if (answer.conversation) {
        const conversation = answer.conversation;
        const usingFallback = conversation.outcome === "temporarily_unavailable";
        setServiceNotice(usingFallback ? serviceNoticeFor(activeAgent) : null);
        setMessages((current) => [
          ...current,
          {
            id: `a-${Date.now()}`,
            role: "assistant",
            content: usingFallback
              ? fallbackResponseFor(activeAgent, answer.report, conversation.response)
              : conversation.response,
            outcome: conversation.outcome,
            llmUsed: conversation.llm_used,
          },
        ]);
      }
    } catch (cause) {
      const problem = messageFor(cause, agent.fallback);
      setError(problem);
      setServiceNotice(null);
      setMessages((current) => [
        ...current,
        { id: `e-${Date.now()}`, role: "assistant", content: problem },
      ]);
    } finally {
      setBusy(false);
    }
  }

  if (!session) {
    return (
      <main className="auth-shell">
        <section className="auth-copy">
          <span className="brand">C</span>
          <p className="eyebrow">CONTAMIND · AGENTES CONTABLES</p>
          <h1>Entiende qué necesita atención, con evidencia.</h1>
          <p>
            Consulta diagnósticos de salud contable y cartera desde un único espacio,
            siempre con evidencia verificable.
          </p>
          <ul>
            <li>Diagnóstico de solo lectura</li>
            <li>Hallazgos y métricas verificables</li>
            <li>Conversaciones acotadas por agente</li>
          </ul>
        </section>

        <section className="login-card">
          <p className="eyebrow">ACCESO SEGURO</p>
          <h2>Ingresa a tu espacio</h2>
          <p>Usa la cuenta con la que accedes a tus empresas en ContaMind.</p>
          <form onSubmit={signIn}>
            <label>
              Correo electrónico
              <input
                type="email"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                autoComplete="email"
                required
                placeholder="nombre@empresa.com"
              />
            </label>
            <label>
              Contraseña
              <input
                type="password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                autoComplete="current-password"
                minLength={8}
                required
                placeholder="••••••••"
              />
            </label>
            {error ? <p className="form-error" role="alert">{error}</p> : null}
            <button className="primary" disabled={busy}>
              {busy ? "Validando acceso…" : "Continuar"}
            </button>
          </form>
          <small>El token se mantiene solo en memoria y se descarta al recargar la página.</small>
        </section>
      </main>
    );
  }

  return (
    <main className="workspace">
      <aside className="sidebar">
        <div className="logo"><span className="brand">C</span><b>ContaMind</b></div>
        <section>
          <p className="side-label">EMPRESA ACTIVA</p>
          <label className="sr-only" htmlFor="company">Empresa activa</label>
          <select
            id="company"
            value={companyId}
            onChange={(event) => chooseCompany(event.target.value)}
            disabled={availableCompanies.length === 0}
          >
            {availableCompanies.length === 0 ? <option value="">Sin empresas disponibles</option> : null}
            {availableCompanies.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
          </select>
          {availableCompanies.length === 0 ? (
            <p className="company-empty" role="status">No tienes empresas asignadas todavía.</p>
          ) : null}
          {company ? (
            <span className={`company-state ${company.status}`}>
              {company.status === "active" ? "Empresa activa" : "Empresa desactivada"}
            </span>
          ) : null}
        </section>
        <nav aria-label="Agentes disponibles">
          {(Object.keys(agentDetails) as AgentKey[]).map((agentKey) => (
            <button
              key={agentKey}
              type="button"
              className={activeAgent === agentKey ? "active" : undefined}
              onClick={() => chooseAgent(agentKey)}
            >
              {agentDetails[agentKey].label}
            </button>
          ))}
          <span>Fuentes de datos</span>
          <span>Auditoría</span>
        </nav>
        <footer>
          Sesión de usuario {session.userId}
          <button
            type="button"
            onClick={() => {
              setSession(null);
              setAvailableCompanies([]);
              setMessages([]);
              setReport(null);
            }}
          >
            Cerrar sesión
          </button>
        </footer>
      </aside>

      <section className="chat">
        <header>
          <div>
            <p className="eyebrow">{agent.eyebrow}</p>
            <h1>{agent.title}</h1>
          </div>
          <span className="readonly">
            {showingOperations ? "Gestión controlada" : "Solo lectura"}
          </span>
        </header>
        {hasOperationalView ? (
          <div className="receivables-tabs" role="tablist" aria-label="Vistas del agente">
            <button
              type="button"
              role="tab"
              aria-selected={agentView === "diagnostic"}
              className={agentView === "diagnostic" ? "active" : undefined}
              onClick={() => setAgentView("diagnostic")}
            >
              Diagnostico
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={agentView === "operations"}
              className={agentView === "operations" ? "active" : undefined}
              onClick={() => setAgentView("operations")}
            >
              {activeAgent === "receivables"
                ? "Cartera operativa"
                : activeAgent === "payables"
                  ? "Pagos operativos"
                  : activeAgent === "electronic-invoicing"
                    ? "Evidencia operativa"
                  : activeAgent === "exogenous-information"
                    ? "Preparación operativa"
                  : "Conciliación operativa"}
            </button>
            {activeAgent === "electronic-invoicing" ? (
              <button
                type="button"
                role="tab"
                aria-selected={agentView === "dian"}
                className={agentView === "dian" ? "active" : undefined}
                onClick={() => setAgentView("dian")}
              >
                Configuración DIAN
              </button>
            ) : null}
          </div>
        ) : null}
        {showingOperations ? (
          showingDianConfiguration ? (
            <DianConfigurationOperations
              key={`${companyId}-${session.userId}-dian`}
              token={session.token}
              company={company}
              enabled={Boolean(canUseAgent)}
            />
          ) : activeAgent === "bank-reconciliation" ? (
            <BankReconciliationOperations
              key={`${companyId}-${session.userId}-bank`}
              token={session.token}
              companyId={companyId}
              companyName={company?.name || "esta empresa"}
              enabled={Boolean(canUseAgent)}
            />
          ) : activeAgent === "electronic-invoicing" ? (
            <ElectronicInvoicingOperations
              key={`${companyId}-${session.userId}-electronic`}
              token={session.token}
              companyId={companyId}
              companyName={company?.name || "esta empresa"}
              enabled={Boolean(canUseAgent)}
            />
          ) : activeAgent === "exogenous-information" ? (
            <ExogenousInformationOperations
              key={`${companyId}-${session.userId}-exogenous`}
              token={session.token}
              companyId={companyId}
              companyName={company?.name || "esta empresa"}
              enabled={Boolean(canUseAgent)}
            />
          ) : (
            <ReceivablesOperations
              key={`${companyId}-${session.userId}`}
              token={session.token}
              companyId={companyId}
              companyName={company?.name || "esta empresa"}
              enabled={Boolean(canUseAgent)}
              mode={activeAgent === "payables" ? "payables" : "receivables"}
            />
          )
        ) : (
          <>
        <p className="privacy">
          <b>Protege los datos personales.</b> No incluyas NIT, correos, documentos ni
          credenciales en la conversación. Este agente es de solo lectura.
        </p>
        {activeAgent === "receivables" || activeAgent === "payables" ? (
          <p id="receivables-chat-scope" className="scope-hint">
            <b>Qué puedes consultar:</b> saldos, vencimientos y antigüedad, pagos,
            seguimientos, promesas y alertas, siempre de forma agregada. Para revisar el
            detalle de una factura, cliente o pago, usa{" "}
            <button
              type="button"
              className="scope-link"
              onClick={() => setAgentView("operations")}
            >
              {activeAgent === "receivables" ? "Cartera operativa" : "Pagos operativos"}
            </button>
            .
          </p>
        ) : null}
        {activeAgent === "cash-flow" ? (
          <p id="cash-flow-chat-scope" className="scope-hint">
            <b>Qué puedes consultar:</b> entradas, salidas, movimiento neto y
            vencimientos por período y moneda. La proyección no incluye saldos
            bancarios ni garantiza que un cobro o pago vaya a ocurrir.
          </p>
        ) : null}
        {activeAgent === "electronic-invoicing" ? (
          <p id="electronic-invoicing-chat-scope" className="scope-hint">
            <b>Qué puedes consultar:</b> estados electrónicos importados, rechazos,
            pendientes, trazabilidad y calidad de datos de forma agregada. El agente no
            emite, firma, transmite ni consulta documentos ante la DIAN. Para preparar
            una consulta individual de adquiriente, usa{" "}
            <button type="button" className="scope-link" onClick={() => setAgentView("dian")}>
              Configuración DIAN
            </button>.
          </p>
        ) : null}
        {activeAgent === "exogenous-information" ? (
          <p id="exogenous-information-chat-scope" className="scope-hint">
            <b>Qué puedes consultar:</b> preparación agregada de terceros, facturas y pagos
            por año gravable. Para revisar casos individuales, usa{" "}
            <button type="button" className="scope-link" onClick={() => setAgentView("operations")}>
              Preparación operativa
            </button>. El agente no determina obligación, formatos ni fechas DIAN, y no genera archivos oficiales.
          </p>
        ) : null}
        {activeAgent === "bank-reconciliation" ? (
          <p id="bank-reconciliation-chat-scope" className="scope-hint">
            <b>Qué puedes consultar:</b> cobertura, pendientes, coincidencias y entradas
            o salidas agregadas. Para cargar extractos o confirmar una coincidencia, usa{" "}
            <button type="button" className="scope-link" onClick={() => setAgentView("operations")}>
              Conciliación operativa
            </button>.
          </p>
        ) : null}
        {activeAgent === "treasury" ? (
          <p id="treasury-chat-scope" className="scope-hint">
            <b>Qué puedes consultar:</b> proyección de entradas y salidas a 30 días,
            calidad de conciliación y señales que requieren revisión. El diagnóstico no
            autoriza o programa pagos; usa Conciliación operativa para registrar cortes
            de saldo bancario verificados.
          </p>
        ) : null}
        {serviceNotice ? <p className="service-notice" role="status">{serviceNotice}</p> : null}

        <div className="messages" aria-live="polite">
          {messages.length === 0 ? (
            <div className="empty">
              <span className="orb">✦</span>
              <h2>
                {!company
                  ? "No tienes empresas disponibles."
                  : canUseAgent
                    ? agent.emptyTitle
                    : "Esta empresa está desactivada."}
              </h2>
              <p>
                {!company
                  ? "Cuando un administrador te asigne una empresa, podrás consultar su salud contable aquí."
                  : canUseAgent
                    ? agent.emptyDescription(company.name)
                    : "Reactiva la empresa para poder iniciar una consulta de salud contable."}
              </p>
              {canUseAgent ? (
                <div className={`prompts ${activeAgent === "receivables" ? "receivables-prompts" : ""}`}>
                  {agent.prompts.map((prompt) => (
                    <button key={prompt} type="button" onClick={() => setQuestion(prompt)}>
                      {prompt}
                    </button>
                  ))}
                </div>
              ) : null}
            </div>
          ) : (
            <>
              {messages.map((item) => (
                <article className={`message ${item.role}`} key={item.id}>
                  <span>{item.role === "assistant" ? "✦" : "Tú"}</span>
                  <div>
                    <p>{item.content}</p>
                    {item.outcome ? (
                      <small>
                        {outcomeText(item.outcome)} · {conversationDetailText(item.outcome, item.llmUsed)}
                      </small>
                    ) : null}
                  </div>
                </article>
              ))}
              {canUseAgent && !busy ? (
                <section
                  className="follow-up-suggestions"
                  aria-label="Preguntas sugeridas para continuar"
                >
                  <p>Preguntas sugeridas</p>
                  <div className={`prompts ${activeAgent === "receivables" ? "receivables-prompts" : ""}`}>
                    {agent.prompts.map((prompt) => (
                      <button key={prompt} type="button" onClick={() => setQuestion(prompt)}>
                        {prompt}
                      </button>
                    ))}
                  </div>
                </section>
              ) : null}
            </>
          )}
        </div>

        {error ? <p className="inline-error" role="alert">{error}</p> : null}
        <form className="composer" onSubmit={send}>
          <label className="sr-only" htmlFor="question">Pregunta para el agente</label>
          <textarea
            id="question"
            value={question}
            onChange={(event) => setQuestion(event.target.value)}
            maxLength={2000}
            rows={2}
            disabled={!canUseAgent || busy}
            aria-describedby={
              activeAgent === "receivables" || activeAgent === "payables"
                ? "receivables-chat-scope"
                : activeAgent === "cash-flow"
                  ? "cash-flow-chat-scope"
                  : activeAgent === "bank-reconciliation"
                    ? "bank-reconciliation-chat-scope"
                    : activeAgent === "electronic-invoicing"
                      ? "electronic-invoicing-chat-scope"
                    : activeAgent === "treasury"
                    ? "treasury-chat-scope"
                  : undefined
            }
            placeholder={canUseAgent ? agent.placeholder : "Selecciona una empresa activa para comenzar"}
          />
          <button className="primary" disabled={!question.trim() || !canUseAgent || busy}>
            {busy ? "…" : "Enviar"}
          </button>
        </form>
          </>
        )}
      </section>

      <aside className="evidence">
        <section className="card status">
          <p className="side-label">ESTADO ACTUAL</p>
          {report ? (
            <>
              <span className={`badge ${report.overall_status}`}>{statusText(report.overall_status)}</span>
              <strong>
                {report.summary.finding_count}{" "}
                {report.summary.finding_count === 1 ? "alerta" : "alertas"} en revisión
              </strong>
              <p>{report.summary.critical_count} críticas · {report.summary.warning_count} advertencias</p>
            </>
          ) : (
            <>
              <span className="badge empty-badge">Sin consulta</span>
              <strong>La evidencia aparecerá aquí.</strong>
              <p>Envía una pregunta para generar el diagnóstico verificable.</p>
            </>
          )}
        </section>
        {report ? (
          <>
            <section className="card">
              <h2>Métricas</h2>
              <dl className="metrics">
                {agent.metrics.map(([key, label]) => (
                  <div key={key}><dt>{label}</dt><dd>{metricText(report.metrics[key])}</dd></div>
                ))}
              </dl>
            </section>
            {report.metrics.outstanding_balances?.length ? (
              <section className="card balances">
                <h2>Saldos pendientes</h2>
                <dl>
                  {report.metrics.outstanding_balances.map((balance) => (
                    <div key={balance.currency_code}>
                      <dt>{balance.currency_code}</dt>
                      <dd>{formatMoney(balance.amount, balance.currency_code)}</dd>
                    </div>
                  ))}
                </dl>
              </section>
            ) : null}
            {activeAgent === "cash-flow" && report.metrics.net_movements_90d?.length ? (
              <section className="card balances cash-flow-net">
                <h2>Movimiento neto a 90 días</h2>
                <dl>
                  {report.metrics.net_movements_90d.map((amount) => (
                    <div key={amount.currency_code}>
                      <dt>{amount.currency_code}</dt>
                      <dd className={Number(amount.amount) < 0 ? "negative" : "positive"}>
                        {formatSignedMoney(amount)}
                      </dd>
                    </div>
                  ))}
                </dl>
                <small>No representa saldo bancario disponible.</small>
              </section>
            ) : null}
            {activeAgent === "treasury" && report.metrics.net_projected_movements_30d?.length ? (
              <section className="card balances cash-flow-net">
                <h2>Movimiento neto proyectado a 30 días</h2>
                <dl>
                  {report.metrics.net_projected_movements_30d.map((amount) => (
                    <div key={amount.currency_code}>
                      <dt>{amount.currency_code}</dt>
                      <dd className={Number(amount.amount) < 0 ? "negative" : "positive"}>
                        {formatSignedMoney(amount)}
                      </dd>
                    </div>
                  ))}
                </dl>
                <small>No representa disponibilidad bancaria real.</small>
              </section>
            ) : null}
            {activeAgent === "treasury" && report.metrics.verified_bank_balances?.length ? (
              <section className="card balances">
                <h2>Saldos bancarios verificados</h2>
                <dl>
                  {report.metrics.verified_bank_balances.map((amount) => (
                    <div key={amount.currency_code}>
                      <dt>{amount.currency_code}</dt>
                      <dd>{formatMoney(amount.amount, amount.currency_code)}</dd>
                    </div>
                  ))}
                </dl>
                <small>Corte: {report.metrics.verified_balance_cutoff_date || "sin fecha común"}. No autoriza pagos automáticamente.</small>
              </section>
            ) : null}
            {activeAgent === "cash-flow" && report.metrics.cash_flow_periods?.length ? (
              <section className="card cash-flow-periods">
                <h2>Movimientos por período</h2>
                <ol>
                  {report.metrics.cash_flow_periods.map((period) => (
                    <li key={period.key}>
                      <div>
                        <strong>{cashFlowPeriodLabel(period.key)}</strong>
                        <small>
                          {period.receivable_invoices} entrada{period.receivable_invoices === 1 ? "" : "s"}
                          {" · "}
                          {period.payable_invoices} salida{period.payable_invoices === 1 ? "" : "s"}
                        </small>
                      </div>
                      <span>{amountsText(period.net_movements)}</span>
                      <small className="cash-flow-breakdown">
                        Entradas: {unsignedAmountsText(period.projected_inflows)}
                        {" · "}
                        Salidas: {unsignedAmountsText(period.projected_outflows)}
                      </small>
                    </li>
                  ))}
                </ol>
              </section>
            ) : null}
            <section className="card findings">
              <h2>Hallazgos <span>{report.summary.finding_count}</span></h2>
              {report.findings.length ? (
                report.findings.map((finding) => <FindingCard key={finding.code} finding={finding} />)
              ) : <p className="healthy">No hay alertas que requieran atención.</p>}
            </section>
          </>
        ) : null}
      </aside>
    </main>
  );
}

function FindingCard({ finding }: { finding: Finding }) {
  return (
    <article className="finding">
      <i className={finding.severity} />
      <div>
        <b>{finding.message}</b>
        <small>Qué hacer: {finding.recommendation}</small>
      </div>
    </article>
  );
}

function messageFor(cause: unknown, fallback: string) {
  return cause instanceof ApiError || cause instanceof Error ? cause.message : fallback;
}

function statusText(status: Report["overall_status"]) {
  return status === "healthy" ? "Saludable" : status === "critical" ? "Atención crítica" : "Requiere atención";
}

function formatMoney(amount: string, currency: string) {
  return new Intl.NumberFormat("es-CO", {
    style: "currency",
    currency,
    maximumFractionDigits: 2,
  }).format(Number(amount));
}

function formatSignedMoney(amount: CashFlowAmount) {
  const value = Number(amount.amount);
  const formatted = formatMoney(String(Math.abs(value)), amount.currency_code);
  return value > 0 ? "+" + formatted : value < 0 ? "−" + formatted : formatted;
}

function amountsText(amounts: CashFlowAmount[]) {
  if (!amounts.length) return "Sin movimiento";
  return amounts.map(formatSignedMoney).join(" · ");
}

function unsignedAmountsText(amounts: CashFlowAmount[]) {
  if (!amounts.length) return "Sin movimiento";
  return amounts
    .map((amount) => formatMoney(amount.amount, amount.currency_code))
    .join(" · ");
}

function cashFlowPeriodLabel(key: string) {
  return {
    overdue: "Vencidos",
    due_today: "Vence hoy",
    next_7_days: "Próximos 7 días",
    days_8_30: "Días 8 a 30",
    days_31_60: "Días 31 a 60",
    days_61_90: "Días 61 a 90",
    beyond_90: "Después de 90 días",
  }[key] || key;
}

function metricText(value: ReportMetricValue | undefined) {
  return typeof value === "number" || typeof value === "string" ? value : 0;
}

function serviceNoticeFor(agent: AgentKey) {
  return agent === "receivables"
    ? "El asistente conversacional de cartera no está disponible temporalmente. Mostramos un resumen respaldado por el diagnóstico actualizado."
    : "El asistente conversacional no está disponible temporalmente. Mostramos un resumen respaldado por el diagnóstico actualizado.";
}

function fallbackResponseFor(agent: AgentKey, report: Report | null, serverResponse: string) {
  if (!report) return serverResponse;

  if (agent === "receivables") {
    const metrics = report.metrics;
    const invoicesNotDue = metrics.aging_buckets?.find((bucket) => bucket.key === "not_due")?.invoices ?? 0;
    const dueToday = numericMetric(metrics.due_today_sales_invoices);
    const overdue = numericMetric(metrics.overdue_sales_invoices);
    const missingDueDate = numericMetric(metrics.sales_invoices_missing_due_date);
    const missingDueDateText = missingDueDate
      ? ` Además, ${invoicesText(missingDueDate)} no tiene fecha de vencimiento registrada.`
      : "";

    return (
      `Como respaldo, el diagnóstico muestra ${invoicesText(invoicesNotDue)} por vencer, `
      + `${invoicesText(dueToday)} con vencimiento hoy y ${invoicesText(overdue)} vencida${overdue === 1 ? "" : "s"}.`
      + `${missingDueDateText} Revisa las métricas y hallazgos para el detalle verificable.`
    );
  }

  const { finding_count: findings, critical_count: critical, warning_count: warnings } = report.summary;
  return (
    `Como respaldo, el diagnóstico muestra ${findings} ${findings === 1 ? "alerta" : "alertas"}: `
    + `${critical} crítica${critical === 1 ? "" : "s"} y ${warnings} advertencia${warnings === 1 ? "" : "s"}. `
    + "Revisa la evidencia disponible para el detalle verificable."
  );
}

function numericMetric(value: ReportMetricValue | undefined) {
  return typeof value === "number" ? value : 0;
}

function invoicesText(count: number) {
  return `${count} ${count === 1 ? "factura" : "facturas"}`;
}

function outcomeText(outcome: Conversation["outcome"]) {
  return {
    answered: "Respuesta disponible",
    clarification_needed: "Reformula la consulta",
    out_of_scope: "Fuera del alcance",
    temporarily_unavailable: "Modo de respaldo",
  }[outcome];
}

function conversationDetailText(outcome: Conversation["outcome"], llmUsed: boolean | undefined) {
  if (llmUsed) return "Explicación asistida";
  if (outcome === "answered") return "Diagnóstico verificado";
  if (outcome === "temporarily_unavailable") return "Resumen verificado";
  return "Consulta protegida";
}
