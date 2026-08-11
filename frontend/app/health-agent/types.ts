export type Company = { id: string; name: string; status: "active" | "disabled"; functional_currency: string };
export type LoginResult = { access_token: string; token_type: "bearer"; user_id: number; is_platform_admin: boolean };
export type Finding = { code: string; severity: "critical" | "warning" | "info"; message: string; evidence: Record<string, number>; recommendation: string };
export type Report = {
  company_id: string;
  generated_at: string;
  overall_status: "healthy" | "needs_attention" | "critical";
  summary: { finding_count: number; critical_count: number; warning_count: number; info_count: number };
  metrics: Record<string, number>;
  findings: Finding[];
};
export type Conversation = { outcome: "answered" | "clarification_needed" | "out_of_scope" | "temporarily_unavailable"; response: string; suggested_questions: string[]; llm_used: boolean; llm_model: string | null };
export type HealthResponse = { success: boolean; response: string; conversation_id: string; workflow: string | null; agent_id: string | null; report: Report | null; conversation: Conversation | null };
