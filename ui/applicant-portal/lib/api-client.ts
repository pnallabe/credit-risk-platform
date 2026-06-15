/**
 * Typed API client for the Credit Risk Decision API.
 *
 * All calls return a Result<T, ApiError> — no thrown errors.
 * Bearer token is attached automatically if available.
 */

// ─────────────────────────────────────────────────────────────────────────────
// Types mirroring the decision-api OpenAPI schema
// ─────────────────────────────────────────────────────────────────────────────

export type LoanPurpose =
  | "personal"
  | "auto"
  | "home_improvement"
  | "medical"
  | "education"
  | "debt_consolidation";

export type EmploymentStatus = "employed" | "self-employed" | "unemployed" | "retired";

export type LoanTermMonths = 12 | 24 | 36 | 48 | 60;

export interface LoanApplicationPayload {
  application_id: string;
  customer_id: string;
  credit_score: number;
  annual_income: number;
  employment_status: EmploymentStatus;
  employer_tenure_months: number;
  debt_to_income_ratio: number;
  existing_debt_amount: number;
  loan_amount: number;
  loan_purpose: LoanPurpose;
  loan_term_months: LoanTermMonths;
  num_open_accounts: number;
  num_derogatory_marks: number;
  months_since_last_delinquency: number | null;
}

export interface ExplanationFactor {
  feature: string;
  shap_value: number;
  direction: string;
}

export interface DecisionResponse {
  application_id: string;
  decision: "APPROVE" | "REJECT" | "MANUAL_REVIEW";
  recommended_rate: number | null;
  loan_terms: Record<string, unknown>;
  reason_codes: string[];
  explanation: ExplanationFactor[];
  decision_latency_ms: number;
  audit_log_id: string;
  fraud_probability: number;
  pd_score: number;
  alternatives?: any[];
}

export interface AuditRecord {
  application_id: string;
  logged_at: string;
  input_features: Record<string, unknown>;
  model_version: string;
  feature_version: string;
  fraud_score: number;
  risk_score: number;
  decision_output: string;
  reason_codes: string[];
  decision_latency_ms: number;
}

export interface ApiError {
  status: number;
  message: string;
  detail?: unknown;
}

export type Result<T> =
  | { ok: true; data: T; latencyMs: number }
  | { ok: false; error: ApiError; latencyMs: number };

// ─────────────────────────────────────────────────────────────────────────────
// Config
// ─────────────────────────────────────────────────────────────────────────────

const API_BASE =
  typeof window !== "undefined"
    ? process.env.NEXT_PUBLIC_DECISION_API_URL || "/api/v1"
    : process.env.DECISION_API_URL || "http://localhost:8081/v1";

// ─────────────────────────────────────────────────────────────────────────────
// Core fetch wrapper
// ─────────────────────────────────────────────────────────────────────────────

async function apiFetch<T>(
  path: string,
  options: RequestInit = {},
  token?: string
): Promise<Result<T>> {
  const start = performance.now();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(options.headers as Record<string, string>),
  };
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  try {
    const resp = await fetch(`${API_BASE}${path}`, { ...options, headers });
    const latencyMs = Math.round(performance.now() - start);

    if (!resp.ok) {
      let detail: unknown;
      try {
        detail = await resp.json();
      } catch {
        detail = await resp.text();
      }
      if (process.env.NODE_ENV === "development") {
        console.error(`[API] ${options.method || "GET"} ${path} → ${resp.status}`, detail);
      }
      return {
        ok: false,
        latencyMs,
        error: { status: resp.status, message: resp.statusText, detail },
      };
    }

    const data: T = await resp.json();
    if (process.env.NODE_ENV === "development") {
      console.info(`[API] ${options.method || "GET"} ${path} → ${resp.status} (${latencyMs}ms)`);
    }
    return { ok: true, data, latencyMs };
  } catch (err) {
    const latencyMs = Math.round(performance.now() - start);
    return {
      ok: false,
      latencyMs,
      error: { status: 0, message: String(err) },
    };
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// API methods
// ─────────────────────────────────────────────────────────────────────────────

export const apiClient = {
  /** POST /v1/decisions — submit a loan application for a decision */
  submitDecision(
    payload: LoanApplicationPayload,
    token?: string
  ): Promise<Result<DecisionResponse>> {
    return apiFetch<DecisionResponse>(
      "/decisions",
      { method: "POST", body: JSON.stringify(payload) },
      token
    );
  },

  /** GET /v1/decisions/{id}/audit — retrieve full audit record */
  getAuditRecord(applicationId: string, token?: string): Promise<Result<AuditRecord>> {
    return apiFetch<AuditRecord>(`/decisions/${encodeURIComponent(applicationId)}/audit`, {}, token);
  },

  /** GET /v1/health — health check */
  health(): Promise<Result<Record<string, unknown>>> {
    return apiFetch<Record<string, unknown>>("/health");
  },
};
