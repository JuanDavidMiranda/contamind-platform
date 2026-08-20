"use client";

import { type FormEvent, useCallback, useEffect, useRef, useState } from "react";

import {
  ApiError,
  createDianDataSource,
  dataSources,
  dianAcquirerLookups,
  lookupDianAcquirer,
  revokeDianCredentials,
  saveDianCredentials,
} from "./api";
import type {
  Company,
  DataSource,
  DianAcquirerLookup,
  DianAcquirerLookupAudit,
} from "./types";

type Props = {
  token: string;
  company: Company | undefined;
  enabled: boolean;
};

const sourceStatus: Record<DataSource["status"], string> = {
  pending: "Pendiente de validación",
  active: "Configuración activa",
  failed: "Requiere revisión",
  disabled: "Deshabilitada",
};

const auditStatus: Record<DianAcquirerLookupAudit["status"], string> = {
  succeeded: "Consulta completada",
  failed: "Consulta no completada",
};

const documentTypes = [
  ["13", "Cédula de ciudadanía"],
  ["31", "NIT"],
  ["41", "Pasaporte"],
  ["42", "Documento de identificación extranjero"],
  ["47", "PEP"],
  ["48", "PPT"],
  ["11", "Registro civil"],
  ["12", "Tarjeta de identidad"],
  ["21", "Tarjeta de extranjería"],
  ["22", "Cédula de extranjería"],
  ["50", "NIT de otro país"],
  ["91", "NUI"],
] as const;

const isDianAcquirerPilotSource = (source: DataSource) => (
  source.connector_id === "dian_get_acquirer"
  && source.provider_id === "dian"
  && source.kind === "fiscal_authority"
  && source.mode === "fiscal_service"
);

export function DianConfigurationOperations({ token, company, enabled }: Props) {
  const [sources, setSources] = useState<DataSource[]>([]);
  const [audits, setAudits] = useState<DianAcquirerLookupAudit[]>([]);
  const [auditTotal, setAuditTotal] = useState(0);
  const [selectedSourceId, setSelectedSourceId] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [result, setResult] = useState<DianAcquirerLookup | null>(null);

  const dianSources = sources.filter(isDianAcquirerPilotSource);
  const selectedSource = dianSources.find((source) => source.id === selectedSourceId) || dianSources[0];

  const load = useCallback(async () => {
    if (!enabled || !company) {
      setSources([]);
      setAudits([]);
      setAuditTotal(0);
      setLoading(false);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const [sourceList, auditList] = await Promise.all([
        dataSources(token, company.id),
        dianAcquirerLookups(token, company.id),
      ]);
      const nextDianSources = sourceList.filter(isDianAcquirerPilotSource);
      setSources(sourceList);
      setAudits(auditList.items);
      setAuditTotal(auditList.total);
      setSelectedSourceId((current) => (
        nextDianSources.some((source) => source.id === current) ? current : nextDianSources[0]?.id || ""
      ));
    } catch (cause) {
      setError(messageFor(cause, "No fue posible cargar la configuración DIAN."));
    } finally {
      setLoading(false);
    }
  }, [company, enabled, token]);

  useEffect(() => {
    let disposed = false;
    void Promise.resolve().then(() => {
      if (!disposed) return load();
    });
    return () => { disposed = true; };
  }, [load]);

  if (!enabled || !company) {
    return (
      <section className="dian-operations unavailable">
        <p className="eyebrow">CONFIGURACIÓN DIAN</p>
        <h2>La empresa está desactivada.</h2>
        <p>Reactiva la empresa para configurar el piloto de consulta de adquirientes.</p>
      </section>
    );
  }

  async function createSource() {
    if (!company) return;
    setError(null);
    setNotice(null);
    try {
      const source = await createDianDataSource(token, company);
      setSources((current) => [...current, source]);
      setSelectedSourceId(source.id);
      setNotice("La fuente DIAN fue creada. Carga las credenciales para continuar.");
    } catch (cause) {
      setError(messageFor(cause, "No fue posible crear la fuente DIAN."));
    }
  }

  async function credentialsSaved() {
    setNotice("Credenciales guardadas de forma cifrada. La fuente queda pendiente de una consulta controlada.");
    await load();
  }

  async function lookupCompleted(nextResult: DianAcquirerLookup) {
    setResult(nextResult);
    setNotice("La consulta fue registrada sin conservar el documento ni los datos devueltos.");
    await load();
  }

  return (
    <section className="dian-operations" aria-labelledby="dian-operations-title">
      <header className="operations-heading">
        <div>
          <p className="eyebrow">PILOTO DIAN · CONSULTA INDIVIDUAL</p>
          <h2 id="dian-operations-title">Consulta de adquirientes</h2>
          <p>Completa nombre y correo durante la expedición. Esta fuente no se reutiliza para la habilitación de software propio.</p>
        </div>
        <button className="quiet-button" type="button" onClick={() => void load()} disabled={loading}>
          {loading ? "Actualizando…" : "Actualizar"}
        </button>
      </header>

      <p className="operations-privacy">
        Esta configuración no se comparte con el asistente. Los secretos se cifran por empresa y la consulta está limitada a una factura a la vez. No transmite documentos ni activa producción.
      </p>

      {error ? <p className="operations-error" role="alert">{error}</p> : null}
      {notice ? <p className="dian-notice" role="status">{notice}</p> : null}
      {loading ? <p className="operations-loading">Cargando configuración DIAN…</p> : null}

      {!loading && !dianSources.length ? (
        <section className="dian-empty">
          <h3>Primero registra la fuente DIAN</h3>
          <p>Solo un propietario o administrador puede crearla. Esta fuente solo sirve para el piloto de consulta y no habilita la emisión ni producción.</p>
          <button className="secondary-action" type="button" onClick={() => void createSource()}>
            Crear fuente DIAN
          </button>
        </section>
      ) : null}

      {dianSources.length ? (
        <>
          <section className="dian-source-card" aria-label="Estado de la fuente DIAN">
            <div>
              <span>Fuente configurada</span>
              {dianSources.length > 1 ? (
                <select value={selectedSource?.id || ""} onChange={(event) => setSelectedSourceId(event.target.value)}>
                  {dianSources.map((source) => <option key={source.id} value={source.id}>{source.display_name}</option>)}
                </select>
              ) : <strong>{selectedSource?.display_name}</strong>}
            </div>
            {selectedSource ? <b className={`dian-status ${selectedSource.status}`}>{sourceStatus[selectedSource.status]}</b> : null}
          </section>

          {selectedSource ? (
            <DianCredentialsForm
              token={token}
              source={selectedSource}
              onSaved={credentialsSaved}
              onRevoked={async () => {
                setResult(null);
                setNotice("Las credenciales fueron revocadas. La fuente quedó deshabilitada.");
                await load();
              }}
              onError={setError}
            />
          ) : null}

          {selectedSource?.credential_reference && selectedSource.status !== "disabled" ? (
            <DianLookupForm
              token={token}
              companyId={company.id}
              dataSourceId={selectedSource.id}
              onCompleted={lookupCompleted}
              onError={setError}
            />
          ) : (
            <p className="dian-next-step">Carga las credenciales cifradas para habilitar una consulta individual de prueba.</p>
          )}
        </>
      ) : null}

      {result ? (
        <section className="dian-result" aria-live="polite">
          <p className="eyebrow">RESULTADO EFÍMERO</p>
          <h3>{result.name}</h3>
          <p>{result.email || "DIAN no devolvió correo electrónico para esta consulta."}</p>
          <small>Este resultado no se guarda en ContaMind. Úsalo únicamente al emitir la factura correspondiente.</small>
        </section>
      ) : null}

      <section className="dian-audit" aria-labelledby="dian-audit-title">
        <h3 id="dian-audit-title">Trazabilidad de consultas</h3>
        <p>{auditTotal} consulta{auditTotal === 1 ? "" : "s"} registrada{auditTotal === 1 ? "" : "s"}. No se muestran documentos ni datos de adquirientes.</p>
        {audits.length ? (
          <ul>
            {audits.map((audit) => (
              <li key={audit.id}>
                <div><b>{auditStatus[audit.status]}</b><span>Tipo de documento {audit.document_type}</span></div>
                <time dateTime={audit.requested_at}>{formatDateTime(audit.requested_at)}</time>
                {audit.error_code ? <small>{errorLabel(audit.error_code)}</small> : null}
              </li>
            ))}
          </ul>
        ) : <p className="history-empty">Aún no hay consultas registradas para esta empresa.</p>}
      </section>
    </section>
  );
}

function DianCredentialsForm({ token, source, onSaved, onRevoked, onError }: {
  token: string;
  source: DataSource;
  onSaved: () => Promise<void>;
  onRevoked: () => Promise<void>;
  onError: (message: string | null) => void;
}) {
  const formRef = useRef<HTMLFormElement>(null);
  const softwareIdRef = useRef<HTMLInputElement>(null);
  const softwarePasswordRef = useRef<HTMLInputElement>(null);
  const certificateRef = useRef<HTMLInputElement>(null);
  const certificatePasswordRef = useRef<HTMLInputElement>(null);
  const [saving, setSaving] = useState(false);
  const [revoking, setRevoking] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const file = certificateRef.current?.files?.[0];
    const softwareId = softwareIdRef.current?.value.trim();
    const softwarePassword = softwarePasswordRef.current?.value;
    const certificatePassword = certificatePasswordRef.current?.value;
    if (!file || !softwareId || !softwarePassword || !certificatePassword) return;
    if (file.size > 750_000) {
      onError("El certificado supera el tamaño permitido para una carga segura.");
      return;
    }
    setSaving(true);
    onError(null);
    try {
      const certificate = await fileToBase64(file);
      await saveDianCredentials(token, source.id, {
        software_id: softwareId,
        software_password: softwarePassword,
        certificate_pfx_base64: certificate,
        certificate_password: certificatePassword,
      });
      formRef.current?.reset();
      await onSaved();
    } catch (cause) {
      formRef.current?.reset();
      onError(messageFor(cause, "No fue posible guardar las credenciales DIAN."));
    } finally {
      setSaving(false);
    }
  }

  async function revoke() {
    if (!window.confirm("¿Confirmas que deseas revocar las credenciales DIAN de esta empresa?")) return;
    setRevoking(true);
    onError(null);
    try {
      await revokeDianCredentials(token, source.id);
      await onRevoked();
    } catch (cause) {
      onError(messageFor(cause, "No fue posible revocar las credenciales DIAN."));
    } finally {
      setRevoking(false);
    }
  }

  return (
    <form ref={formRef} className="operations-form dian-credentials-form" onSubmit={submit}>
      <div className="form-heading"><h3>Credenciales y certificado</h3><p>Se transfieren directamente al almacén cifrado. Nunca aparecen nuevamente en esta pantalla.</p></div>
      <label>ID del software (usuario Basic)<input ref={softwareIdRef} name="software_id" autoComplete="off" required maxLength={255} /></label>
      <label>PIN o contraseña del software (Basic)<input ref={softwarePasswordRef} name="software_password" type="password" autoComplete="new-password" required maxLength={4096} /></label>
      <label>Certificado de pertenencia (.pfx o .p12)<input ref={certificateRef} name="certificate" type="file" accept=".pfx,.p12,application/x-pkcs12" required /></label>
      <label>Contraseña del certificado<input ref={certificatePasswordRef} name="certificate_password" type="password" autoComplete="new-password" required maxLength={4096} /></label>
      <p className="note-warning"><b>Antes de continuar:</b> usa el ID/PIN del software registrado, un certificado vigente de la empresa y las credenciales del ambiente correcto. No cargues archivos ni secretos en el chat.</p>
      <div className="dian-form-actions">
        <button className="secondary-action" disabled={saving}>{saving ? "Cifrando y guardando…" : source.credential_reference ? "Actualizar credenciales" : "Guardar credenciales"}</button>
        {source.credential_reference ? <button className="dian-revoke" type="button" onClick={() => void revoke()} disabled={revoking}>{revoking ? "Revocando…" : "Revocar credenciales"}</button> : null}
      </div>
    </form>
  );
}

function DianLookupForm({ token, companyId, dataSourceId, onCompleted, onError }: {
  token: string;
  companyId: string;
  dataSourceId: string;
  onCompleted: (result: DianAcquirerLookup) => Promise<void>;
  onError: (message: string | null) => void;
}) {
  const formRef = useRef<HTMLFormElement>(null);
  const [documentType, setDocumentType] = useState("31");
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = formRef.current;
    const documentNumber = (new FormData(form || undefined).get("document_number") as string | null)?.trim();
    if (!documentNumber) return;
    setBusy(true);
    onError(null);
    try {
      const response = await lookupDianAcquirer(token, companyId, {
        data_source_id: dataSourceId,
        document_type: documentType,
        document_number: documentNumber,
        purpose: "electronic_invoice_issuance",
        confirmed: true,
      });
      form?.reset();
      setDocumentType("31");
      await onCompleted(response);
    } catch (cause) {
      form?.reset();
      onError(messageFor(cause, "No fue posible consultar el adquiriente."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form ref={formRef} className="operations-form dian-lookup-form" onSubmit={submit}>
      <div className="form-heading"><h3>Consulta individual para facturar</h3><p>Solo úsala mientras expides la factura o documento equivalente electrónico correspondiente.</p></div>
      <div className="dian-query-fields">
        <label>Tipo de documento<select value={documentType} onChange={(event) => setDocumentType(event.target.value)}>{documentTypes.map(([value, label]) => <option key={value} value={value}>{value} · {label}</option>)}</select></label>
        <label>Número de documento<input name="document_number" autoComplete="off" inputMode="text" pattern="[A-Za-z0-9-]{1,50}" required maxLength={50} /></label>
      </div>
      <label className="check-line confirm-line"><input type="checkbox" required />Confirmo que esta consulta se usará únicamente para emitir la factura electrónica en curso y no para enriquecer bases de datos.</label>
      <button className="secondary-action" disabled={busy}>{busy ? "Consultando…" : "Consultar adquiriente"}</button>
    </form>
  );
}

async function fileToBase64(file: File): Promise<string> {
  const bytes = new Uint8Array(await file.arrayBuffer());
  let binary = "";
  for (let offset = 0; offset < bytes.length; offset += 8_192) {
    binary += String.fromCharCode(...bytes.subarray(offset, offset + 8_192));
  }
  return btoa(binary);
}

function formatDateTime(value: string) {
  const parsed = new Date(value);
  return Number.isNaN(parsed.valueOf()) ? value : new Intl.DateTimeFormat("es-CO", { dateStyle: "medium", timeStyle: "short", timeZone: "America/Bogota" }).format(parsed);
}

function errorLabel(code: string) {
  const labels: Record<string, string> = {
    DEPENDENCY_DISABLED: "La integración DIAN permanece deshabilitada en este ambiente.",
    PROVIDER_AUTH_FAILED: "DIAN no aceptó las credenciales configuradas.",
    PROVIDER_UNREACHABLE: "No fue posible comunicarse con DIAN.",
    PROVIDER_ERROR: "DIAN rechazó o no pudo procesar la consulta.",
    VALIDATION_ERROR: "La configuración o la consulta requiere corrección.",
  };
  return labels[code] || "La consulta requiere revisión técnica.";
}

function messageFor(cause: unknown, fallback: string) {
  return cause instanceof ApiError || cause instanceof Error ? cause.message : fallback;
}
