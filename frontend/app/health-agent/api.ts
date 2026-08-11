import type { Company, HealthResponse, LoginResult } from "./types";

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
