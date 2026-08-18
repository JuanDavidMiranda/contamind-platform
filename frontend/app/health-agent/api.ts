import type {
  CollectionFollowUp,
  CollectionFollowUpCreate,
  CollectionFollowUpUpdate,
  BankAccount,
  BankAccountsResponse,
  BankBalanceSnapshot,
  BankBalanceSnapshotsResponse,
  BankImportResult,
  BankReviewAction,
  BankTransaction,
  BankTransactionsResponse,
  Company,
  ElectronicInvoiceEvidenceImportResult,
  ElectronicInvoiceEvidenceImportRowsResponse,
  ElectronicInvoiceEvidenceImportsResponse,
  ElectronicInvoiceExceptionsResponse,
  HealthResponse,
  InvoiceTermsUpdate,
  LoginResult,
  OpenReceivablesResponse,
} from "./types";

const baseUrl = () => (import.meta.env.VITE_API_BASE_URL || "http://localhost:8000/api/v1").replace(/\/$/, "");

export class ApiError extends Error {
  constructor(message: string) { super(message); this.name = "ApiError"; }
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
    const source = payload as { error?: { message?: string }; detail?: string } | null;
    throw new ApiError(source?.error?.message || source?.detail || "No fue posible completar la solicitud.");
  }
  return payload as T;
}

export const login = (email: string, password: string) => request<LoginResult>("/auth/login", { method: "POST", body: JSON.stringify({ email, password }) });
export const companies = (token: string) => request<Company[]>("/companies/mine", {}, token);
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
