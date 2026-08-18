"use client";

import { type FormEvent, useCallback, useEffect, useState } from "react";

import {
  ApiError,
  electronicInvoiceEvidenceImportRows,
  electronicInvoiceEvidenceImports,
  electronicInvoiceExceptions,
  importElectronicInvoiceEvidence,
} from "./api";
import type {
  ElectronicInvoiceEvidenceImport,
  ElectronicInvoiceEvidenceImportResult,
  ElectronicInvoiceEvidenceImportRow,
  ElectronicInvoiceException,
} from "./types";


type Props = {
  token: string;
  companyId: string;
  companyName: string;
  enabled: boolean;
};

const statusLabels: Record<string, string> = {
  accepted: "Aceptada",
  validated: "Validada",
  approved: "Aprobada",
  dian_accepted: "Aceptada por DIAN",
  draft: "Borrador",
  issued: "Emitida",
  sent: "Enviada",
  submitted: "Radicada",
  pending: "Pendiente",
  processing: "En proceso",
  rejected: "Rechazada",
  error: "Con error",
  failed: "Fallida",
  invalid: "Inválida",
};

const issueLabels: Record<string, string> = {
  ELECTRONIC_STATUS_REJECTED: "Estado electrónico rechazado o con error",
  ELECTRONIC_STATUS_PENDING: "Estado electrónico pendiente",
  ELECTRONIC_STATUS_MISSING: "Sin estado electrónico",
  ELECTRONIC_REFERENCE_MISSING: "Sin referencia electrónica",
  INVOICE_NUMBER_MISSING: "Sin consecutivo",
  RECIPIENT_MISSING: "Sin adquiriente asociado",
  TOTAL_MISMATCH: "Total contable inconsistente",
  FUTURE_ISSUE_DATE: "Fecha de emisión futura",
};

export function ElectronicInvoicingOperations({ token, companyId, companyName, enabled }: Props) {
  const [exceptions, setExceptions] = useState<ElectronicInvoiceException[]>([]);
  const [total, setTotal] = useState(0);
  const [canImport, setCanImport] = useState(false);
  const [imports, setImports] = useState<ElectronicInvoiceEvidenceImport[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [importResult, setImportResult] = useState<ElectronicInvoiceEvidenceImportResult | null>(null);
  const [auditImportId, setAuditImportId] = useState<string | null>(null);
  const [auditRows, setAuditRows] = useState<ElectronicInvoiceEvidenceImportRow[]>([]);
  const [auditLoading, setAuditLoading] = useState(false);

  const load = useCallback(async () => {
    if (!enabled) {
      setExceptions([]);
      setImports([]);
      setTotal(0);
      setLoading(false);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const [exceptionPage, importPage] = await Promise.all([
        electronicInvoiceExceptions(token, companyId, { limit: 100 }),
        electronicInvoiceEvidenceImports(token, companyId),
      ]);
      setExceptions(exceptionPage.items);
      setTotal(exceptionPage.total);
      setImports(importPage.items);
      setCanImport(exceptionPage.can_import && importPage.can_import);
    } catch (cause) {
      setError(messageFor(cause, "No fue posible cargar la revisión operativa."));
    } finally {
      setLoading(false);
    }
  }, [companyId, enabled, token]);

  useEffect(() => {
    let disposed = false;
    void Promise.resolve().then(() => {
      if (!disposed) return load();
    });
    return () => { disposed = true; };
  }, [load]);

  async function openAudit(importId: string) {
    setAuditImportId(importId);
    setAuditLoading(true);
    setError(null);
    try {
      const response = await electronicInvoiceEvidenceImportRows(token, companyId, importId);
      setAuditRows(response.items);
    } catch (cause) {
      setAuditRows([]);
      setError(messageFor(cause, "No fue posible cargar la auditoría de la importación."));
    } finally {
      setAuditLoading(false);
    }
  }

  if (!enabled) {
    return (
      <section className="electronic-operations unavailable">
        <p className="eyebrow">FACTURACIÓN ELECTRÓNICA OPERATIVA</p>
        <h2>La empresa está desactivada.</h2>
        <p>Reactiva {companyName} para importar evidencia y revisar excepciones.</p>
      </section>
    );
  }

  return (
    <section className="electronic-operations" aria-labelledby="electronic-operations-title">
      <header className="operations-heading">
        <div>
          <p className="eyebrow">FACTURACIÓN ELECTRÓNICA OPERATIVA</p>
          <h2 id="electronic-operations-title">Evidencia y excepciones</h2>
          <p>{total} factura{total === 1 ? "" : "s"} que requiere{total === 1 ? "" : "n"} revisión.</p>
        </div>
        <button className="quiet-button" type="button" onClick={() => void load()} disabled={loading}>
          {loading ? "Actualizando…" : "Actualizar"}
        </button>
      </header>

      <p className="operations-privacy">
        Esta vista no comparte referencias electrónicas ni datos de adquirientes con el asistente. La conexión en tiempo real con la DIAN aún no está habilitada.
      </p>

      {canImport ? (
        <EvidenceImportForm
          token={token}
          companyId={companyId}
          onImported={async (result) => {
            setImportResult(result);
            await load();
            await openAudit(result.import_id);
          }}
        />
      ) : (
        <p className="operations-privacy">Tu rol permite consultar las excepciones, pero no cargar evidencia.</p>
      )}

      {importResult ? (
        <section className="electronic-import-result" role="status">
          <b>Importación terminada.</b> {importResult.accepted_rows} aceptadas, {importResult.duplicate_rows} duplicadas y {importResult.rejections.length} rechazadas.
          {importResult.rejections.length ? (
            <ul>
              {importResult.rejections.map((rejection) => <li key={`${rejection.row_number}-${rejection.message}`}>Fila {rejection.row_number}: {rejection.message}</li>)}
            </ul>
          ) : null}
        </section>
      ) : null}

      {error ? <p className="operations-error" role="alert">{error}</p> : null}
      {loading ? <p className="operations-loading">Cargando evidencia y excepciones…</p> : null}

      {!loading && !exceptions.length ? (
        <div className="operations-empty">
          <h3>No hay excepciones pendientes.</h3>
          <p>Las facturas de venta disponibles tienen estado aceptado, referencia registrada y datos contables consistentes.</p>
        </div>
      ) : null}

      {exceptions.length ? (
        <div className="electronic-exception-list">
          {exceptions.map((item) => <ExceptionCard key={item.invoice_id} item={item} />)}
        </div>
      ) : null}

      {imports.length ? (
        <section className="electronic-audit" aria-labelledby="electronic-audit-title">
          <h3 id="electronic-audit-title">Auditoría de cargas</h3>
          <p>Se conserva el resultado por fila, no el contenido sensible del archivo.</p>
          <ul>
            {imports.map((item) => (
              <li key={item.id}>
                <span>{formatDateTime(item.created_at)} · {item.file_format.toUpperCase()}</span>
                <small>{item.accepted_rows} aceptadas · {item.duplicate_rows} duplicadas · {item.rejected_rows} rechazadas</small>
                <button type="button" onClick={() => void openAudit(item.id)}>{auditImportId === item.id ? "Ver auditoría" : "Abrir auditoría"}</button>
              </li>
            ))}
          </ul>
          {auditImportId ? (
            <div className="electronic-audit-rows">
              <h4>Resultado por fila</h4>
              {auditLoading ? <p>Consultando auditoría…</p> : auditRows.length ? (
                <ul>
                  {auditRows.map((row) => <li key={`${row.row_number}-${row.outcome}`}><b>Fila {row.row_number}</b> · {outcomeText(row.outcome)}{row.reason ? `: ${row.reason}` : ""}</li>)}
                </ul>
              ) : <p>No hay filas disponibles para esta importación.</p>}
            </div>
          ) : null}
        </section>
      ) : null}
    </section>
  );
}

function EvidenceImportForm({ token, companyId, onImported }: {
  token: string;
  companyId: string;
  onImported: (result: ElectronicInvoiceEvidenceImportResult) => Promise<void>;
}) {
  const [file, setFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!file) return;
    setUploading(true);
    setError(null);
    try {
      const result = await importElectronicInvoiceEvidence(token, companyId, file);
      setFile(null);
      await onImported(result);
    } catch (cause) {
      setError(messageFor(cause, "No fue posible importar la evidencia."));
    } finally {
      setUploading(false);
    }
  }

  return (
    <form className="operations-form electronic-import-form" onSubmit={submit}>
      <h3>Importar evidencia</h3>
      <p>Admite CSV o XLSX. Obligatorias: <b>número de factura</b> y <b>estado electrónico</b>. Opcionales: referencia electrónica (CUFE/CUDE) y fecha de respuesta ISO 8601.</p>
      <label>Archivo<input type="file" accept=".csv,.xlsx,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" onChange={(event) => setFile(event.target.files?.[0] || null)} required /></label>
      <p className="note-warning"><b>Revisa antes de cargar.</b> La carga actualiza estados de facturas de venta existentes; no transmite ni valida documentos ante la DIAN.</p>
      {error ? <p className="form-error" role="alert">{error}</p> : null}
      <button className="secondary-action" disabled={!file || uploading}>{uploading ? "Importando…" : "Importar evidencia"}</button>
    </form>
  );
}

function ExceptionCard({ item }: { item: ElectronicInvoiceException }) {
  return (
    <article className="electronic-exception">
      <div className="electronic-exception-heading">
        <div>
          <time dateTime={item.issue_date}>{formatDate(item.issue_date)}</time>
          <strong>{item.invoice_number || "Factura sin consecutivo"}</strong>
        </div>
        <span className="electronic-status">{item.electronic_status ? statusLabels[item.electronic_status] || "Estado sin clasificar" : "Sin estado electrónico"}</span>
      </div>
      <small>{item.has_electronic_reference ? "Referencia electrónica registrada" : "Sin referencia electrónica registrada"}</small>
      <ul>{item.issue_codes.map((code) => <li key={code}>{issueLabels[code] || code}</li>)}</ul>
    </article>
  );
}

function formatDate(value: string) {
  const parsed = new Date(`${value.slice(0, 10)}T00:00:00Z`);
  return Number.isNaN(parsed.valueOf()) ? value : new Intl.DateTimeFormat("es-CO", { dateStyle: "medium", timeZone: "UTC" }).format(parsed);
}

function formatDateTime(value: string) {
  const parsed = new Date(value);
  return Number.isNaN(parsed.valueOf()) ? value : new Intl.DateTimeFormat("es-CO", { dateStyle: "short", timeZone: "America/Bogota" }).format(parsed);
}

function outcomeText(value: ElectronicInvoiceEvidenceImportRow["outcome"]) {
  return value === "accepted" ? "Aceptada" : value === "duplicate" ? "Duplicada" : "Rechazada";
}

function messageFor(cause: unknown, fallback: string) {
  return cause instanceof ApiError || cause instanceof Error ? cause.message : fallback;
}
