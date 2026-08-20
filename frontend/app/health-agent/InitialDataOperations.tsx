"use client";

import { type FormEvent, useRef, useState } from "react";

import {
  ApiError,
  createImportProfile,
  createInitialCsvDataSource,
  dataSources,
  importAccounting,
  importParties,
} from "./api";
import type { Company, DataSource, ImportRejection } from "./types";

type ImportKind = "parties" | "invoices" | "payments";
type ImportSummary = { acceptedRows: number; rejections: ImportRejection[]; kind: ImportKind };

type Props = {
  token: string;
  company: Company;
  onGoToDiagnostic: () => void;
};

const definitions: Record<ImportKind, {
  label: string;
  title: string;
  description: string;
  template: string;
  mapping: Record<string, string>;
  defaultPartyType?: "customer" | "supplier" | "both";
}> = {
  parties: {
    label: "Terceros",
    title: "1. Carga tus terceros",
    description: "Registra clientes y proveedores antes de relacionarlos con facturas. La plantilla no exige datos de contacto.",
    template: "/plantilla-terceros-beta.csv",
    defaultPartyType: "both",
    mapping: {
      name: "Nombre",
      document_type: "Tipo documento",
      document_number: "Documento",
      email: "Correo",
      phone: "Teléfono",
      city: "Ciudad",
      address: "Dirección",
    },
  },
  invoices: {
    label: "Facturas",
    title: "2. Carga facturas de venta y compra",
    description: "Cada fila representa una línea. Usa sale para ventas y purchase para compras; en ventas registra el cliente como receptor y en compras el proveedor como emisor.",
    template: "/plantilla-facturas-beta.csv",
    mapping: {
      number: "Numero",
      invoice_type: "Tipo",
      issue_date: "Fecha emision",
      due_date: "Fecha vencimiento",
      description: "Descripcion",
      quantity: "Cantidad",
      unit_price: "Precio unitario",
      currency_code: "Moneda",
      tax_total: "Total impuestos",
      issuer_document_number: "Documento emisor",
      recipient_document_number: "Documento receptor",
    },
  },
  payments: {
    label: "Pagos",
    title: "3. Carga pagos ya registrados",
    description: "Relaciona cada pago con una factura cargada previamente. La referencia de pago debe ser única para impedir duplicados y el tipo identifica facturas con el mismo número.",
    template: "/plantilla-pagos-beta.csv",
    mapping: {
      payment_date: "Fecha pago",
      amount: "Valor",
      currency_code: "Moneda",
      invoice_number: "Factura",
      invoice_type: "Tipo factura",
      payment_reference: "Referencia de pago",
      payment_method: "Medio de pago",
    },
  },
};

export function InitialDataOperations({ token, company, onGoToDiagnostic }: Props) {
  const [kind, setKind] = useState<ImportKind>("parties");
  const [file, setFile] = useState<File | null>(null);
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<ImportSummary | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const definition = definitions[kind];

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!file || !confirmed || busy) return;
    if (!file.name.toLowerCase().endsWith(".csv")) {
      setError("Para la carga inicial usa un archivo CSV con codificación UTF-8.");
      return;
    }
    if (file.size > 5_000_000) {
      setError("El archivo supera el límite de 5 MB de esta beta.");
      return;
    }
    if (!window.confirm(`¿Confirmas que deseas importar ${definition.label.toLowerCase()} en ${company.name}?`)) return;

    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const source = await resolveInitialSource(token, company);
      const profile = await createImportProfile(token, source.id, {
        entity: kind,
        file_format: "csv",
        column_mapping: definition.mapping,
        ...(definition.defaultPartyType ? { default_party_type: definition.defaultPartyType } : {}),
      });
      if (kind === "parties") {
        const response = await importParties(token, source.id, profile.id, file);
        setResult({ acceptedRows: response.parties.length, rejections: response.rejections, kind });
      } else {
        const response = await importAccounting(token, source.id, profile.id, file);
        setResult({ acceptedRows: response.accepted_rows, rejections: response.rejections, kind });
      }
      setFile(null);
      setConfirmed(false);
      if (fileRef.current) fileRef.current.value = "";
    } catch (cause) {
      setError(messageFor(cause, "No fue posible completar la carga inicial."));
    } finally {
      setBusy(false);
    }
  }

  function chooseKind(nextKind: ImportKind) {
    setKind(nextKind);
    setFile(null);
    setConfirmed(false);
    setError(null);
    setResult(null);
    if (fileRef.current) fileRef.current.value = "";
  }

  return (
    <section className="beta-setup initial-data" aria-labelledby="initial-data-title">
      <header className="operations-heading">
        <div>
          <p className="eyebrow">CARGA INICIAL</p>
          <h1 id="initial-data-title">Convierte tus archivos en señales accionables.</h1>
          <p>Carga la información mínima de {company.name} para automatizar diagnósticos, cartera, vencimientos y proyecciones por moneda.</p>
        </div>
      </header>

      <ol className="initial-data-steps" aria-label="Orden recomendado de carga">
        {(Object.keys(definitions) as ImportKind[]).map((item) => (
          <li key={item} className={item === kind ? "active" : undefined}>
            <button type="button" onClick={() => chooseKind(item)}>{definitions[item].label}</button>
          </li>
        ))}
      </ol>

      <form className="operations-form beta-form initial-data-form" onSubmit={submit}>
        <div className="form-heading">
          <h2>{definition.title}</h2>
          <p>{definition.description}</p>
        </div>
        <p className="beta-note">
          Descarga la <a href={definition.template} download>plantilla CSV de {definition.label.toLowerCase()}</a>, reemplaza únicamente los ejemplos ficticios y conserva los encabezados. Las fechas usan AAAA-MM-DD y los valores no incluyen separadores de miles.
        </p>
        <label>
          Archivo CSV
          <input
            ref={fileRef}
            type="file"
            accept=".csv,text/csv"
            onChange={(event) => setFile(event.target.files?.[0] || null)}
            required
          />
        </label>
        <p className="note-warning">
          <b>Antes de cargar:</b> revisa que no adjuntes certificados, contraseñas ni archivos distintos de la plantilla. Los terceros coincidentes se actualizan; las facturas y pagos que ya existen se reportan sin modificarse para evitar duplicados.
        </p>
        <label className="check-line confirm-line">
          <input type="checkbox" checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)} required />
          Confirmo que el archivo corresponde a {company.name} y estoy autorizado para incorporarlo.
        </label>
        {error ? <p className="form-error" role="alert">{error}</p> : null}
        <button className="secondary-action" disabled={!file || !confirmed || busy}>
          {busy ? "Validando e importando…" : `Importar ${definition.label.toLowerCase()}`}
        </button>
      </form>

      {result ? (
        <section className="initial-import-result" role="status">
          <b>Carga terminada.</b> {result.acceptedRows} fila{result.acceptedRows === 1 ? "" : "s"} aceptada{result.acceptedRows === 1 ? "" : "s"} y {result.rejections.length} rechazada{result.rejections.length === 1 ? "" : "s"}.
          {result.rejections.length ? (
            <ul>
              {result.rejections.slice(0, 8).map((rejection) => (
                <li key={`${rejection.row_number}-${rejection.message}`}>Fila {rejection.row_number}: {safeRejectionMessage(rejection.message)}</li>
              ))}
            </ul>
          ) : null}
          {result.rejections.length > 8 ? (
            <p>Se muestran 8 rechazos. Descarga el informe para revisar los {result.rejections.length - 8} restantes.</p>
          ) : null}
          {result.rejections.length ? (
            <button type="button" className="quiet-button" onClick={() => downloadRejectionReport(result.rejections, result.kind)}>
              Descargar informe de rechazos
            </button>
          ) : null}
          <button type="button" className="quiet-button" onClick={onGoToDiagnostic}>Ver diagnóstico actualizado</button>
        </section>
      ) : null}

      <p className="beta-footnote">
        Esta carga no transmite datos a la DIAN ni realiza acciones bancarias. Las monedas se conservan separadas para evitar conclusiones incorrectas.
      </p>
    </section>
  );
}

async function resolveInitialSource(token: string, company: Company): Promise<DataSource> {
  const sources = await dataSources(token, company.id);
  const existing = sources.find((source) => (
    source.connector_id === "csv_import"
    && source.kind === "file_import"
    && source.mode === "file_upload"
    && source.status === "active"
    && ["parties", "invoices", "payments"].every((capability) => source.capabilities.includes(capability))
  ));
  return existing || createInitialCsvDataSource(token, company);
}

function safeRejectionMessage(message: string) {
  return message
    .replace(/'[^']+'/g, "'[dato oculto]'")
    .replace(/\b\d{5,}\b/g, "[dato oculto]");
}

function downloadRejectionReport(rejections: ImportRejection[], kind: ImportKind) {
  const rows = [
    "Fila,Motivo",
    ...rejections.map((rejection) => `${rejection.row_number},${csvValue(safeRejectionMessage(rejection.message))}`),
  ];
  const url = URL.createObjectURL(new Blob([`\uFEFF${rows.join("\n")}`], { type: "text/csv;charset=utf-8" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = `rechazos-${kind}-contamind.csv`;
  link.click();
  URL.revokeObjectURL(url);
}

function csvValue(value: string) {
  return `"${value.replace(/"/g, '""')}"`;
}

function messageFor(cause: unknown, fallback: string) {
  return cause instanceof ApiError || cause instanceof Error ? cause.message : fallback;
}
