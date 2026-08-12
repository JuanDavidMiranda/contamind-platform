"use client";

import { type FormEvent, useState } from "react";

import { ApiError, askHealth, companies, login } from "./api";
import type { Company, Conversation, Finding, Report } from "./types";
import "./health-agent.css";

type Session = { token: string; userId: number };
type Message = {
  id: string;
  role: "user" | "assistant";
  content: string;
  outcome?: Conversation["outcome"];
  llmUsed?: boolean;
};

const prompts = [
  "¿Qué debo revisar primero?",
  "¿Qué significa cada alerta?",
  "¿Cómo corrijo un comprobante descuadrado?",
];
const metricLabels: Array<[string, string]> = [
  ["data_sources", "Fuentes"],
  ["parties", "Terceros"],
  ["invoices", "Facturas"],
  ["payments", "Pagos"],
  ["journal_entries", "Comprobantes"],
];

export function HealthAgentApp() {
  const [session, setSession] = useState<Session | null>(null);
  const [availableCompanies, setAvailableCompanies] = useState<Company[]>([]);
  const [companyId, setCompanyId] = useState("");
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [report, setReport] = useState<Report | null>(null);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [question, setQuestion] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const company = availableCompanies.find((item) => item.id === companyId);
  const canUseAgent = company?.status === "active";

  async function signIn(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError(null);

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
      const answer = await askHealth(session.token, companyId, text, conversationId);
      setConversationId(answer.conversation_id);
      if (answer.report) setReport(answer.report);
      setQuestion("");

      if (answer.conversation) {
        setMessages((current) => [
          ...current,
          {
            id: `a-${Date.now()}`,
            role: "assistant",
            content: answer.conversation.response,
            outcome: answer.conversation.outcome,
            llmUsed: answer.conversation.llm_used,
          },
        ]);
      }
    } catch (cause) {
      const problem = messageFor(cause, "No fue posible consultar la salud contable.");
      setError(problem);
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
          <p className="eyebrow">CONTAMIND · SALUD CONTABLE</p>
          <h1>Entiende qué necesita atención, con evidencia.</h1>
          <p>
            Consulta prioridades, interpreta alertas y revisa la calidad de tus datos
            contables desde un único espacio.
          </p>
          <ul>
            <li>Diagnóstico de solo lectura</li>
            <li>Hallazgos y métricas verificables</li>
            <li>Conversación acotada a salud contable</li>
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
        <nav aria-label="Módulos disponibles">
          <span className="active">Salud contable</span>
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
            <p className="eyebrow">AGENTE DE SALUD CONTABLE</p>
            <h1>Una conversación para revisar lo importante.</h1>
          </div>
          <span className="readonly">Solo lectura</span>
        </header>
        <p className="privacy">
          <b>Protege los datos personales.</b> No incluyas NIT, correos, documentos ni
          credenciales en la conversación.
        </p>

        <div className="messages" aria-live="polite">
          {messages.length === 0 ? (
            <div className="empty">
              <span className="orb">✦</span>
              <h2>
                {!company
                  ? "No tienes empresas disponibles."
                  : canUseAgent
                    ? "¿Por dónde quieres empezar?"
                    : "Esta empresa está desactivada."}
              </h2>
              <p>
                {!company
                  ? "Cuando un administrador te asigne una empresa, podrás consultar su salud contable aquí."
                  : canUseAgent
                    ? `Revisaré los hallazgos actuales de ${company.name} y te devolveré la evidencia disponible.`
                    : "Reactiva la empresa para poder iniciar una consulta de salud contable."}
              </p>
              {canUseAgent ? (
                <div className="prompts">
                  {prompts.map((prompt) => (
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
                    {outcomeText(item.outcome)} · {item.llmUsed ? "Explicación asistida" : "Diagnóstico verificado"}
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
            placeholder={canUseAgent ? "Pregunta sobre la salud contable…" : "Selecciona una empresa activa para comenzar"}
          />
          <button className="primary" disabled={!question.trim() || !canUseAgent || busy}>
            {busy ? "…" : "Enviar"}
          </button>
        </form>
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
                {metricLabels.map(([key, label]) => (
                  <div key={key}><dt>{label}</dt><dd>{report.metrics[key] ?? 0}</dd></div>
                ))}
              </dl>
            </section>
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

function outcomeText(outcome: Conversation["outcome"]) {
  return {
    answered: "Respuesta disponible",
    clarification_needed: "Reformula la consulta",
    out_of_scope: "Fuera del alcance",
    temporarily_unavailable: "Explicación temporalmente no disponible",
  }[outcome];
}
