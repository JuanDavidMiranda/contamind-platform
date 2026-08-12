"use client";

import { type FormEvent, useState } from "react";

import { ApiError, askHealth, askReceivables, companies, login } from "./api";
import { ReceivablesOperations } from "./ReceivablesOperations";
import type { Company, Conversation, Finding, Report, ReportMetricValue } from "./types";
import "./health-agent.css";
import "./receivables.css";

type Session = { token: string; userId: number };
type AgentKey = "accounting-health" | "receivables";
type ReceivablesView = "diagnostic" | "operations";
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
};

export function HealthAgentApp() {
  const [session, setSession] = useState<Session | null>(null);
  const [availableCompanies, setAvailableCompanies] = useState<Company[]>([]);
  const [companyId, setCompanyId] = useState("");
  const [activeAgent, setActiveAgent] = useState<AgentKey>("accounting-health");
  const [receivablesView, setReceivablesView] = useState<ReceivablesView>("diagnostic");
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
    setReceivablesView("diagnostic");
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
        : await askReceivables(session.token, companyId, text, conversationId);
      setConversationId(answer.conversation_id);
      if (answer.report) setReport(answer.report);
      setQuestion("");
      setServiceNotice(null);

      if (answer.conversation) {
        const usingFallback = answer.conversation.outcome === "temporarily_unavailable";
        setServiceNotice(usingFallback ? serviceNoticeFor(activeAgent) : null);
        setMessages((current) => [
          ...current,
          {
            id: `a-${Date.now()}`,
            role: "assistant",
            content: usingFallback
              ? fallbackResponseFor(activeAgent, answer.report, answer.conversation.response)
              : answer.conversation.response,
            outcome: answer.conversation.outcome,
            llmUsed: answer.conversation.llm_used,
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
            {activeAgent === "receivables" && receivablesView === "operations" ? "Gestion controlada" : "Solo lectura"}
          </span>
        </header>
        {activeAgent === "receivables" ? (
          <div className="receivables-tabs" role="tablist" aria-label="Vistas de cartera">
            <button
              type="button"
              role="tab"
              aria-selected={receivablesView === "diagnostic"}
              className={receivablesView === "diagnostic" ? "active" : undefined}
              onClick={() => setReceivablesView("diagnostic")}
            >
              Diagnostico
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={receivablesView === "operations"}
              className={receivablesView === "operations" ? "active" : undefined}
              onClick={() => setReceivablesView("operations")}
            >
              Cartera operativa
            </button>
          </div>
        ) : null}
        {activeAgent === "receivables" && receivablesView === "operations" ? (
          <ReceivablesOperations
            key={`${companyId}-${session.userId}`}
            token={session.token}
            companyId={companyId}
            companyName={company?.name || "esta empresa"}
            enabled={Boolean(canUseAgent)}
          />
        ) : (
          <>
        <p className="privacy">
          <b>Protege los datos personales.</b> No incluyas NIT, correos, documentos ni
          credenciales en la conversación. Este agente es de solo lectura.
        </p>
        {activeAgent === "receivables" ? (
          <p id="receivables-chat-scope" className="scope-hint">
            <b>Qué puedes consultar:</b> saldos, vencimientos y antigüedad, pagos,
            seguimientos, promesas y alertas, siempre de forma agregada. Para revisar el
            detalle de una factura, cliente o pago, usa{" "}
            <button
              type="button"
              className="scope-link"
              onClick={() => setReceivablesView("operations")}
            >
              Cartera operativa
            </button>
            .
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
          ) : messages.map((item) => (
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
            aria-describedby={activeAgent === "receivables" ? "receivables-chat-scope" : undefined}
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
              <strong>{report.summary.finding_count} alertas en revisión</strong>
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
        <b>{finding.code.replaceAll("_", " ")}</b>
        <p>{finding.message}</p>
        <small>{finding.recommendation}</small>
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
