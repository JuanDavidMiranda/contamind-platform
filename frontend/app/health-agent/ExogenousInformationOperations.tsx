"use client";

import { useCallback, useEffect, useState } from "react";

import { ApiError, exogenousInformationExceptions } from "./api";
import type { ExogenousInformationException } from "./types";


type Props = {
  token: string;
  companyId: string;
  companyName: string;
  enabled: boolean;
};

const issueLabels: Record<string, string> = {
  PARTY_DOCUMENT_TYPE_MISSING: "Sin tipo de documento",
  PARTY_DOCUMENT_NUMBER_MISSING: "Sin número de documento",
  PARTY_CITY_MISSING: "Sin ciudad",
  PARTY_ADDRESS_MISSING: "Sin dirección",
  INVOICE_NUMBER_MISSING: "Sin consecutivo",
  INVOICE_COUNTERPARTY_MISSING: "Sin contraparte asociada",
  INVOICE_TOTAL_MISMATCH: "Total contable inconsistente",
  PAYMENT_INVOICE_MISSING: "Sin factura vinculada",
};

const recordTypeLabels: Record<ExogenousInformationException["record_type"], string> = {
  party: "Tercero",
  invoice: "Factura",
  payment: "Pago",
};

export function ExogenousInformationOperations({ token, companyId, companyName, enabled }: Props) {
  const [taxYear, setTaxYear] = useState(() => new Date().getFullYear());
  const [effectiveYear, setEffectiveYear] = useState(taxYear);
  const [exceptions, setExceptions] = useState<ExogenousInformationException[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!enabled) {
      setExceptions([]);
      setTotal(0);
      setLoading(false);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const page = await exogenousInformationExceptions(token, companyId, taxYear, { limit: 100 });
      setExceptions(page.items);
      setTotal(page.total);
      setEffectiveYear(page.tax_year);
    } catch (cause) {
      setError(messageFor(cause, "No fue posible cargar la preparación operativa."));
    } finally {
      setLoading(false);
    }
  }, [companyId, enabled, taxYear, token]);

  useEffect(() => {
    let disposed = false;
    void Promise.resolve().then(() => {
      if (!disposed) return load();
    });
    return () => { disposed = true; };
  }, [load]);

  if (!enabled) {
    return (
      <section className="exogenous-operations unavailable">
        <p className="eyebrow">PREPARACIÓN DE INFORMACIÓN EXÓGENA</p>
        <h2>La empresa está desactivada.</h2>
        <p>Reactiva {companyName} para revisar la calidad de los datos.</p>
      </section>
    );
  }

  return (
    <section className="exogenous-operations" aria-labelledby="exogenous-operations-title">
      <header className="operations-heading">
        <div>
          <p className="eyebrow">PREPARACIÓN DE INFORMACIÓN EXÓGENA</p>
          <h2 id="exogenous-operations-title">Datos pendientes por depurar</h2>
          <p>{total} caso{total === 1 ? "" : "s"} para el año gravable {effectiveYear}.</p>
        </div>
        <button className="quiet-button" type="button" onClick={() => void load()} disabled={loading}>
          {loading ? "Actualizando…" : "Actualizar"}
        </button>
      </header>

      <p className="operations-privacy">
        Esta vista revisa calidad de datos, pero no define obligación, formatos o conceptos DIAN; tampoco genera, firma ni presenta archivos oficiales.
      </p>

      <label className="exogenous-year">
        Año gravable
        <input type="number" min="2000" max="2100" value={taxYear} onChange={(event) => setTaxYear(Number(event.target.value) || new Date().getFullYear())} />
      </label>

      {error ? <p className="operations-error" role="alert">{error}</p> : null}
      {loading ? <p className="operations-loading">Revisando datos del año gravable…</p> : null}

      {!loading && !exceptions.length ? (
        <div className="operations-empty">
          <h3>No hay casos pendientes.</h3>
          <p>No se encontraron faltantes de identificación, trazabilidad o consistencia en los datos disponibles para {effectiveYear}.</p>
        </div>
      ) : null}

      {exceptions.length ? (
        <div className="exogenous-exception-list">
          {exceptions.map((item) => (
            <article key={`${item.record_type}-${item.record_id}`} className={`exogenous-exception ${item.record_type}`}>
              <div>
                <span>{recordTypeLabels[item.record_type]}</span>
                <strong>{item.record_label}</strong>
                {item.record_date ? <time dateTime={item.record_date}>{formatDate(item.record_date)}</time> : null}
              </div>
              <ul>{item.issue_codes.map((code) => <li key={code}>{issueLabels[code] || code}</li>)}</ul>
            </article>
          ))}
        </div>
      ) : null}
    </section>
  );
}

function formatDate(value: string) {
  const parsed = new Date(`${value.slice(0, 10)}T00:00:00Z`);
  return Number.isNaN(parsed.valueOf()) ? value : new Intl.DateTimeFormat("es-CO", { dateStyle: "medium", timeZone: "UTC" }).format(parsed);
}

function messageFor(cause: unknown, fallback: string) {
  return cause instanceof ApiError || cause instanceof Error ? cause.message : fallback;
}
