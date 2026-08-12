import type {
  CollectionFollowUp,
  CollectionFollowUpCreate,
  CollectionFollowUpUpdate,
  Company,
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
  const response = await fetch(`${baseUrl()}${path}`, {
    ...options,
    headers: {
      Accept: "application/json",
      ...(options.body ? { "Content-Type": "application/json" } : {}),
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
