export type Company = { id: string; name: string; status: "active" | "disabled"; functional_currency: string };
export type LoginResult = { access_token: string; token_type: "bearer"; user_id: number; is_platform_admin: boolean };
export type Finding = { code: string; severity: "critical" | "warning" | "info"; message: string; evidence: Record<string, number>; recommendation: string };
export type ReceivablesBalance = { currency_code: string; amount: string };
export type ReceivablesAgingBucket = {
  key: string;
  invoices: number;
  outstanding_balances: ReceivablesBalance[];
};
export type ReportMetricValue = number | string | null | ReceivablesBalance[] | ReceivablesAgingBucket[];
export type Report = {
  company_id: string;
  generated_at: string;
  overall_status: "healthy" | "needs_attention" | "critical";
  summary: { finding_count: number; critical_count: number; warning_count: number; info_count: number };
  metrics: Record<string, ReportMetricValue> & {
    outstanding_balances?: ReceivablesBalance[];
    aging_buckets?: ReceivablesAgingBucket[];
  };
  findings: Finding[];
};
export type Conversation = { outcome: "answered" | "clarification_needed" | "out_of_scope" | "temporarily_unavailable"; response: string; suggested_questions: string[]; llm_used: boolean; llm_model: string | null };
export type HealthResponse = { success: boolean; response: string; conversation_id: string; workflow: string | null; agent_id: string | null; report: Report | null; conversation: Conversation | null };

export type CollectionFollowUpStatus = "pending" | "contacted" | "promise_to_pay" | "resolved" | "cancelled";

export type OpenReceivableItem = {
  invoice_id: string;
  invoice_number: string | null;
  issue_date: string;
  due_date: string | null;
  payment_terms_days: number | null;
  currency_code: string;
  total_amount: string;
  paid_amount: string;
  outstanding_amount: string;
  days_overdue: number | null;
  aging_bucket: string;
  latest_followup_status: CollectionFollowUpStatus | null;
  promised_date: string | null;
  mismatched_payment_count: number;
};

export type OpenReceivablesResponse = {
  as_of: string;
  total: number;
  can_manage: boolean;
  items: OpenReceivableItem[];
};

export type InvoiceTermsUpdate = {
  due_date?: string | null;
  payment_terms_days?: number | null;
  confirmed: true;
};

export type CollectionFollowUp = {
  id: string;
  company_id: string;
  invoice_id: string;
  status: CollectionFollowUpStatus;
  promised_date: string | null;
  note: string | null;
  created_by_user_id: number;
  updated_by_user_id: number;
  created_at: string;
  updated_at: string;
};

export type CollectionFollowUpCreate = {
  invoice_id: string;
  status: CollectionFollowUpStatus;
  promised_date?: string | null;
  note?: string | null;
  confirmed: true;
};

export type CollectionFollowUpUpdate = {
  status?: CollectionFollowUpStatus;
  promised_date?: string | null;
  note?: string | null;
  confirmed: true;
};
