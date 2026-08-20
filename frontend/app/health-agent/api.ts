import type {
  AccountingImportResult,
  CollectionFollowUp,
  CollectionFollowUpCreate,
  CollectionFollowUpUpdate,
  DataSource,
  DianAcquirerLookupsResponse,
  DianDocumentEventsResponse,
  DianElectronicDocument,
  DianHabilitationAccess,
  DianHabilitationProfile,
  DianHabilitationParametersInput,
  DianHabilitationProfileWrite,
  DianNumberingRange,
  DianNumberingRangeWrite,
  DianSignedTestDocumentUpload,
  DianTechnicalCredentialsInput,
  BankAccount,
  BankAccountsResponse,
  BankBalanceSnapshot,
  BankBalanceSnapshotsResponse,
  BankImportResult,
  BankReviewAction,
  BankTransaction,
  BankTransactionsResponse,
  Company,
  CompanyOnboardingResponse,
  BetaAccess,
  DianAcquirerLookup,
  ElectronicInvoiceEvidenceImportResult,
  ElectronicInvoiceEvidenceImportRowsResponse,
  ElectronicInvoiceEvidenceImportsResponse,
  ElectronicInvoiceExceptionsResponse,
  ExogenousInformationExceptionsResponse,
  HealthResponse,
  InvoiceTermsUpdate,
  ImportProfile,
  LoginResult,
  OpenReceivablesResponse,
  ProviderCredentialsResponse,
  PartyImportResult,
  PasswordChangeResponse,
} from "./types";

const baseUrl = () => {
  const configured = import.meta.env.VITE_API_BASE_URL?.trim();
  if (configured) return configured.replace(/\/$/, "");
  if (import.meta.env.DEV) return "http://localhost:8000/api/v1";
  throw new ApiError("La versión de prueba no tiene configurada la URL segura del servicio.");
};

export class ApiError extends Error {
  constructor(message: string) { super(message); this.name = "ApiError"; }
}

type ApiErrorPayload = {
  error?: { message?: unknown };
  detail?: unknown;
};

const validationFieldLabels: Record<string, string> = {
  legal_name: "la razón social",
  nit: "el NIT",
  check_digit: "el dígito de verificación",
  email: "el correo electrónico",
  address: "la dirección",
  city_code: "el código de municipio",
  city_name: "el municipio",
  department_code: "el código de departamento",
  department_name: "el departamento",
  tax_responsibilities: "las responsabilidades tributarias",
  software_test_set_id: "el conjunto de pruebas",
  signature_policy_identifier: "la política de firma",
  signature_policy_digest_base64: "el hash de la política de firma",
  signature_policy_qualifier_url: "la URL de la política de firma",
  software_id: "el ID del software",
  software_password: "la contraseña del software",
  certificate_pfx_base64: "el certificado",
  certificate_password: "la contraseña del certificado",
  prefix: "el prefijo",
  consecutive: "el consecutivo",
  issue_date: "la fecha de emisión",
  document_type: "el tipo de documento",
  currency_code: "la moneda",
  payable_amount: "el valor total",
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function safeValidationMessage(detail: unknown): string | null {
  if (!Array.isArray(detail)) return null;

  const fields = new Set<string>();
  for (const item of detail) {
    if (!isRecord(item) || !Array.isArray(item.loc)) continue;
    const field = [...item.loc].reverse().find((value) => typeof value === "string" && !["body", "query", "path"].includes(value));
    if (typeof field === "string") fields.add(validationFieldLabels[field] || "los datos ingresados");
  }

  if (!fields.size) return "Revisa los datos ingresados y vuelve a intentarlo.";
  const labels = [...fields].slice(0, 3);
  const joined = labels.length > 1 ? `${labels.slice(0, -1).join(", ")} y ${labels.at(-1)}` : labels[0];
  return `Revisa ${joined} y vuelve a intentarlo.`;
}

function safeErrorMessage(payload: unknown): string | null {
  if (!isRecord(payload)) return null;
  const source = payload as ApiErrorPayload;
  if (typeof source.error?.message === "string" && source.error.message.trim()) return source.error.message;

  const validationMessage = safeValidationMessage(source.detail);
  if (validationMessage) return validationMessage;
  if (typeof source.detail === "string" && source.detail.trim()) return source.detail;
  return null;
}

async function request<T>(path: string, options: RequestInit = {}, token?: string): Promise<T> {
  const isFormData = options.body instanceof FormData;
  const response = await fetch(`${baseUrl()}${path}`, {
    ...options,
    headers: {
      Accept: "application/json",
      ...(options.body && !isFormData ? { "Content-Type": "application/json" } : {}),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...options.headers,
    },
  });
  const payload: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    throw new ApiError(safeErrorMessage(payload) || "No fue posible completar la solicitud.");
  }
  return payload as T;
}

export const login = (email: string, password: string) => request<LoginResult>("/auth/login", { method: "POST", body: JSON.stringify({ email, password }) });
export const changePassword = (token: string, currentPassword: string, newPassword: string) => request<PasswordChangeResponse>(
  "/auth/change-password",
  { method: "POST", body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }) },
  token,
);
export const createBetaAccess = (token: string, payload: { full_name: string; email: string; temporary_password: string }) => request<BetaAccess>(
  "/admin/beta-access",
  { method: "POST", body: JSON.stringify(payload) },
  token,
);
export const companies = (token: string) => request<Company[]>("/companies/mine", {}, token);
export const onboardCompany = (token: string, payload: { tenant_name: string; company_name: string; functional_currency: string }) => request<CompanyOnboardingResponse>(
  "/companies/onboarding",
  { method: "POST", body: JSON.stringify({ country_code: "CO", ...payload }) },
  token,
);
export const askHealth = (token: string, companyId: string, message: string, conversationId: string | null) => request<HealthResponse>(
  `/companies/${companyId}/agents/accounting-health/chat`,
  { method: "POST", body: JSON.stringify({ message, ...(conversationId ? { conversation_id: conversationId } : {}) }) },
  token,
);
export const askReceivables = (token: string, companyId: string, message: string, conversationId: string | null) => request<HealthResponse>(
  `/companies/${companyId}/agents/receivables/chat`,
  { method: "POST", body: JSON.stringify({ message, ...(conversationId ? { conversation_id: conversationId } : {}) }) },
  token,
);
export const askPayables = (token: string, companyId: string, message: string, conversationId: string | null) => request<HealthResponse>(
  `/companies/${companyId}/agents/payables/chat`,
  { method: "POST", body: JSON.stringify({ message, ...(conversationId ? { conversation_id: conversationId } : {}) }) },
  token,
);
export const askCashFlow = (token: string, companyId: string, message: string, conversationId: string | null) => request<HealthResponse>(
  `/companies/${companyId}/agents/cash-flow/chat`,
  { method: "POST", body: JSON.stringify({ message, ...(conversationId ? { conversation_id: conversationId } : {}) }) },
  token,
);
export const askElectronicInvoicing = (token: string, companyId: string, message: string, conversationId: string | null) => request<HealthResponse>(
  `/companies/${companyId}/agents/electronic-invoicing/chat`,
  { method: "POST", body: JSON.stringify({ message, ...(conversationId ? { conversation_id: conversationId } : {}) }) },
  token,
);
export const askExogenousInformation = (token: string, companyId: string, message: string, conversationId: string | null) => request<HealthResponse>(
  `/companies/${companyId}/agents/exogenous-information/chat`,
  { method: "POST", body: JSON.stringify({ message, ...(conversationId ? { conversation_id: conversationId } : {}) }) },
  token,
);
export const askBankReconciliation = (token: string, companyId: string, message: string, conversationId: string | null) => request<HealthResponse>(
  `/companies/${companyId}/agents/bank-reconciliation/chat`,
  { method: "POST", body: JSON.stringify({ message, ...(conversationId ? { conversation_id: conversationId } : {}) }) },
  token,
);
export const askTreasury = (token: string, companyId: string, message: string, conversationId: string | null) => request<HealthResponse>(
  `/companies/${companyId}/agents/treasury/chat`,
  { method: "POST", body: JSON.stringify({ message, ...(conversationId ? { conversation_id: conversationId } : {}) }) },
  token,
);

export const openReceivables = (
  token: string,
  companyId: string,
  options: { limit?: number; offset?: number } = {},
) => {
  const parameters = new URLSearchParams();
  if (options.limit !== undefined) parameters.set("limit", String(options.limit));
  if (options.offset !== undefined) parameters.set("offset", String(options.offset));
  const query = parameters.size ? `?${parameters.toString()}` : "";
  return request<OpenReceivablesResponse>(`/companies/${companyId}/receivables/open-items${query}`, {}, token);
};

export const updateInvoiceTerms = (
  token: string,
  companyId: string,
  invoiceId: string,
  payload: InvoiceTermsUpdate,
) => request(
  `/companies/${companyId}/receivables/invoices/${invoiceId}/terms`,
  { method: "PATCH", body: JSON.stringify(payload) },
  token,
);

export const openPayables = (token: string, companyId: string, options: { limit?: number; offset?: number } = {}) => {
  const parameters = new URLSearchParams();
  if (options.limit !== undefined) parameters.set("limit", String(options.limit));
  if (options.offset !== undefined) parameters.set("offset", String(options.offset));
  const query = parameters.size ? `?${parameters.toString()}` : "";
  return request<OpenReceivablesResponse>(`/companies/${companyId}/payables/open-items${query}`, {}, token);
};

export const updatePayableTerms = (token: string, companyId: string, invoiceId: string, payload: InvoiceTermsUpdate) => request(
  `/companies/${companyId}/payables/invoices/${invoiceId}/terms`,
  { method: "PATCH", body: JSON.stringify(payload) }, token,
);

export const collectionFollowUps = (token: string, companyId: string, invoiceId: string) => request<CollectionFollowUp[]>(
  `/companies/${companyId}/collection-followups?invoice_id=${encodeURIComponent(invoiceId)}`,
  {},
  token,
);

export const createCollectionFollowUp = (
  token: string,
  companyId: string,
  payload: CollectionFollowUpCreate,
) => request<CollectionFollowUp>(
  `/companies/${companyId}/collection-followups`,
  { method: "POST", body: JSON.stringify(payload) },
  token,
);

export const updateCollectionFollowUp = (
  token: string,
  companyId: string,
  followUpId: string,
  payload: CollectionFollowUpUpdate,
) => request<CollectionFollowUp>(
  `/companies/${companyId}/collection-followups/${followUpId}`,
  { method: "PATCH", body: JSON.stringify(payload) },
  token,
);

export const bankAccounts = (token: string, companyId: string) => request<BankAccountsResponse>(
  `/companies/${companyId}/bank-reconciliation/accounts`,
  {},
  token,
);

export const createBankAccount = (
  token: string,
  companyId: string,
  payload: { name: string; bank_name?: string | null; currency_code: string; confirmed: true },
) => request<BankAccount>(
  `/companies/${companyId}/bank-reconciliation/accounts`,
  { method: "POST", body: JSON.stringify(payload) },
  token,
);

export const bankBalanceSnapshots = (token: string, companyId: string) => request<BankBalanceSnapshotsResponse>(
  `/companies/${companyId}/bank-reconciliation/balance-snapshots`,
  {},
  token,
);

export const createBankBalanceSnapshot = (
  token: string,
  companyId: string,
  bankAccountId: string,
  payload: { as_of_date: string; balance: string; confirmed: true },
) => request<BankBalanceSnapshot>(
  `/companies/${companyId}/bank-reconciliation/accounts/${bankAccountId}/balance-snapshots`,
  { method: "POST", body: JSON.stringify(payload) },
  token,
);

export const importBankStatement = (
  token: string,
  companyId: string,
  bankAccountId: string,
  file: File,
) => {
  const body = new FormData();
  body.set("file", file);
  return request<BankImportResult>(
    `/companies/${companyId}/bank-reconciliation/accounts/${bankAccountId}/imports`,
    { method: "POST", body },
    token,
  );
};

export const bankTransactions = (
  token: string,
  companyId: string,
  options: { bankAccountId?: string; limit?: number; offset?: number } = {},
) => {
  const parameters = new URLSearchParams();
  if (options.bankAccountId) parameters.set("bank_account_id", options.bankAccountId);
  if (options.limit !== undefined) parameters.set("limit", String(options.limit));
  if (options.offset !== undefined) parameters.set("offset", String(options.offset));
  const query = parameters.size ? `?${parameters.toString()}` : "";
  return request<BankTransactionsResponse>(
    `/companies/${companyId}/bank-reconciliation/transactions${query}`,
    {},
    token,
  );
};

export const reviewBankTransaction = (
  token: string,
  companyId: string,
  transactionId: string,
  action: BankReviewAction,
) => request<BankTransaction>(
  `/companies/${companyId}/bank-reconciliation/transactions/${transactionId}`,
  { method: "PATCH", body: JSON.stringify({ action, confirmed: true }) },
  token,
);

export const electronicInvoiceExceptions = (
  token: string,
  companyId: string,
  options: { limit?: number; offset?: number } = {},
) => {
  const parameters = new URLSearchParams();
  if (options.limit !== undefined) parameters.set("limit", String(options.limit));
  if (options.offset !== undefined) parameters.set("offset", String(options.offset));
  const query = parameters.size ? `?${parameters.toString()}` : "";
  return request<ElectronicInvoiceExceptionsResponse>(
    `/companies/${companyId}/electronic-invoicing/exceptions${query}`,
    {},
    token,
  );
};

export const electronicInvoiceEvidenceImports = (
  token: string,
  companyId: string,
) => request<ElectronicInvoiceEvidenceImportsResponse>(
  `/companies/${companyId}/electronic-invoicing/imports?limit=20`,
  {},
  token,
);

export const electronicInvoiceEvidenceImportRows = (
  token: string,
  companyId: string,
  importId: string,
) => request<ElectronicInvoiceEvidenceImportRowsResponse>(
  `/companies/${companyId}/electronic-invoicing/imports/${importId}/rows?limit=100`,
  {},
  token,
);

export const importElectronicInvoiceEvidence = (
  token: string,
  companyId: string,
  file: File,
) => {
  const body = new FormData();
  body.set("file", file);
  return request<ElectronicInvoiceEvidenceImportResult>(
    `/companies/${companyId}/electronic-invoicing/imports`,
    { method: "POST", body },
    token,
  );
};

export const exogenousInformationExceptions = (
  token: string,
  companyId: string,
  taxYear: number,
  options: { limit?: number; offset?: number } = {},
) => {
  const parameters = new URLSearchParams({ tax_year: String(taxYear) });
  if (options.limit !== undefined) parameters.set("limit", String(options.limit));
  if (options.offset !== undefined) parameters.set("offset", String(options.offset));
  return request<ExogenousInformationExceptionsResponse>(
    `/companies/${companyId}/exogenous-information/exceptions?${parameters.toString()}`,
    {},
    token,
  );
};

export const dataSources = (token: string, companyId: string) => request<DataSource[]>(
  `/data-sources?company_id=${encodeURIComponent(companyId)}`,
  {},
  token,
);

export const createInitialCsvDataSource = (token: string, company: Company) => request<DataSource>(
  "/data-sources",
  {
    method: "POST",
    body: JSON.stringify({
      tenant_id: company.tenant_id,
      company_id: company.id,
      connector_id: "csv_import",
      display_name: "Carga inicial CSV",
      kind: "file_import",
      mode: "file_upload",
      capabilities: ["parties", "invoices", "payments", "file_import_export"],
    }),
  },
  token,
);

export const createImportProfile = (
  token: string,
  dataSourceId: string,
  payload: {
    entity: "parties" | "invoices" | "payments";
    file_format: "csv";
    column_mapping: Record<string, string>;
    default_party_type?: "customer" | "supplier" | "both";
  },
) => request<ImportProfile>(
  `/data-sources/${dataSourceId}/profiles`,
  { method: "POST", body: JSON.stringify(payload) },
  token,
);

export const importParties = (token: string, dataSourceId: string, profileId: string, file: File) => {
  const body = new FormData();
  body.set("profile_id", profileId);
  body.set("file", file);
  return request<PartyImportResult>(`/data-sources/${dataSourceId}/imports/parties`, { method: "POST", body }, token);
};

export const importAccounting = (token: string, dataSourceId: string, profileId: string, file: File) => {
  const body = new FormData();
  body.set("profile_id", profileId);
  body.set("file", file);
  return request<AccountingImportResult>(`/data-sources/${dataSourceId}/imports/accounting`, { method: "POST", body }, token);
};

export const createDianDataSource = (token: string, company: Company) => request<DataSource>(
  "/data-sources",
  {
    method: "POST",
    body: JSON.stringify({
      tenant_id: company.tenant_id,
      company_id: company.id,
      connector_id: "dian_get_acquirer",
      display_name: "DIAN · Consulta de adquirientes",
      kind: "fiscal_authority",
      mode: "fiscal_service",
      provider_id: "dian",
    }),
  },
  token,
);

export const saveDianCredentials = (
  token: string,
  dataSourceId: string,
  credentials: Record<string, string>,
) => request<ProviderCredentialsResponse>(
  `/data-sources/${dataSourceId}/credentials`,
  { method: "PUT", body: JSON.stringify({ credentials }) },
  token,
);

export const revokeDianCredentials = (token: string, dataSourceId: string) => request<void>(
  `/data-sources/${dataSourceId}/credentials`,
  { method: "DELETE" },
  token,
);

export const lookupDianAcquirer = (
  token: string,
  companyId: string,
  payload: {
    data_source_id: string;
    document_type: string;
    document_number: string;
    purpose: "electronic_invoice_issuance";
    confirmed: true;
  },
) => request<DianAcquirerLookup>(
  `/companies/${companyId}/dian/acquirers/lookup`,
  { method: "POST", body: JSON.stringify(payload) },
  token,
);

export const dianAcquirerLookups = (token: string, companyId: string) => request<DianAcquirerLookupsResponse>(
  `/companies/${companyId}/dian/acquirers/lookups?limit=20`,
  {},
  token,
);

export const dianHabilitationProfile = (token: string, companyId: string) => request<DianHabilitationProfile | null>(
  `/companies/${companyId}/dian/electronic-invoicing/habilitation`,
  {},
  token,
);

export const dianHabilitationAccess = (token: string, companyId: string) => request<DianHabilitationAccess>(
  `/companies/${companyId}/dian/electronic-invoicing/habilitation/access`,
  {},
  token,
);

export const saveDianHabilitationProfile = (
  token: string,
  companyId: string,
  payload: DianHabilitationProfileWrite,
) => request<DianHabilitationProfile>(
  `/companies/${companyId}/dian/electronic-invoicing/habilitation`,
  { method: "PUT", body: JSON.stringify(payload) },
  token,
);

export const saveDianTechnicalCredentials = (
  token: string,
  companyId: string,
  payload: DianTechnicalCredentialsInput,
) => request<DianHabilitationProfile>(
  `/companies/${companyId}/dian/electronic-invoicing/technical-credentials`,
  { method: "PUT", body: JSON.stringify(payload) },
  token,
);

export const saveDianHabilitationParameters = (
  token: string,
  companyId: string,
  payload: DianHabilitationParametersInput,
) => request<DianHabilitationProfile>(
  `/companies/${companyId}/dian/electronic-invoicing/habilitation-parameters`,
  { method: "PUT", body: JSON.stringify(payload) },
  token,
);

export const revokeDianTechnicalCredentials = (token: string, companyId: string) => request<void>(
  `/companies/${companyId}/dian/electronic-invoicing/technical-credentials`,
  { method: "DELETE" },
  token,
);

export const dianNumberingRanges = (token: string, companyId: string) => request<DianNumberingRange[]>(
  `/companies/${companyId}/dian/electronic-invoicing/numbering-ranges`,
  {},
  token,
);

export const createDianNumberingRange = (
  token: string,
  companyId: string,
  payload: DianNumberingRangeWrite,
) => request<DianNumberingRange>(
  `/companies/${companyId}/dian/electronic-invoicing/numbering-ranges`,
  { method: "POST", body: JSON.stringify(payload) },
  token,
);

export const dianSignedTestDocuments = (token: string, companyId: string) => request<DianElectronicDocument[]>(
  `/companies/${companyId}/dian/electronic-invoicing/test-documents?limit=50`,
  {},
  token,
);

export const uploadDianSignedTestDocument = (
  token: string,
  companyId: string,
  payload: DianSignedTestDocumentUpload,
) => {
  const body = new FormData();
  body.set("file", payload.file);
  body.set("prefix", payload.prefix);
  body.set("consecutive", String(payload.consecutive));
  body.set("issue_date", payload.issue_date);
  body.set("document_type", payload.document_type);
  body.set("currency_code", payload.currency_code);
  body.set("payable_amount", payload.payable_amount);
  body.set("confirmed", "true");
  return request<DianElectronicDocument>(
    `/companies/${companyId}/dian/electronic-invoicing/test-documents`,
    { method: "POST", body },
    token,
  );
};

export const dianSignedTestDocumentEvents = (
  token: string,
  companyId: string,
  documentId: string,
  signal?: AbortSignal,
) => request<DianDocumentEventsResponse>(
  `/companies/${companyId}/dian/electronic-invoicing/test-documents/${encodeURIComponent(documentId)}/events`,
  { signal },
  token,
);
