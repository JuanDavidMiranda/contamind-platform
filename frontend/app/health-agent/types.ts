export type Company = { id: string; name: string; status: "active" | "disabled"; functional_currency: string };
export type LoginResult = { access_token: string; token_type: "bearer"; user_id: number; is_platform_admin: boolean };
export type Finding = { code: string; severity: "critical" | "warning" | "info"; message: string; evidence: Record<string, number>; recommendation: string };
export type ReceivablesBalance = { currency_code: string; amount: string };
export type ReceivablesAgingBucket = {
  key: string;
  invoices: number;
  outstanding_balances: ReceivablesBalance[];
};
export type CashFlowAmount = { currency_code: string; amount: string };
export type CashFlowPeriod = {
  key: string;
  start_date: string | null;
  end_date: string | null;
  receivable_invoices: number;
  payable_invoices: number;
  projected_inflows: CashFlowAmount[];
  projected_outflows: CashFlowAmount[];
  net_movements: CashFlowAmount[];
};
export type ReportMetricValue =
  | number
  | string
  | null
  | ReceivablesBalance[]
  | ReceivablesAgingBucket[]
  | CashFlowPeriod[];
export type Report = {
  company_id: string;
  generated_at: string;
  overall_status: "healthy" | "needs_attention" | "critical";
  summary: { finding_count: number; critical_count: number; warning_count: number; info_count: number };
  metrics: Record<string, ReportMetricValue> & {
    outstanding_balances?: ReceivablesBalance[];
    aging_buckets?: ReceivablesAgingBucket[];
    projected_inflows_90d?: CashFlowAmount[];
    projected_outflows_90d?: CashFlowAmount[];
    net_movements_90d?: CashFlowAmount[];
    cash_flow_periods?: CashFlowPeriod[];
    projected_inflows_30d?: CashFlowAmount[];
    projected_outflows_30d?: CashFlowAmount[];
    net_projected_movements_30d?: CashFlowAmount[];
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

export type BankAccount = {
  id: string;
  name: string;
  bank_name: string | null;
  currency_code: string;
  status: "active" | "disabled";
  created_by_user_id: number;
  created_at: string;
};

export type BankAccountsResponse = {
  can_manage: boolean;
  can_configure: boolean;
  accounts: BankAccount[];
};

export type BankTransactionStatus =
  | "pending"
  | "suggested"
  | "reconciled"
  | "dismissed"
  | "excluded";

export type BankTransaction = {
  id: string;
  bank_account_id: string;
  transaction_date: string;
  amount: string;
  currency_code: string;
  description: string | null;
  reference: string | null;
  status: BankTransactionStatus;
  match_candidate_count: number;
  suggested_payment_id: string | null;
  suggested_payment_date: string | null;
  matched_payment_id: string | null;
  reviewed_by_user_id: number | null;
  reviewed_at: string | null;
};

export type BankTransactionsResponse = {
  total: number;
  can_manage: boolean;
  items: BankTransaction[];
};

export type BankImportResult = {
  import_id: string;
  accepted_rows: number;
  duplicate_rows: number;
  rejections: Array<{ row_number: number; message: string }>;
};

export type BankReviewAction = "confirm" | "dismiss" | "exclude" | "reopen";
