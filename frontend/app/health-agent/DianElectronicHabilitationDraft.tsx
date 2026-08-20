"use client";

import { type FormEvent, useCallback, useEffect, useRef, useState } from "react";

import {
  ApiError,
  createDianNumberingRange,
  dianHabilitationAccess,
  dianHabilitationProfile,
  dianNumberingRanges,
  dianSignedTestDocumentEvents,
  dianSignedTestDocuments,
  revokeDianTechnicalCredentials,
  saveDianHabilitationProfile,
  saveDianHabilitationParameters,
  saveDianTechnicalCredentials,
  uploadDianSignedTestDocument,
} from "./api";
import type {
  DianDocumentEvent,
  DianElectronicDocument,
  DianElectronicDocumentType,
  DianHabilitationProfile,
  DianNumberingRange,
} from "./types";
import "./dian-electronic-habilitation-draft.css";

export type DianElectronicHabilitationDraftCompany = {
  id: string;
  name: string;
  status: "active" | "disabled";
};

type Props = {
  token: string;
  company: DianElectronicHabilitationDraftCompany | undefined;
  enabled: boolean;
};

type FiscalFormState = {
  legalName: string;
  nit: string;
  checkDigit: string;
  email: string;
  address: string;
  cityCode: string;
  cityName: string;
  departmentCode: string;
  departmentName: string;
  taxResponsibilities: string;
  phone: string;
  taxRegime: string;
};

const MAX_CERTIFICATE_BYTES = 750_000;
const MAX_SIGNED_ZIP_BYTES = 10_000_000;

const requirementLabels: Record<string, string> = {
  dian_data_source: "Falta la fuente aislada de habilitación.",
  technical_credentials: "Falta cargar las credenciales técnicas protegidas.",
  software_test_set_id: "Falta registrar el conjunto oficial de pruebas de DIAN.",
  signature_policy: "Falta confirmar la política de firma aplicable.",
  numbering_range: "Falta un rango de numeración vigente para habilitación.",
};

const statusLabels: Record<string, { label: string; detail: string; tone: "draft" | "ready" | "active" | "review" }> = {
  draft: {
    label: "Preparación incompleta",
    detail: "Aún hay requisitos pendientes antes de enviar documentos de prueba.",
    tone: "draft",
  },
  ready_for_habilitation: {
    label: "Lista para habilitación",
    detail: "La configuración mínima está lista para preparar una prueba controlada.",
    tone: "ready",
  },
  in_habilitation: {
    label: "Prueba en seguimiento",
    detail: "Hay documentos de habilitación con trazabilidad pendiente de revisión.",
    tone: "active",
  },
};

const documentTypeLabels: Record<DianElectronicDocumentType, string> = {
  invoice: "Factura de venta",
  credit_note: "Nota crédito",
  debit_note: "Nota débito",
};

const documentStatusLabels: Record<string, string> = {
  queued: "En cola",
  sending: "Enviando a DIAN",
  processing: "En seguimiento",
  accepted: "Aceptada",
  rejected: "Rechazada",
  failed: "Con error",
  manual_review: "Requiere revisión",
  cancelled: "Cancelada",
};

const setupChecks = [
  { id: "profile", label: "Perfil fiscal registrado", requirement: null },
  { id: "test-set", label: "Conjunto de pruebas configurado", requirement: "software_test_set_id" },
  { id: "credentials", label: "Credenciales técnicas protegidas", requirement: "technical_credentials" },
  { id: "signature", label: "Política de firma confirmada", requirement: "signature_policy" },
  { id: "numbering", label: "Rango de numeración activo", requirement: "numbering_range" },
] as const;

/**
 * Operational interface for the own-software DIAN habilitation flow.
 * It deliberately has no production action and never renders a saved secret,
 * the TestSetId, signing policy, XML payload, or SOAP response body.
 */
export function DianElectronicHabilitationDraft({ token, company, enabled }: Props) {
  const [profile, setProfile] = useState<DianHabilitationProfile | null>(null);
  const [ranges, setRanges] = useState<DianNumberingRange[]>([]);
  const [documents, setDocuments] = useState<DianElectronicDocument[]>([]);
  const [selectedDocumentId, setSelectedDocumentId] = useState<string | null>(null);
  const [events, setEvents] = useState<DianDocumentEvent[]>([]);
  const [canManageHabilitation, setCanManageHabilitation] = useState(false);
  const [loading, setLoading] = useState(true);
  const [eventsLoading, setEventsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const eventsRequestId = useRef(0);
  const eventsAbortController = useRef<AbortController | null>(null);

  const cancelEventsRequest = useCallback(() => {
    eventsRequestId.current += 1;
    eventsAbortController.current?.abort();
    eventsAbortController.current = null;
  }, []);

  const load = useCallback(async () => {
    if (!enabled || !company) {
      setProfile(null);
      setRanges([]);
      setDocuments([]);
      setSelectedDocumentId(null);
      setEvents([]);
      setCanManageHabilitation(false);
      setLoading(false);
      return;
    }

    setLoading(true);
    setError(null);
    // Keep write actions closed until the role is confirmed for this company.
    setCanManageHabilitation(false);
    try {
      const [nextProfile, nextRanges, nextDocuments, access] = await Promise.all([
        dianHabilitationProfile(token, company.id),
        dianNumberingRanges(token, company.id),
        dianSignedTestDocuments(token, company.id),
        dianHabilitationAccess(token, company.id),
      ]);
      setProfile(nextProfile);
      setRanges(nextRanges);
      setDocuments(nextDocuments);
      setCanManageHabilitation(access.can_manage_habilitation);
      setSelectedDocumentId((current) => (
        nextDocuments.some((document) => document.id === current) ? current : null
      ));
    } catch (cause) {
      setError(messageFor(cause, "No fue posible consultar la habilitación DIAN."));
    } finally {
      setLoading(false);
    }
  }, [company, enabled, token]);

  useEffect(() => {
    let disposed = false;
    void Promise.resolve().then(() => {
      if (!disposed) return load();
      return undefined;
    });
    return () => {
      disposed = true;
      cancelEventsRequest();
    };
  }, [cancelEventsRequest, load]);

  async function openEvents(documentId: string) {
    if (!company) return;
    const requestId = eventsRequestId.current + 1;
    eventsRequestId.current = requestId;
    eventsAbortController.current?.abort();
    eventsAbortController.current = null;

    if (selectedDocumentId === documentId) {
      setSelectedDocumentId(null);
      setEvents([]);
      setEventsLoading(false);
      return;
    }

    const controller = new AbortController();
    eventsAbortController.current = controller;
    setSelectedDocumentId(documentId);
    setEvents([]);
    setEventsLoading(true);
    setError(null);
    try {
      const response = await dianSignedTestDocumentEvents(token, company.id, documentId, controller.signal);
      if (eventsRequestId.current !== requestId || controller.signal.aborted) return;
      setEvents(response.items);
    } catch (cause) {
      if (eventsRequestId.current !== requestId || controller.signal.aborted) return;
      setError(messageFor(cause, "No fue posible consultar los eventos del documento."));
    } finally {
      if (eventsRequestId.current === requestId) {
        eventsAbortController.current = null;
        setEventsLoading(false);
      }
    }
  }

  async function profileSaved(nextProfile: DianHabilitationProfile) {
    setProfile(nextProfile);
    setCanManageHabilitation(nextProfile.can_manage_habilitation);
    setNotice("El perfil fiscal fue guardado para el ambiente de habilitación.");
    await load();
  }

  async function habilitationParametersSaved(nextProfile: DianHabilitationProfile) {
    setProfile(nextProfile);
    setCanManageHabilitation(nextProfile.can_manage_habilitation);
    setNotice("El conjunto de pruebas y la política de firma quedaron configurados para habilitación. Sus valores no volverán a mostrarse.");
    await load();
  }

  async function technicalCredentialsSaved(nextProfile: DianHabilitationProfile, action: "saved" | "revoked") {
    setProfile(nextProfile);
    setCanManageHabilitation(nextProfile.can_manage_habilitation);
    setNotice(action === "saved"
      ? "Las credenciales de habilitación se validaron y almacenaron cifradas. No volverán a mostrarse."
      : "Las credenciales de habilitación fueron revocadas. No se enviarán nuevas pruebas hasta configurarlas de nuevo.");
    await load();
  }

  async function rangeCreated() {
    setNotice("El rango de numeración quedó registrado para habilitación.");
    await load();
  }

  async function documentQueued(document: DianElectronicDocument) {
    setNotice(`El documento ${document.document_number} quedó en cola de habilitación. Revisa sus eventos antes de volver a enviarlo.`);
    await load();
    await openEvents(document.id);
  }

  if (!enabled || !company) {
    return (
      <section className="dian-habilitation-draft" aria-labelledby="dian-habilitation-draft-title">
        <p className="eyebrow">HABILITACIÓN DIAN · SOFTWARE PROPIO</p>
        <h2 id="dian-habilitation-draft-title">La empresa está desactivada.</h2>
        <p className="dian-habilitation-draft__notice">Reactiva la empresa para administrar sus pruebas de habilitación.</p>
      </section>
    );
  }

  const status = profile ? statusLabels[profile.status] || {
    label: "Requiere revisión",
    detail: "El estado recibido requiere revisión por un usuario autorizado.",
    tone: "review" as const,
  } : null;
  const missingRequirements = new Set(profile?.missing_requirements || []);
  const selectedDocument = documents.find((document) => document.id === selectedDocumentId) || null;

  return (
    <section className="dian-habilitation-draft" aria-labelledby="dian-habilitation-draft-title">
      <header className="dian-habilitation-draft__heading">
        <div>
          <p className="eyebrow">HABILITACIÓN DIAN · SOFTWARE PROPIO</p>
          <h2 id="dian-habilitation-draft-title">Pruebas con trazabilidad</h2>
          <p>Configura y sigue la habilitación de <b>{company.name}</b> sin activar producción.</p>
        </div>
        <div className="dian-habilitation-draft__badges" aria-label="Ambiente y protección">
          <span className="dian-habilitation-draft__badge ready">Solo habilitación</span>
          <span className="dian-habilitation-draft__badge locked">Producción bloqueada</span>
        </div>
      </header>

      <section className="dian-habilitation-draft__notice" aria-label="Límite del ambiente">
        <b>Ambiente controlado.</b> Esta sección permite preparar pruebas de DIAN, no emitir en producción. Los datos técnicos,
        documentos firmados y respuestas SOAP no se comparten con el asistente.
      </section>

      <section className="dian-habilitation-draft__status-card" aria-labelledby="dian-habilitation-status-title">
        <div className="dian-habilitation-draft__section-heading">
          <div>
            <p className="eyebrow">ESTADO ACTUAL</p>
            <h3 id="dian-habilitation-status-title">Preparación por empresa</h3>
          </div>
          <button className="quiet-button" type="button" onClick={() => void load()} disabled={loading}>
            {loading ? "Actualizando…" : "Actualizar"}
          </button>
        </div>

        {notice ? <p className="dian-habilitation-draft__success" role="status">{notice}</p> : null}
        {error ? <p className="operations-error" role="alert">{error}</p> : null}
        {loading ? <p className="operations-loading" role="status">Consultando el estado de habilitación…</p> : null}

        {!loading && profile && !profile.integration_enabled ? (
          <p className="dian-habilitation-draft__environment-lock" role="status">
            <b>Envío de pruebas desactivado en este ambiente.</b> Puedes completar el perfil, las credenciales y la numeración, pero no se encolarán documentos hasta que el entorno autorizado habilite la integración. Esta vista no permite cambiar esa condición.
          </p>
        ) : null}

        {!loading && !canManageHabilitation ? (
          <p className="dian-habilitation-draft__environment-lock" role="status">
            <b>Acceso de solo lectura.</b> Tu rol puede consultar la preparación y los eventos, pero no modificar perfiles, credenciales, parámetros, rangos ni documentos de habilitación. Solicita a un administrador o responsable de fuentes que realice esos cambios.
          </p>
        ) : null}

        {!loading && !profile ? (
          <div className="dian-habilitation-draft__empty" role="status">
            <h4>Comienza con el perfil fiscal.</h4>
            <p>Registra los datos de la empresa. Las credenciales y los documentos de prueba permanecen cerrados hasta completar ese paso.</p>
          </div>
        ) : null}

        {!loading && profile && status ? (
          <>
            <div className="dian-habilitation-draft__status-summary">
              <div>
                <span>Estado</span>
                <strong className={`dian-habilitation-draft__status ${status.tone}`}>{status.label}</strong>
                <p>{status.detail}</p>
              </div>
              <div>
                <span>Ambiente</span>
                <strong>Habilitación DIAN</strong>
                <p>La producción sigue bloqueada por el sistema.</p>
              </div>
            </div>

            <ul className="dian-habilitation-draft__checks" aria-label="Controles de configuración">
              {setupChecks.map((item) => {
                const complete = item.requirement === null || !missingRequirements.has(item.requirement);
                return (
                  <li key={item.id} className={complete ? "complete" : "pending"}>
                    <span aria-hidden="true">{complete ? "✓" : "•"}</span>
                    <div>
                      <b>{item.label}</b>
                      <small>{complete ? "Configurado" : requirementLabels[item.requirement || ""] || "Pendiente de configurar"}</small>
                    </div>
                  </li>
                );
              })}
            </ul>
          </>
        ) : null}
      </section>

      <section className="dian-habilitation-draft__configuration" aria-labelledby="dian-habilitation-configuration-title">
        <div className="dian-habilitation-draft__section-heading">
          <div>
            <p className="eyebrow">CONFIGURACIÓN CONTROLADA</p>
            <h3 id="dian-habilitation-configuration-title">Datos fiscales y habilitación técnica</h3>
          </div>
          <span>Solo usuarios autorizados</span>
        </div>
        <div className="dian-habilitation-draft__configuration-grid">
          {canManageHabilitation ? (
            <>
              <FiscalProfileForm
                key={profile?.id || "new-profile"}
                token={token}
                companyId={company.id}
                profile={profile}
                onSaved={profileSaved}
              />
              <HabilitationParametersForm
                token={token}
                companyId={company.id}
                profile={profile}
                onSaved={habilitationParametersSaved}
              />
              <TechnicalCredentialsForm
                token={token}
                companyId={company.id}
                profile={profile}
                onSaved={technicalCredentialsSaved}
              />
            </>
          ) : <ReadOnlyHabilitationNotice section="la configuración fiscal y técnica" />}
        </div>
      </section>

      <section className="dian-habilitation-draft__configuration" aria-labelledby="dian-habilitation-numbering-title">
        <div className="dian-habilitation-draft__section-heading">
          <div>
            <p className="eyebrow">NUMERACIÓN DE PRUEBAS</p>
            <h3 id="dian-habilitation-numbering-title">Rangos reservados para habilitación</h3>
          </div>
          <span>{ranges.filter((item) => item.active).length} rango{ranges.filter((item) => item.active).length === 1 ? "" : "s"} activo{ranges.filter((item) => item.active).length === 1 ? "" : "s"}</span>
        </div>
        <div className="dian-habilitation-draft__configuration-grid numbering">
          {canManageHabilitation
            ? <NumberingRangeForm token={token} companyId={company.id} profile={profile} onCreated={rangeCreated} />
            : <ReadOnlyHabilitationNotice section="los rangos de numeración" />}
          <NumberingRangeList ranges={ranges} />
        </div>
      </section>

      <section className="dian-habilitation-draft__configuration" aria-labelledby="dian-habilitation-documents-title">
        <div className="dian-habilitation-draft__section-heading">
          <div>
            <p className="eyebrow">DOCUMENTOS DE PRUEBA</p>
            <h3 id="dian-habilitation-documents-title">Carga un ZIP firmado y sigue su estado</h3>
          </div>
          <span>{documents.length} documento{documents.length === 1 ? "" : "s"}</span>
        </div>
        <p className="dian-habilitation-draft__section-copy">
          El ZIP debe contener un único XML UBL firmado. La carga reserva el consecutivo y encola la prueba; no vuelve a enviar el documento automáticamente si la respuesta es incierta.
        </p>
        {canManageHabilitation ? (
          <SignedTestDocumentForm
            token={token}
            companyId={company.id}
            profile={profile}
            ranges={ranges}
            onQueued={documentQueued}
          />
        ) : <ReadOnlyHabilitationNotice section="la carga de documentos de prueba" />}
        <HabilitationDocumentList
          documents={documents}
          selectedDocumentId={selectedDocumentId}
          onSelect={(documentId) => void openEvents(documentId)}
        />
        {selectedDocument ? (
          <DocumentEventsPanel document={selectedDocument} events={events} loading={eventsLoading} />
        ) : null}
      </section>

      <section className="dian-habilitation-draft__safety" aria-labelledby="dian-habilitation-safety-title">
        <div>
          <p className="eyebrow">PROTECCIÓN DE DATOS</p>
          <h3 id="dian-habilitation-safety-title">Los secretos y la producción permanecen fuera de este flujo.</h3>
        </div>
        <ul>
          <li>El certificado, contraseña, PIN y datos del software se cifran al enviarse y nunca se muestran después.</li>
          <li>La consulta de adquirientes es un piloto distinto; no comparte sus fuentes ni sus credenciales con esta habilitación.</li>
          <li>La emisión productiva requiere la aprobación oficial de DIAN y una activación separada, que esta vista no ofrece.</li>
        </ul>
      </section>
    </section>
  );
}

function ReadOnlyHabilitationNotice({ section }: { section: string }) {
  return (
    <section className="operations-form dian-habilitation-draft__form dian-habilitation-draft__form--locked" aria-live="polite">
      <h4>Consulta de solo lectura</h4>
      <p>Tu rol puede revisar {section}, pero no realizar cambios. Un administrador o responsable de fuentes debe completar esta acción.</p>
    </section>
  );
}

function FiscalProfileForm({ token, companyId, profile, onSaved }: {
  token: string;
  companyId: string;
  profile: DianHabilitationProfile | null;
  onSaved: (profile: DianHabilitationProfile) => Promise<void>;
}) {
  const [values, setValues] = useState<FiscalFormState>(() => fiscalFormValues(profile));
  const [confirmed, setConfirmed] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function update<Key extends keyof FiscalFormState>(key: Key, value: FiscalFormState[Key]) {
    setValues((current) => ({ ...current, [key]: value }));
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!confirmed) return;
    const taxResponsibilities = values.taxResponsibilities
      .split(",")
      .map((value) => value.trim())
      .filter(Boolean);
    if (!taxResponsibilities.length) {
      setError("Indica al menos una responsabilidad tributaria, separada por comas si aplica.");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const nextProfile = await saveDianHabilitationProfile(token, companyId, {
        legal_name: values.legalName.trim(),
        nit: values.nit.trim(),
        check_digit: values.checkDigit.trim(),
        email: values.email.trim(),
        address: values.address.trim(),
        city_code: values.cityCode.trim(),
        city_name: values.cityName.trim(),
        department_code: values.departmentCode.trim(),
        department_name: values.departmentName.trim(),
        tax_responsibilities: taxResponsibilities,
        phone: values.phone.trim() || null,
        tax_regime: values.taxRegime.trim() || null,
      });
      setConfirmed(false);
      await onSaved(nextProfile);
    } catch (cause) {
      setError(messageFor(cause, "No fue posible guardar el perfil fiscal."));
    } finally {
      setSaving(false);
    }
  }

  return (
    <form className="operations-form dian-habilitation-draft__form" onSubmit={submit}>
      <div className="form-heading">
        <h4>{profile ? "Actualizar perfil fiscal" : "Registrar perfil fiscal"}</h4>
        <p>Confirma los datos tributarios que se usarán exclusivamente en las pruebas de habilitación.</p>
      </div>
      {profile ? <p className="note-warning">Confirma los datos actuales antes de guardar. Los parámetros de habilitación y las credenciales se administran en sus formularios separados.</p> : null}
      <div className="dian-habilitation-draft__field-grid">
        <label className="wide">Razón social<input value={values.legalName} onChange={(event) => update("legalName", event.target.value)} maxLength={255} required /></label>
        <label>NIT<input value={values.nit} onChange={(event) => update("nit", event.target.value.replace(/\D/g, ""))} inputMode="numeric" pattern="\d+" maxLength={30} required /></label>
        <label>Dígito de verificación<input value={values.checkDigit} onChange={(event) => update("checkDigit", event.target.value.replace(/\D/g, "").slice(0, 1))} inputMode="numeric" pattern="\d" maxLength={1} required /></label>
        <label className="wide">Correo de contacto<input type="email" value={values.email} onChange={(event) => update("email", event.target.value)} maxLength={255} required /></label>
        <label className="wide">Dirección<input value={values.address} onChange={(event) => update("address", event.target.value)} maxLength={255} required /></label>
        <label>Código de municipio<input value={values.cityCode} onChange={(event) => update("cityCode", event.target.value)} maxLength={10} required /></label>
        <label>Municipio<input value={values.cityName} onChange={(event) => update("cityName", event.target.value)} maxLength={100} required /></label>
        <label>Código de departamento<input value={values.departmentCode} onChange={(event) => update("departmentCode", event.target.value)} maxLength={10} required /></label>
        <label>Departamento<input value={values.departmentName} onChange={(event) => update("departmentName", event.target.value)} maxLength={100} required /></label>
        <label className="wide">Responsabilidades tributarias<textarea value={values.taxResponsibilities} onChange={(event) => update("taxResponsibilities", event.target.value)} maxLength={500} required placeholder="Ej. O-13, O-15" /></label>
        <label>Teléfono (opcional)<input value={values.phone} onChange={(event) => update("phone", event.target.value)} maxLength={50} /></label>
        <label>Régimen tributario (opcional)<input value={values.taxRegime} onChange={(event) => update("taxRegime", event.target.value)} maxLength={100} /></label>
      </div>
      <label className="check-line confirm-line">
        <input type="checkbox" checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)} />
        Confirmo que los datos fiscales corresponden a esta empresa y a sus pruebas de habilitación.
      </label>
      {error ? <p className="form-error" role="alert">{error}</p> : null}
      <button className="secondary-action" disabled={!confirmed || saving}>{saving ? "Guardando…" : profile ? "Actualizar perfil fiscal" : "Guardar perfil fiscal"}</button>
    </form>
  );
}

function HabilitationParametersForm({ token, companyId, profile, onSaved }: {
  token: string;
  companyId: string;
  profile: DianHabilitationProfile | null;
  onSaved: (profile: DianHabilitationProfile) => Promise<void>;
}) {
  const [softwareTestSetId, setSoftwareTestSetId] = useState("");
  const [signaturePolicyIdentifier, setSignaturePolicyIdentifier] = useState("");
  const [signaturePolicyDigestBase64, setSignaturePolicyDigestBase64] = useState("");
  const [signaturePolicyQualifierUrl, setSignaturePolicyQualifierUrl] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!profile || !confirmed) return;
    setSaving(true);
    setError(null);
    try {
      const nextProfile = await saveDianHabilitationParameters(token, companyId, {
        software_test_set_id: softwareTestSetId.trim(),
        signature_policy_identifier: signaturePolicyIdentifier.trim(),
        signature_policy_digest_base64: signaturePolicyDigestBase64.trim(),
        signature_policy_qualifier_url: signaturePolicyQualifierUrl.trim() || null,
      });
      setSoftwareTestSetId("");
      setSignaturePolicyIdentifier("");
      setSignaturePolicyDigestBase64("");
      setSignaturePolicyQualifierUrl("");
      setConfirmed(false);
      await onSaved(nextProfile);
    } catch (cause) {
      setError(messageFor(cause, "No fue posible guardar los parámetros de habilitación."));
    } finally {
      setSaving(false);
    }
  }

  if (!profile) {
    return (
      <section className="operations-form dian-habilitation-draft__form dian-habilitation-draft__form--locked">
        <h4>Parámetros de habilitación</h4>
        <p>Primero registra el perfil fiscal. Después podrás ingresar el conjunto de pruebas y la política de firma entregados por DIAN.</p>
      </section>
    );
  }

  const policyConfigured = !profile.missing_requirements.includes("signature_policy");
  return (
    <form className="operations-form dian-habilitation-draft__form" onSubmit={submit}>
      <div className="form-heading">
        <h4>Parámetros de habilitación</h4>
        <p>{profile.software_test_set_id_configured && policyConfigured ? "Los parámetros están configurados. Puedes reemplazarlos con una nueva asignación de DIAN." : "Registra la asignación de pruebas y la política XAdES de esta empresa."}</p>
      </div>
      <label>Identificador del conjunto de pruebas (TestSetId)<input value={softwareTestSetId} onChange={(event) => setSoftwareTestSetId(event.target.value)} maxLength={128} autoComplete="off" required /></label>
      <label>Identificador de política de firma XAdES<input value={signaturePolicyIdentifier} onChange={(event) => setSignaturePolicyIdentifier(event.target.value)} maxLength={2048} autoComplete="off" required /></label>
      <label>Hash SHA-256 de la política (base64)<input value={signaturePolicyDigestBase64} onChange={(event) => setSignaturePolicyDigestBase64(event.target.value)} maxLength={128} autoComplete="off" required /></label>
      <label>URL calificadora de la política (opcional)<input value={signaturePolicyQualifierUrl} onChange={(event) => setSignaturePolicyQualifierUrl(event.target.value)} maxLength={2048} autoComplete="off" /></label>
      <p className="note-warning"><b>Protección:</b> estos identificadores no son contraseñas, pero no se muestran después de guardarse. Cópialos únicamente de la asignación oficial de DIAN.</p>
      <label className="check-line confirm-line"><input type="checkbox" checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)} />Confirmo que estos parámetros fueron asignados a esta empresa para habilitación y que no corresponden a producción.</label>
      {error ? <p className="form-error" role="alert">{error}</p> : null}
      <button className="secondary-action" disabled={!confirmed || saving}>{saving ? "Guardando…" : profile.software_test_set_id_configured || policyConfigured ? "Reemplazar parámetros" : "Guardar parámetros"}</button>
    </form>
  );
}

function TechnicalCredentialsForm({ token, companyId, profile, onSaved }: {
  token: string;
  companyId: string;
  profile: DianHabilitationProfile | null;
  onSaved: (profile: DianHabilitationProfile, action: "saved" | "revoked") => Promise<void>;
}) {
  const formRef = useRef<HTMLFormElement>(null);
  const [saving, setSaving] = useState(false);
  const [revoking, setRevoking] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = formRef.current;
    let formData: FormData | null = new FormData(form || undefined);
    let softwareId = String(formData.get("software_id") || "").trim();
    let softwarePassword = String(formData.get("software_password") || "");
    let certificate = fileFromFormData(formData, "certificate");
    let certificatePassword = String(formData.get("certificate_password") || "");
    let certificatePfxBase64 = "";
    let sensitiveDataCleared = false;
    const clearSensitiveData = () => {
      if (sensitiveDataCleared) return;
      sensitiveDataCleared = true;
      softwareId = "";
      softwarePassword = "";
      certificatePassword = "";
      certificatePfxBase64 = "";
      certificate = null;
      formData = null;
      form?.reset();
    };

    if (!profile || !certificate?.size || !softwareId || !softwarePassword || !certificatePassword) {
      clearSensitiveData();
      return;
    }
    if (certificate.size > MAX_CERTIFICATE_BYTES) {
      setError("El certificado supera el tamaño permitido para una carga segura.");
      clearSensitiveData();
      return;
    }

    setSaving(true);
    setError(null);
    try {
      certificatePfxBase64 = await fileToBase64(certificate);
      const nextProfile = await saveDianTechnicalCredentials(token, companyId, {
        software_id: softwareId,
        software_password: softwarePassword,
        certificate_pfx_base64: certificatePfxBase64,
        certificate_password: certificatePassword,
      });
      // Clear DOM inputs and local references before any state refresh can run.
      clearSensitiveData();
      await onSaved(nextProfile, "saved");
    } catch (cause) {
      setError(messageFor(cause, "No fue posible guardar las credenciales de habilitación."));
    } finally {
      clearSensitiveData();
      setSaving(false);
    }
  }

  async function revoke() {
    if (!profile || !window.confirm("¿Confirmas que deseas revocar las credenciales de habilitación de esta empresa?")) return;
    setRevoking(true);
    setError(null);
    try {
      await revokeDianTechnicalCredentials(token, companyId);
      const nextProfile = await dianHabilitationProfile(token, companyId);
      if (nextProfile) await onSaved(nextProfile, "revoked");
    } catch (cause) {
      setError(messageFor(cause, "No fue posible revocar las credenciales de habilitación."));
    } finally {
      setRevoking(false);
    }
  }

  if (!profile) {
    return (
      <section className="operations-form dian-habilitation-draft__form dian-habilitation-draft__form--locked">
        <h4>Credenciales técnicas</h4>
        <p>Primero registra el perfil fiscal. Luego un usuario autorizado podrá cargar el material técnico de habilitación.</p>
      </section>
    );
  }

  return (
    <form ref={formRef} className="operations-form dian-habilitation-draft__form" onSubmit={submit}>
      <div className="form-heading">
        <h4>Credenciales técnicas de habilitación</h4>
        <p>{profile.credential_configured ? "Hay material técnico cifrado. Puedes rotarlo sin revelar los valores actuales." : "Carga el material técnico asignado a esta empresa para habilitación."}</p>
      </div>
      <label>ID del software<input name="software_id" autoComplete="off" maxLength={255} required /></label>
      <label>Contraseña del software<input name="software_password" type="password" autoComplete="new-password" maxLength={4096} required /></label>
      <label>Certificado de pertenencia (.pfx o .p12)<input name="certificate" type="file" accept=".pfx,.p12,application/x-pkcs12" required /></label>
      <label>Contraseña del certificado<input name="certificate_password" type="password" autoComplete="new-password" maxLength={4096} required /></label>
      <p className="note-warning"><b>Protección:</b> el archivo se convierte localmente solo para este envío, se valida y se cifra. No pegues secretos en el chat ni los compartas con el piloto de adquirientes.</p>
      {error ? <p className="form-error" role="alert">{error}</p> : null}
      <div className="dian-habilitation-draft__form-actions">
        <button className="secondary-action" disabled={saving || revoking}>{saving ? "Validando y cifrando…" : profile.credential_configured ? "Rotar credenciales" : "Guardar credenciales"}</button>
        {profile.credential_configured ? <button className="dian-habilitation-draft__revoke" type="button" onClick={() => void revoke()} disabled={saving || revoking}>{revoking ? "Revocando…" : "Revocar"}</button> : null}
      </div>
    </form>
  );
}

function NumberingRangeForm({ token, companyId, profile, onCreated }: {
  token: string;
  companyId: string;
  profile: DianHabilitationProfile | null;
  onCreated: () => Promise<void>;
}) {
  const [prefix, setPrefix] = useState("");
  const [resolutionNumber, setResolutionNumber] = useState("");
  const [resolutionDate, setResolutionDate] = useState(() => todayValue());
  const [validFrom, setValidFrom] = useState(() => todayValue());
  const [validTo, setValidTo] = useState(() => todayValue());
  const [rangeFrom, setRangeFrom] = useState("");
  const [rangeTo, setRangeTo] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!profile || !confirmed) return;
    const start = Number(rangeFrom);
    const end = Number(rangeTo);
    if (!Number.isSafeInteger(start) || !Number.isSafeInteger(end) || start < 1 || end < start) {
      setError("El rango debe usar consecutivos enteros y el final no puede ser menor al inicial.");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await createDianNumberingRange(token, companyId, {
        prefix: prefix.trim(),
        resolution_number: resolutionNumber.trim(),
        resolution_date: resolutionDate,
        valid_from: validFrom,
        valid_to: validTo,
        range_from: start,
        range_to: end,
      });
      setPrefix("");
      setResolutionNumber("");
      setRangeFrom("");
      setRangeTo("");
      setConfirmed(false);
      await onCreated();
    } catch (cause) {
      setError(messageFor(cause, "No fue posible registrar el rango de numeración."));
    } finally {
      setSaving(false);
    }
  }

  if (!profile) {
    return (
      <section className="operations-form dian-habilitation-draft__form dian-habilitation-draft__form--locked">
        <h4>Nuevo rango de habilitación</h4>
        <p>Registra primero el perfil fiscal para reservar un rango de pruebas separado de producción.</p>
      </section>
    );
  }

  return (
    <form className="operations-form dian-habilitation-draft__form" onSubmit={submit}>
      <div className="form-heading"><h4>Nuevo rango de habilitación</h4><p>Utiliza solo la resolución y los consecutivos autorizados para este ambiente de pruebas.</p></div>
      <div className="dian-habilitation-draft__field-grid compact">
        <label>Prefijo<input value={prefix} onChange={(event) => setPrefix(event.target.value.toUpperCase())} maxLength={20} required /></label>
        <label>Número de resolución<input value={resolutionNumber} onChange={(event) => setResolutionNumber(event.target.value)} maxLength={100} required /></label>
        <label>Fecha de resolución<input type="date" value={resolutionDate} onChange={(event) => setResolutionDate(event.target.value)} required /></label>
        <label>Vigencia desde<input type="date" value={validFrom} onChange={(event) => setValidFrom(event.target.value)} required /></label>
        <label>Vigencia hasta<input type="date" value={validTo} min={validFrom} onChange={(event) => setValidTo(event.target.value)} required /></label>
        <label>Consecutivo inicial<input type="number" value={rangeFrom} onChange={(event) => setRangeFrom(event.target.value)} min="1" step="1" required /></label>
        <label>Consecutivo final<input type="number" value={rangeTo} onChange={(event) => setRangeTo(event.target.value)} min={rangeFrom || "1"} step="1" required /></label>
      </div>
      <label className="check-line confirm-line"><input type="checkbox" checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)} />Confirmo que esta numeración corresponde a la habilitación DIAN de esta empresa.</label>
      {error ? <p className="form-error" role="alert">{error}</p> : null}
      <button className="secondary-action" disabled={!confirmed || saving}>{saving ? "Registrando…" : "Registrar rango"}</button>
    </form>
  );
}

function NumberingRangeList({ ranges }: { ranges: DianNumberingRange[] }) {
  if (!ranges.length) {
    return <section className="dian-habilitation-draft__range-list empty"><h4>No hay rangos registrados.</h4><p>Cuando exista uno activo, podrás usar su siguiente consecutivo para cargar una prueba firmada.</p></section>;
  }
  return (
    <section className="dian-habilitation-draft__range-list" aria-label="Rangos de habilitación registrados">
      <h4>Rangos registrados</h4>
      <ul>
        {ranges.map((range) => (
          <li key={range.id} className={range.active ? "active" : "inactive"}>
            <div><b>{range.prefix} · {range.resolution_number}</b><small>{range.range_from} a {range.range_to} · próximo: {range.next_number}</small></div>
            <span>{range.active ? "Activo" : "Inactivo"}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}

function SignedTestDocumentForm({ token, companyId, profile, ranges, onQueued }: {
  token: string;
  companyId: string;
  profile: DianHabilitationProfile | null;
  ranges: DianNumberingRange[];
  onQueued: (document: DianElectronicDocument) => Promise<void>;
}) {
  const formRef = useRef<HTMLFormElement>(null);
  const activeRanges = ranges.filter((range) => range.active);
  const [rangeId, setRangeId] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [documentType, setDocumentType] = useState<DianElectronicDocumentType>("invoice");
  const [prefix, setPrefix] = useState("");
  const [consecutive, setConsecutive] = useState("");
  const [issueDate, setIssueDate] = useState(() => todayValue());
  const [currencyCode, setCurrencyCode] = useState("COP");
  const [payableAmount, setPayableAmount] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function chooseRange(id: string) {
    setRangeId(id);
    const range = activeRanges.find((item) => item.id === id);
    if (range) {
      setPrefix(range.prefix);
      setConsecutive(String(range.next_number));
    }
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const nextConsecutive = Number(consecutive);
    if (!profile || !file || !confirmed || !prefix.trim() || !Number.isSafeInteger(nextConsecutive) || nextConsecutive < 1) return;
    if (!file.name.toLowerCase().endsWith(".zip")) {
      setError("Selecciona un archivo ZIP que contenga el XML UBL firmado.");
      return;
    }
    if (file.size > MAX_SIGNED_ZIP_BYTES) {
      setError("El ZIP supera el límite permitido para una prueba de habilitación.");
      formRef.current?.reset();
      setFile(null);
      return;
    }
    setUploading(true);
    setError(null);
    try {
      const document = await uploadDianSignedTestDocument(token, companyId, {
        file,
        prefix: prefix.trim(),
        consecutive: nextConsecutive,
        issue_date: issueDate,
        document_type: documentType,
        currency_code: currencyCode.trim().toUpperCase(),
        payable_amount: payableAmount.trim(),
        confirmed: true,
      });
      formRef.current?.reset();
      setFile(null);
      setRangeId("");
      setPrefix("");
      setConsecutive("");
      setDocumentType("invoice");
      setIssueDate(todayValue());
      setCurrencyCode("COP");
      setPayableAmount("");
      setConfirmed(false);
      await onQueued(document);
    } catch (cause) {
      setError(messageFor(cause, "No fue posible cargar el documento de prueba."));
    } finally {
      setUploading(false);
    }
  }

  if (!profile) {
    return <p className="dian-habilitation-draft__locked-message">Registra el perfil fiscal antes de cargar un documento de prueba.</p>;
  }
  if (!profile.integration_enabled) {
    return <p className="dian-habilitation-draft__locked-message">El envío de pruebas está desactivado en este ambiente. Puedes revisar la configuración, pero no cargar ni encolar documentos desde esta vista.</p>;
  }
  if (!activeRanges.length) {
    return <p className="dian-habilitation-draft__locked-message">Registra un rango de habilitación activo antes de cargar un documento firmado.</p>;
  }

  return (
    <form ref={formRef} className="operations-form dian-habilitation-draft__upload-form" onSubmit={submit}>
      <div className="dian-habilitation-draft__field-grid compact">
        <label>Rango de habilitación<select value={rangeId} onChange={(event) => chooseRange(event.target.value)} required><option value="">Selecciona un rango</option>{activeRanges.map((range) => <option key={range.id} value={range.id}>{range.prefix} · próximo {range.next_number}</option>)}</select></label>
        <label>Tipo de documento<select value={documentType} onChange={(event) => setDocumentType(event.target.value as DianElectronicDocumentType)}>{(Object.keys(documentTypeLabels) as DianElectronicDocumentType[]).map((type) => <option key={type} value={type}>{documentTypeLabels[type]}</option>)}</select></label>
        <label>Prefijo<input value={prefix} onChange={(event) => setPrefix(event.target.value.toUpperCase())} maxLength={20} required /></label>
        <label>Consecutivo<input type="number" value={consecutive} onChange={(event) => setConsecutive(event.target.value)} min="1" step="1" required /></label>
        <label>Fecha de emisión<input type="date" value={issueDate} onChange={(event) => setIssueDate(event.target.value)} required /></label>
        <label>Moneda<input value={currencyCode} onChange={(event) => setCurrencyCode(event.target.value.toUpperCase())} minLength={3} maxLength={3} pattern="[A-Za-z]{3}" required /></label>
        <label>Valor total<input type="number" value={payableAmount} onChange={(event) => setPayableAmount(event.target.value)} min="0" step="0.01" required /></label>
        <label className="wide">ZIP firmado<input type="file" accept=".zip,application/zip,application/x-zip-compressed" onChange={(event) => setFile(event.target.files?.[0] || null)} required /></label>
      </div>
      <label className="check-line confirm-line"><input type="checkbox" checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)} />Confirmo que el ZIP contiene un único XML UBL firmado, corresponde al tipo, prefijo, consecutivo y valor indicados, y se envía solo a habilitación.</label>
      <p className="note-warning"><b>Antes de cargar:</b> si la conexión se interrumpe después del envío, revisa los eventos del documento; no intentes cargarlo de nuevo con el mismo consecutivo.</p>
      {error ? <p className="form-error" role="alert">{error}</p> : null}
      <button className="secondary-action" disabled={!file || !rangeId || !confirmed || uploading}>{uploading ? "Validando y encolando…" : "Cargar prueba firmada"}</button>
    </form>
  );
}

function HabilitationDocumentList({ documents, selectedDocumentId, onSelect }: {
  documents: DianElectronicDocument[];
  selectedDocumentId: string | null;
  onSelect: (documentId: string) => void;
}) {
  if (!documents.length) {
    return <div className="dian-habilitation-draft__documents-empty"><h4>Aún no hay documentos de prueba.</h4><p>Después de cargar un ZIP válido, aquí verás la cola y el resultado de cada prueba.</p></div>;
  }
  return (
    <section className="dian-habilitation-draft__documents" aria-label="Documentos de habilitación">
      <h4>Documentos de prueba</h4>
      <ul>
        {documents.map((document) => (
          <li key={document.id} className={selectedDocumentId === document.id ? "selected" : undefined}>
            <div className="dian-habilitation-draft__document-main">
              <div>
                <b>{document.document_number}</b>
                <small>{documentTypeLabels[document.document_type]} · {formatDate(document.issue_date)} · {formatMoney(document.payable_amount, document.currency_code)}</small>
                {document.corrects_document_id ? <small className="dian-habilitation-draft__correction">Corrección de una prueba rechazada</small> : null}
              </div>
              <span className={`dian-habilitation-draft__document-status ${document.status}`}>{documentStatusLabels[document.status] || "Requiere revisión"}</span>
            </div>
            <button type="button" onClick={() => onSelect(document.id)} aria-expanded={selectedDocumentId === document.id}>{selectedDocumentId === document.id ? "Ocultar eventos" : "Ver eventos"}</button>
          </li>
        ))}
      </ul>
    </section>
  );
}

function DocumentEventsPanel({ document, events, loading }: {
  document: DianElectronicDocument;
  events: DianDocumentEvent[];
  loading: boolean;
}) {
  return (
    <section className="dian-habilitation-draft__events" aria-live="polite" aria-labelledby="dian-habilitation-events-title">
      <h4 id="dian-habilitation-events-title">Eventos de {document.document_number}</h4>
      {loading ? <p>Consultando eventos…</p> : events.length ? (
        <ol>
          {events.map((event) => (
            <li key={event.id}>
              <time dateTime={event.created_at}>{formatDateTime(event.created_at)}</time>
              <div><b>{documentStatusLabels[event.status] || "Evento registrado"}</b>{event.message ? <p>{event.message}</p> : null}{event.code ? <small>Código: {event.code}</small> : null}</div>
            </li>
          ))}
        </ol>
      ) : <p>No hay eventos disponibles todavía.</p>}
    </section>
  );
}

function fiscalFormValues(profile: DianHabilitationProfile | null): FiscalFormState {
  return {
    legalName: profile?.legal_name || "",
    nit: profile?.nit || "",
    checkDigit: profile?.check_digit || "",
    email: profile?.email || "",
    address: profile?.address || "",
    cityCode: profile?.city_code || "",
    cityName: profile?.city_name || "",
    departmentCode: profile?.department_code || "",
    departmentName: profile?.department_name || "",
    taxResponsibilities: profile?.tax_responsibilities.join(", ") || "",
    phone: profile?.phone || "",
    taxRegime: profile?.tax_regime || "",
  };
}

function todayValue() {
  return new Date().toISOString().slice(0, 10);
}

async function fileToBase64(file: File): Promise<string> {
  const bytes = new Uint8Array(await file.arrayBuffer());
  let binary = "";
  for (let offset = 0; offset < bytes.length; offset += 8_192) {
    binary += String.fromCharCode(...bytes.subarray(offset, offset + 8_192));
  }
  return btoa(binary);
}

function fileFromFormData(formData: FormData, field: string): File | null {
  const value = formData.get(field);
  return value instanceof File ? value : null;
}

function formatDate(value: string) {
  const parsed = new Date(`${value.slice(0, 10)}T00:00:00Z`);
  return Number.isNaN(parsed.valueOf()) ? value : new Intl.DateTimeFormat("es-CO", { dateStyle: "medium", timeZone: "UTC" }).format(parsed);
}

function formatDateTime(value: string) {
  const parsed = new Date(value);
  return Number.isNaN(parsed.valueOf()) ? value : new Intl.DateTimeFormat("es-CO", { dateStyle: "medium", timeStyle: "short", timeZone: "America/Bogota" }).format(parsed);
}

function formatMoney(amount: string, currency: string) {
  try {
    return new Intl.NumberFormat("es-CO", { style: "currency", currency, maximumFractionDigits: 2 }).format(Number(amount));
  } catch {
    return `${amount} ${currency}`;
  }
}

function messageFor(cause: unknown, fallback: string) {
  return cause instanceof ApiError || cause instanceof Error ? cause.message : fallback;
}
