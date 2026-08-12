"use client";

import { type FormEvent, useCallback, useEffect, useMemo, useState } from "react";

import {
  ApiError,
  collectionFollowUps,
  createCollectionFollowUp,
  openReceivables,
  updateCollectionFollowUp,
  updateInvoiceTerms,
} from "./api";
import type {
  CollectionFollowUp,
  CollectionFollowUpStatus,
  InvoiceTermsUpdate,
  OpenReceivableItem,
} from "./types";

type ReceivablesOperationsProps = {
  token: string;
  companyId: string;
  companyName: string;
  enabled: boolean;
};

const PAGE_SIZE = 50;

const followUpLabels: Record<CollectionFollowUpStatus, string> = {
  pending: "Pendiente",
  contacted: "Contactado",
  promise_to_pay: "Promesa de pago",
  resolved: "Resuelto",
  cancelled: "Cancelado",
};

export function ReceivablesOperations({
  token,
  companyId,
  companyName,
  enabled,
}: ReceivablesOperationsProps) {
  const [items, setItems] = useState<OpenReceivableItem[]>([]);
  const [total, setTotal] = useState(0);
  const [asOf, setAsOf] = useState<string | null>(null);
  const [canManage, setCanManage] = useState(false);
  const [selectedInvoiceId, setSelectedInvoiceId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadFirstPage = useCallback(async () => {
    if (!enabled) {
      setItems([]);
      setTotal(0);
      setAsOf(null);
      setCanManage(false);
      setSelectedInvoiceId(null);
      setLoading(false);
      return;
    }

    setLoading(true);
    setError(null);
    try {
      const page = await openReceivables(token, companyId, { limit: PAGE_SIZE, offset: 0 });
      setItems(page.items);
      setTotal(page.total);
      setAsOf(page.as_of);
      setCanManage(page.can_manage);
      setSelectedInvoiceId((current) => (
        page.items.some((item) => item.invoice_id === current)
          ? current
          : page.items[0]?.invoice_id ?? null
      ));
    } catch (cause) {
      setError(messageFor(cause, "No fue posible cargar la cartera operativa."));
      setItems([]);
      setTotal(0);
      setSelectedInvoiceId(null);
    } finally {
      setLoading(false);
    }
  }, [companyId, enabled, token]);

  useEffect(() => {
    void loadFirstPage();
  }, [loadFirstPage]);

  const selectedItem = useMemo(
    () => items.find((item) => item.invoice_id === selectedInvoiceId) ?? null,
    [items, selectedInvoiceId],
  );

  async function loadMore() {
    if (loadingMore || items.length >= total) return;
    setLoadingMore(true);
    setError(null);
    try {
      const page = await openReceivables(token, companyId, { limit: PAGE_SIZE, offset: items.length });
      setItems((current) => [...current, ...page.items.filter((item) => !current.some((existing) => existing.invoice_id === item.invoice_id))]);
    } catch (cause) {
      setError(messageFor(cause, "No fue posible cargar más facturas."));
    } finally {
      setLoadingMore(false);
    }
  }

  if (!enabled) {
    return (
      <section className="receivables-operations unavailable" aria-labelledby="operations-title">
        <p className="eyebrow">CARTERA OPERATIVA</p>
        <h2 id="operations-title">La empresa está desactivada.</h2>
        <p>Reactiva {companyName} para consultar y registrar seguimientos de cartera.</p>
      </section>
    );
  }

  return (
    <section className="receivables-operations" aria-labelledby="operations-title">
      <header className="operations-heading">
        <div>
          <p className="eyebrow">CARTERA OPERATIVA</p>
          <h2 id="operations-title">Facturas de venta con saldo</h2>
          <p>
            {asOf ? `Corte al ${formatDate(asOf)}.` : "Consulta los saldos pendientes por factura."}
            {total ? ` ${total} en total.` : ""}
          </p>
        </div>
        <button className="quiet-button" type="button" onClick={() => void loadFirstPage()} disabled={loading}>
          {loading ? "Actualizando…" : "Actualizar"}
        </button>
      </header>

      <p className="operations-privacy">
        Esta vista no envía datos al asistente. Los cambios y seguimientos requieren confirmación explícita y quedan asociados a tu usuario.
      </p>

      {error ? (
        <div className="operations-error" role="alert">
          <p>{error}</p>
          <button className="quiet-button" type="button" onClick={() => void loadFirstPage()}>Reintentar</button>
        </div>
      ) : null}

      {loading ? <p className="operations-loading" role="status">Cargando cartera…</p> : null}

      {!loading && !error && items.length === 0 ? (
        <div className="operations-empty">
          <span aria-hidden="true">✓</span>
          <h3>No hay facturas de venta con saldo pendiente.</h3>
          <p>Cuando exista cartera abierta, podrás revisarla y registrar su seguimiento aquí.</p>
        </div>
      ) : null}

      {!loading && items.length ? (
        <>
          <div className="receivables-table-wrap">
            <table className="receivables-table">
              <caption className="sr-only">Facturas de venta con saldo pendiente</caption>
              <thead>
                <tr>
                  <th scope="col">Factura</th>
                  <th scope="col">Vencimiento</th>
                  <th scope="col">Saldo</th>
                  <th scope="col">Estado</th>
                  <th scope="col"><span className="sr-only">Acción</span></th>
                </tr>
              </thead>
              <tbody>
                {items.map((item) => {
                  const selected = item.invoice_id === selectedInvoiceId;
                  return (
                    <tr key={item.invoice_id} className={selected ? "selected" : undefined}>
                      <td>
                        <strong>{item.invoice_number || "Sin consecutivo"}</strong>
                        <small>Emitida {formatDate(item.issue_date)}</small>
                      </td>
                      <td>
                        <span>{item.due_date ? formatDate(item.due_date) : "Sin vencimiento"}</span>
                        {item.days_overdue && item.days_overdue > 0 ? <small>{item.days_overdue} días vencida</small> : null}
                      </td>
                      <td>
                        <strong>{formatMoney(item.outstanding_amount, item.currency_code)}</strong>
                        {item.paid_amount !== "0" && item.paid_amount !== "0.00" ? <small>Pagado: {formatMoney(item.paid_amount, item.currency_code)}</small> : null}
                      </td>
                      <td>
                        <span className={`aging-pill ${item.aging_bucket}`}>{agingLabel(item.aging_bucket)}</span>
                        {item.latest_followup_status ? <small className="followup-summary">{followUpLabels[item.latest_followup_status]}</small> : null}
                      </td>
                      <td>
                        <button
                          className="row-action"
                          type="button"
                          onClick={() => setSelectedInvoiceId(item.invoice_id)}
                          aria-pressed={selected}
                        >
                          {selected ? "Seleccionada" : "Gestionar"}
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          {items.length < total ? (
            <button className="load-more" type="button" onClick={() => void loadMore()} disabled={loadingMore}>
              {loadingMore ? "Cargando…" : `Mostrar más (${total - items.length})`}
            </button>
          ) : null}
        </>
      ) : null}

      {selectedItem ? (
        <InvoiceDetail
          key={selectedItem.invoice_id}
          item={selectedItem}
          token={token}
          companyId={companyId}
          canManage={canManage}
          onChanged={loadFirstPage}
        />
      ) : null}
    </section>
  );
}

type InvoiceDetailProps = {
  item: OpenReceivableItem;
  token: string;
  companyId: string;
  canManage: boolean;
  onChanged: () => Promise<void>;
};

function InvoiceDetail({ item, token, companyId, canManage, onChanged }: InvoiceDetailProps) {
  const [followUps, setFollowUps] = useState<CollectionFollowUp[]>([]);
  const [loadingFollowUps, setLoadingFollowUps] = useState(true);
  const [followUpError, setFollowUpError] = useState<string | null>(null);

  const loadFollowUps = useCallback(async () => {
    setLoadingFollowUps(true);
    setFollowUpError(null);
    try {
      const records = await collectionFollowUps(token, companyId, item.invoice_id);
      setFollowUps(records);
    } catch (cause) {
      setFollowUpError(messageFor(cause, "No fue posible cargar los seguimientos."));
      setFollowUps([]);
    } finally {
      setLoadingFollowUps(false);
    }
  }, [companyId, item.invoice_id, token]);

  useEffect(() => {
    void loadFollowUps();
  }, [loadFollowUps]);

  async function handleTermsUpdate(payload: InvoiceTermsUpdate) {
    await updateInvoiceTerms(token, companyId, item.invoice_id, payload);
    await onChanged();
  }

  async function handleFollowUpChanged() {
    await Promise.all([onChanged(), loadFollowUps()]);
  }

  return (
    <article className="invoice-detail" aria-labelledby="selected-invoice-title">
      <header>
        <div>
          <p className="eyebrow">FACTURA SELECCIONADA</p>
          <h3 id="selected-invoice-title">{item.invoice_number || "Factura sin consecutivo"}</h3>
        </div>
        <strong>{formatMoney(item.outstanding_amount, item.currency_code)}</strong>
      </header>

      <dl className="invoice-facts">
        <div><dt>Emitida</dt><dd>{formatDate(item.issue_date)}</dd></div>
        <div><dt>Vence</dt><dd>{item.due_date ? formatDate(item.due_date) : "Sin vencimiento"}</dd></div>
        <div><dt>Plazo</dt><dd>{item.payment_terms_days === null ? "Sin definir" : `${item.payment_terms_days} días`}</dd></div>
        <div><dt>Pagado</dt><dd>{formatMoney(item.paid_amount, item.currency_code)}</dd></div>
      </dl>

      {item.mismatched_payment_count ? (
        <p className="mismatch-warning">Hay {item.mismatched_payment_count} pago{item.mismatched_payment_count === 1 ? "" : "s"} en otra moneda que no reduce este saldo.</p>
      ) : null}

      {canManage ? (
        <TermsForm item={item} onSave={handleTermsUpdate} />
      ) : (
        <p className="read-only-notice">Tu rol permite consultar esta cartera, pero no registrar cambios ni seguimientos.</p>
      )}

      <FollowUpPanel
        item={item}
        followUps={followUps}
        loading={loadingFollowUps}
        error={followUpError}
        canManage={canManage}
        token={token}
        companyId={companyId}
        onRetry={loadFollowUps}
        onChanged={handleFollowUpChanged}
      />
    </article>
  );
}

function TermsForm({ item, onSave }: { item: OpenReceivableItem; onSave: (payload: InvoiceTermsUpdate) => Promise<void> }) {
  const [dueDate, setDueDate] = useState(item.due_date || "");
  const [termsDays, setTermsDays] = useState(item.payment_terms_days?.toString() || "");
  const [clearTerms, setClearTerms] = useState(false);
  const [confirmed, setConfirmed] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setDueDate(item.due_date || "");
    setTermsDays(item.payment_terms_days?.toString() || "");
  }, [item.due_date, item.payment_terms_days]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const normalizedTerms = termsDays.trim();
    if (!clearTerms && !dueDate && !normalizedTerms) {
      setError("Indica una fecha de vencimiento, un plazo de pago o selecciona la limpieza explícita.");
      return;
    }
    const parsedTerms = Number(normalizedTerms);
    if (!clearTerms && normalizedTerms && (!Number.isInteger(parsedTerms) || parsedTerms < 0 || parsedTerms > 3650)) {
      setError("El plazo debe ser un número entero entre 0 y 3650 días.");
      return;
    }
    if (!confirmed) return;

    setSaving(true);
    setError(null);
    try {
      const payload: InvoiceTermsUpdate = clearTerms
        ? { due_date: null, payment_terms_days: null, confirmed: true }
        : {
          ...(dueDate ? { due_date: dueDate } : {}),
          ...(normalizedTerms ? { payment_terms_days: parsedTerms } : {}),
          confirmed: true,
        };
      await onSave(payload);
      setConfirmed(false);
      setClearTerms(false);
    } catch (cause) {
      setError(messageFor(cause, "No fue posible actualizar las condiciones de pago."));
    } finally {
      setSaving(false);
    }
  }

  return (
    <form className="operations-form terms-form" onSubmit={submit}>
      <div className="form-heading">
        <h4>Condiciones de pago</h4>
        <p>Un plazo calcula el vencimiento; si informas ambos, deben coincidir.</p>
      </div>
      <div className="terms-inputs">
        <label>
          Fecha de vencimiento
          <input
            type="date"
            value={dueDate}
            onChange={(event) => {
              setDueDate(event.target.value);
              setTermsDays("");
            }}
            disabled={clearTerms || saving}
          />
        </label>
        <label>
          Plazo en días
          <input
            type="number"
            min="0"
            max="3650"
            step="1"
            inputMode="numeric"
            value={termsDays}
            onChange={(event) => {
              setTermsDays(event.target.value);
              setDueDate("");
            }}
            disabled={clearTerms || saving}
            placeholder="Ej. 30"
          />
        </label>
      </div>
      <label className="check-line">
        <input type="checkbox" checked={clearTerms} onChange={(event) => setClearTerms(event.target.checked)} disabled={saving} />
        Borrar la fecha y el plazo actuales
      </label>
      <label className="check-line confirm-line">
        <input type="checkbox" checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)} disabled={saving} />
        Confirmo que deseo actualizar las condiciones de esta factura.
      </label>
      {error ? <p className="form-error" role="alert">{error}</p> : null}
      <button className="secondary-action" type="submit" disabled={!confirmed || saving}>
        {saving ? "Guardando…" : "Guardar condiciones"}
      </button>
    </form>
  );
}

type FollowUpPanelProps = {
  item: OpenReceivableItem;
  followUps: CollectionFollowUp[];
  loading: boolean;
  error: string | null;
  canManage: boolean;
  token: string;
  companyId: string;
  onRetry: () => Promise<void>;
  onChanged: () => Promise<void>;
};

function FollowUpPanel({
  item,
  followUps,
  loading,
  error,
  canManage,
  token,
  companyId,
  onRetry,
  onChanged,
}: FollowUpPanelProps) {
  const [editing, setEditing] = useState<CollectionFollowUp | null>(null);
  const [status, setStatus] = useState<CollectionFollowUpStatus>(item.latest_followup_status || "pending");
  const [promisedDate, setPromisedDate] = useState(item.promised_date || "");
  const [note, setNote] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  function startEdit(record: CollectionFollowUp) {
    setEditing(record);
    setStatus(record.status);
    setPromisedDate(record.promised_date || "");
    setNote(record.note || "");
    setConfirmed(false);
    setFormError(null);
  }

  function cancelEdit() {
    setEditing(null);
    setStatus(item.latest_followup_status || "pending");
    setPromisedDate(item.promised_date || "");
    setNote("");
    setConfirmed(false);
    setFormError(null);
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (status === "promise_to_pay" && !promisedDate) {
      setFormError("Una promesa de pago requiere una fecha prometida.");
      return;
    }
    if (!confirmed) return;

    const shared = {
      status,
      promised_date: status === "promise_to_pay" ? promisedDate : null,
      note: note.trim() || null,
      confirmed: true as const,
    };
    setSaving(true);
    setFormError(null);
    try {
      if (editing) {
        await updateCollectionFollowUp(token, companyId, editing.id, shared);
      } else {
        await createCollectionFollowUp(token, companyId, { invoice_id: item.invoice_id, ...shared });
      }
      cancelEdit();
      await onChanged();
    } catch (cause) {
      setFormError(messageFor(cause, "No fue posible guardar el seguimiento."));
    } finally {
      setSaving(false);
    }
  }

  return (
    <section className="followups-panel" aria-labelledby="followups-title">
      <div className="form-heading">
        <h4 id="followups-title">Seguimiento de cobro</h4>
        <p>Registrar un seguimiento no envía comunicaciones ni genera cobros.</p>
      </div>

      {loading ? <p className="operations-loading">Cargando seguimientos…</p> : null}
      {error ? <p className="form-error" role="alert">{error} <button type="button" className="text-button" onClick={() => void onRetry()}>Reintentar</button></p> : null}
      {!loading && !error && followUps.length ? (
        <ol className="followup-history">
          {followUps.map((record) => (
            <li key={record.id}>
              <div>
                <span className={`followup-pill ${record.status}`}>{followUpLabels[record.status]}</span>
                <time dateTime={record.updated_at}>{formatDateTime(record.updated_at)}</time>
              </div>
              {record.promised_date ? <p>Promesa: {formatDate(record.promised_date)}</p> : null}
              {record.note ? <p>{record.note}</p> : null}
              {canManage ? <button className="text-button" type="button" onClick={() => startEdit(record)}>Editar</button> : null}
            </li>
          ))}
        </ol>
      ) : null}
      {!loading && !error && !followUps.length ? <p className="history-empty">No hay seguimientos registrados todavía.</p> : null}

      {canManage ? (
        <form className="operations-form followup-form" onSubmit={submit}>
          <div className="form-heading compact">
            <h4>{editing ? "Actualizar seguimiento" : "Registrar seguimiento"}</h4>
            {editing ? <button className="text-button" type="button" onClick={cancelEdit} disabled={saving}>Cancelar edición</button> : null}
          </div>
          <label>
            Estado
            <select value={status} onChange={(event) => setStatus(event.target.value as CollectionFollowUpStatus)} disabled={saving}>
              {(Object.keys(followUpLabels) as CollectionFollowUpStatus[]).map((value) => <option key={value} value={value}>{followUpLabels[value]}</option>)}
            </select>
          </label>
          {status === "promise_to_pay" ? (
            <label>
              Fecha prometida
              <input type="date" value={promisedDate} onChange={(event) => setPromisedDate(event.target.value)} disabled={saving} required />
            </label>
          ) : null}
          <label>
            Nota operativa <small>(opcional, máximo 280 caracteres)</small>
            <textarea value={note} onChange={(event) => setNote(event.target.value)} maxLength={280} rows={3} disabled={saving} placeholder="Ej. Se revisará el estado interno el viernes." />
          </label>
          <p className="note-warning"><b>No incluyas datos personales.</b> No escribas nombres, NIT, correos, teléfonos, documentos, cuentas ni enlaces.</p>
          <label className="check-line confirm-line">
            <input type="checkbox" checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)} disabled={saving} />
            Confirmo el registro de este seguimiento operativo.
          </label>
          {formError ? <p className="form-error" role="alert">{formError}</p> : null}
          <button className="secondary-action" type="submit" disabled={!confirmed || saving}>
            {saving ? "Guardando…" : editing ? "Guardar seguimiento" : "Registrar seguimiento"}
          </button>
        </form>
      ) : null}
    </section>
  );
}

function agingLabel(bucket: string) {
  return {
    not_due: "Por vencer",
    due_today: "Vence hoy",
    overdue_1_30: "Vencida 1–30 días",
    overdue_31_60: "Vencida 31–60 días",
    overdue_61_90: "Vencida 61–90 días",
    overdue_91_plus: "Vencida +90 días",
    missing_due_date: "Sin vencimiento",
  }[bucket] || "Pendiente";
}

function formatMoney(amount: string, currency: string) {
  const numericAmount = Number(amount);
  if (!Number.isFinite(numericAmount)) return `${amount} ${currency}`;
  return new Intl.NumberFormat("es-CO", {
    style: "currency",
    currency,
    maximumFractionDigits: 2,
  }).format(numericAmount);
}

function formatDate(value: string) {
  const date = new Date(`${value.slice(0, 10)}T00:00:00Z`);
  return Number.isNaN(date.valueOf())
    ? value
    : new Intl.DateTimeFormat("es-CO", { dateStyle: "medium", timeZone: "UTC" }).format(date);
}

function formatDateTime(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.valueOf())
    ? value
    : new Intl.DateTimeFormat("es-CO", { dateStyle: "short", timeZone: "America/Bogota" }).format(date);
}

function messageFor(cause: unknown, fallback: string) {
  return cause instanceof ApiError || cause instanceof Error ? cause.message : fallback;
}
