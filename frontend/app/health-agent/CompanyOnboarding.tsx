"use client";

import { type FormEvent, useState } from "react";

import { ApiError, onboardCompany } from "./api";
import type { Company } from "./types";

type Props = {
  token: string;
  onCompleted: (company: Company) => void;
};

export function CompanyOnboarding({ token, onCompleted }: Props) {
  const [companyName, setCompanyName] = useState("");
  const [currency, setCurrency] = useState("COP");
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const normalizedName = companyName.trim();
    if (!normalizedName || !confirmed) return;
    setBusy(true);
    setError(null);
    try {
      const result = await onboardCompany(token, {
        tenant_name: normalizedName,
        company_name: normalizedName,
        functional_currency: currency,
      });
      onCompleted(result.company);
    } catch (cause) {
      setError(messageFor(cause, "No fue posible crear la empresa de prueba."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="beta-setup company-onboarding" aria-labelledby="company-onboarding-title">
      <p className="eyebrow">PRIMER PASO</p>
      <h1 id="company-onboarding-title">Crea el espacio de tu empresa.</h1>
      <p className="beta-lead">
        Configuraremos una empresa activa en Colombia y te asignaremos como propietario. Después podrás cargar
        información para recibir diagnósticos, prioridades y proyecciones útiles desde el primer día.
      </p>
      <form className="operations-form beta-form" onSubmit={submit}>
        <label>
          Razón social o nombre de la empresa
          <input
            value={companyName}
            onChange={(event) => setCompanyName(event.target.value)}
            autoComplete="organization"
            maxLength={255}
            required
            placeholder="Ej. Acme Colombia S.A.S."
          />
        </label>
        <label>
          Moneda funcional
          <select value={currency} onChange={(event) => setCurrency(event.target.value)}>
            <option value="COP">COP · Peso colombiano</option>
            <option value="USD">USD · Dólar estadounidense</option>
            <option value="EUR">EUR · Euro</option>
          </select>
        </label>
        <p className="beta-note">
          El espacio de trabajo inicial llevará el mismo nombre. Puedes agregar otras razones sociales de tu grupo
          cuando el plan y la operación de beta lo habiliten.
        </p>
        <label className="check-line confirm-line">
          <input type="checkbox" checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)} required />
          Confirmo que estoy autorizado para crear y administrar este espacio de empresa.
        </label>
        {error ? <p className="form-error" role="alert">{error}</p> : null}
        <button className="secondary-action" disabled={!confirmed || busy}>
          {busy ? "Creando empresa…" : "Crear empresa y continuar"}
        </button>
      </form>
      <p className="beta-footnote">
        La beta no transmite facturas, realiza pagos ni presenta información ante la DIAN.
      </p>
    </section>
  );
}

function messageFor(cause: unknown, fallback: string) {
  return cause instanceof ApiError || cause instanceof Error ? cause.message : fallback;
}
