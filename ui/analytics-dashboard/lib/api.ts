/**
 * api.ts — Typed fetch wrappers for all S3–S6 endpoints.
 * Used by portfolio, scorecard, and compliance dashboard pages.
 */

const API_BASE =
  process.env.NEXT_PUBLIC_DECISION_API_URL ?? "http://localhost:8000";

function getToken(): string {
  if (typeof window === "undefined") return "";
  return localStorage.getItem("decision_api_token") ?? "";
}

async function apiFetch<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${getToken()}`,
      ...(options?.headers ?? {}),
    },
  });
  if (res.status === 403) throw new Error("FORBIDDEN");
  if (!res.ok) throw new Error(`API error ${res.status}: ${res.statusText}`);
  return res.json() as Promise<T>;
}

// ─────────────────────────────────────────────────────────────────────────────
// Portfolio types
// ─────────────────────────────────────────────────────────────────────────────

export interface PortfolioSnapshot {
  computed_at: string;
  total_accounts: number;
  total_exposure: number;
  wa_pd: number;
  wa_lgd: number;
  wa_el: number;
  expected_loss_dollars: number;
  risk_rating_distribution: Record<string, number>;
  delinquency_rates: Record<string, number>;
  approval_rate_mtd: number;
  approval_rate_qtd: number;
}

export interface ConcentrationBreakdownEntry {
  count: number;
  exposure: number;
  pct_of_total: number;
}

export interface ConcentrationDimension {
  dimension: string;
  breakdown: Record<string, ConcentrationBreakdownEntry>;
  configured_limit_pct: number;
  max_observed_pct: number;
  at_risk: boolean;
  in_breach: boolean;
}

export interface ConcentrationBreach {
  dimension: string;
  segment_value: string;
  observed_pct: number;
  limit_pct: number;
  excess_pct: number;
  severity: "Warning" | "Breach";
}

export interface ConcentrationReport {
  computed_at: string;
  dimensions: ConcentrationDimension[];
  breaches: ConcentrationBreach[];
  total_accounts: number;
  total_exposure: number;
}

export interface RebalancingAction {
  segment: string;
  dimension: string;
  current_pct: number;
  limit_pct: number;
  recommended_action: "REDUCE" | "HOLD" | "GROW";
  urgency: "Immediate" | "Monitor" | "Opportunistic";
  reasoning: string;
  estimated_wa_pd_impact: number;
}

export interface RebalancingPlan {
  generated_at: string;
  portfolio_wa_pd_current: number;
  portfolio_wa_pd_projected: number;
  actions: RebalancingAction[];
  summary: string;
}

export interface HeatmapRow {
  label: string;
  value: number;
  pct_of_total: number;
  status: "ok" | "warning" | "breach";
}

// ─────────────────────────────────────────────────────────────────────────────
// Scorecard types
// ─────────────────────────────────────────────────────────────────────────────

export interface ScorecardRow {
  feature: string;
  bin_label: string;
  bin_lower: number | null;
  bin_upper: number | null;
  count: number;
  event_rate: number;
  woe: number;
  iv: number;
  points: number;
  feature_iv: number;
  low_iv: boolean;
  iv_label: string;
  scorecard_type?: string;
}

// ─────────────────────────────────────────────────────────────────────────────
// Compliance types
// ─────────────────────────────────────────────────────────────────────────────

export interface PolicyRuleStats {
  rule_id: string;
  rule_description: string;
  decisions_evaluated: number;
  compliance_count: number;
  compliance_rate: number;
  exception_count: number;
  waiver_count: number;
  trend_30d: number;
  status: "Healthy" | "Watch" | "Breach";
}

export interface PolicyAdherenceReport {
  period: string;
  generated_at: string;
  total_decisions: number;
  overall_compliance_rate: number;
  rules: PolicyRuleStats[];
  top_exception_rules: string[];
  summary: string;
}

export interface Waiver {
  waiver_id: string;
  application_id: string;
  policy_rule_id: string;
  policy_rule_description: string;
  waiver_reason: string;
  requested_by: string;
  requested_at: string;
  approved_by: string | null;
  approved_at: string | null;
  denied_by: string | null;
  denied_at: string | null;
  denial_reason: string | null;
  expires_at: string | null;
  scope: "single" | "portfolio";
  status: "pending" | "approved" | "denied" | "expired";
  notes: string | null;
}

export interface FairLendingReport {
  dir_score: number;
  approval_parity_p_value: number;
  air_by_class: Record<string, number>;
  [key: string]: unknown;
}

// ─────────────────────────────────────────────────────────────────────────────
// API functions — Portfolio
// ─────────────────────────────────────────────────────────────────────────────

export const fetchPortfolioSnapshot = () =>
  apiFetch<PortfolioSnapshot>("/v1/portfolio/snapshot");

export const fetchConcentrationReport = () =>
  apiFetch<ConcentrationReport>("/v1/portfolio/concentration");

export const fetchRebalancingPlan = () =>
  apiFetch<RebalancingPlan>("/v1/portfolio/rebalancing");

export const fetchHeatmap = (dimension: string = "sector") =>
  apiFetch<HeatmapRow[]>(`/v1/portfolio/heatmap?dimension=${dimension}`);

// ─────────────────────────────────────────────────────────────────────────────
// API functions — Scorecard
// ─────────────────────────────────────────────────────────────────────────────

export const fetchScorecard = (modelName: string) =>
  apiFetch<{ rows: ScorecardRow[]; scorecard_type: string; row_count: number }>(
    `/v1/models/${modelName}/scorecard`
  );

// ─────────────────────────────────────────────────────────────────────────────
// API functions — Compliance
// ─────────────────────────────────────────────────────────────────────────────

export const fetchPolicyAdherence = (period: string = "30d") =>
  apiFetch<PolicyAdherenceReport>(`/v1/compliance/policy-adherence?period=${period}`);

export const fetchPendingWaivers = () =>
  apiFetch<Waiver[]>("/v1/waivers?status=pending");

export const approveWaiver = (waiverId: string, approvedBy: string) =>
  apiFetch<Waiver>(`/v1/waivers/${waiverId}/approve`, {
    method: "POST",
    body: JSON.stringify({ approved_by: approvedBy }),
  });

export const denyWaiver = (
  waiverId: string,
  deniedBy: string,
  denialReason: string
) =>
  apiFetch<Waiver>(`/v1/waivers/${waiverId}/deny`, {
    method: "POST",
    body: JSON.stringify({ denied_by: deniedBy, denial_reason: denialReason }),
  });

export const fetchFairLendingReport = () =>
  apiFetch<FairLendingReport>("/v1/fair-lending/report");

export const triggerExamPacket = () =>
  apiFetch<{ status: string; packet_id?: string }>(
    "/v1/reports/exam-packets/generate",
    { method: "POST", body: JSON.stringify({}) }
  );

export const fetchExamPackets = () =>
  apiFetch<Array<{ packet_id: string; status: string; created_at: string }>>(
    "/v1/reports/exam-packets"
  );
