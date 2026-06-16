/**
 * Shared SWR data hooks for the analytics dashboard.
 * All hooks revalidate every 60 seconds.
 */
import useSWR from "swr";

const REVALIDATE = 60; // seconds

async function fetcher<T>(url: string): Promise<T> {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`Fetch error: ${res.status} ${res.statusText}`);
  return res.json() as Promise<T>;
}

// ─────────────────────────────────────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────────────────────────────────────

export interface DecisionRecord {
  application_id: string;
  decision: string;
  created_at: string;
  loan_amount: number;
  pd_score: number;
  top_factors?: string[];
  reviewer?: string;
  review_complete_at?: string;
  fraud_probability?: number;
  loan_purpose?: string;
  loan_term?: number;
  annual_income?: number;
  bureau_score?: number;
}

export interface DecisionsStats {
  total: number;
  approved: number;
  rejected: number;
  manual_review: number;
  approval_rate: number;
  avg_pd_score: number;
  avg_fraud_probability: number;
  fraud_flag_count: number;
  daily_series: Array<{ date: string; approved: number; rejected: number; manual_review: number }>;
  weekly_trend: Array<{ week: string; APPROVE: number; REJECT: number; MANUAL_REVIEW: number }>;
  by_purpose: Array<{ purpose: string; count: number }>;
  decisions: DecisionRecord[];
}

export interface ModelMetrics {
  credit_risk: {
    auc: number;
    ks: number;
    precision: number;
    recall: number;
    f1: number;
    version: string;
    trained_at: string;
  };
  fraud_detection: {
    auc: number;
    precision: number;
    recall: number;
    f1: number;
    version: string;
    trained_at: string;
  };
  feature_importances: Array<{ feature: string; importance: number }>;
  roc_curve: Array<{ fpr: number; tpr: number }>;
  version_history: Array<{ version: string; auc: number; ks: number; date: string }>;
}

export interface DriftReport {
  generated_at: string;
  drift_status: "stable" | "minor" | "major";
  features: Array<{
    feature: string;
    psi: number;
    ks_pvalue: number;
    status: "stable" | "minor" | "major";
  }>;
}

export interface FairLendingReport {
  generated_at: string;
  dir_score: number;
  dir_flag: boolean;
  approval_parity_p_value: number;
  geographic_flags: string[];
  summary_text: string;
  approval_by_group: Array<{ group: string; approval_rate: number; count: number }>;
  approval_by_state: Array<{ state: string; approval_rate: number; count: number }>;
}

// ─────────────────────────────────────────────────────────────────────────────
// Hooks
// ─────────────────────────────────────────────────────────────────────────────

export function useDecisionsData(dateRange?: string | { start: string; end: string }) {
  let params = "";
  if (dateRange) {
    if (typeof dateRange === "string") {
      // Convert preset string ("7d", "30d", "90d", "custom") to a date range
      const days = dateRange === "7d" ? 7 : dateRange === "90d" ? 90 : 30;
      const end = new Date();
      const start = new Date();
      start.setDate(start.getDate() - days);
      params = `?start=${start.toISOString().split("T")[0]}&end=${end.toISOString().split("T")[0]}`;
    } else {
      params = `?start=${dateRange.start}&end=${dateRange.end}`;
    }
  }
  return useSWR<DecisionsStats>(`/api/v1/analytics/decisions${params}`, fetcher, {
    refreshInterval: REVALIDATE * 1000,
  });
}

export function useModelMetrics() {
  return useSWR<ModelMetrics>("/api/v1/analytics/model-metrics", fetcher, {
    refreshInterval: REVALIDATE * 1000,
  });
}

export function useDriftReport() {
  return useSWR<DriftReport>("/api/v1/analytics/drift", fetcher, {
    refreshInterval: REVALIDATE * 1000,
  });
}

export function useFairLendingReport() {
  return useSWR<FairLendingReport>("/api/v1/analytics/fair-lending", fetcher, {
    refreshInterval: REVALIDATE * 1000,
  });
}

// ─────────────────────────────────────────────────────────────────────────────
// Mock fallback data (used when API is unavailable)
// ─────────────────────────────────────────────────────────────────────────────

function getMockDecisionsData(): DecisionsStats {
  const today = new Date();
  const daily_series = Array.from({ length: 30 }, (_, i) => {
    const d = new Date(today);
    d.setDate(d.getDate() - (29 - i));
    const date = d.toISOString().slice(0, 10);
    const total = Math.floor(Math.random() * 200 + 100);
    const approved = Math.floor(total * (0.55 + Math.random() * 0.15));
    const rejected = Math.floor((total - approved) * 0.7);
    const manual_review = total - approved - rejected;
    return { date, approved, rejected, manual_review };
  });

  const DECISION_TYPES = ["APPROVE", "REJECT", "MANUAL_REVIEW"];
  const PURPOSES = ["Personal", "Debt Consolidation", "Home Improvement", "Auto", "Medical", "Education"];
  const REASON_CODES = ["HIGH_PD", "HIGH_DTI", "INSUFFICIENT_INCOME", "FRAUD_RISK", "CREDIT_HISTORY"];
  const REVIEWERS = ["Alice Wang", "Bob Smith", "Carol Davis", "Dan Chen"];

  const decisions: DecisionRecord[] = Array.from({ length: 50 }, (_, i) => {
    const decision = DECISION_TYPES[Math.floor(Math.random() * DECISION_TYPES.length)];
    const daysAgo = Math.floor(Math.random() * 30);
    const d = new Date(today);
    d.setDate(d.getDate() - daysAgo);
    return {
      application_id: `APP-${String(1000 + i).padStart(6, "0")}`,
      decision,
      created_at: d.toISOString(),
      loan_amount: Math.floor(Math.random() * 45000 + 5000),
      pd_score: parseFloat((Math.random() * 0.4).toFixed(3)),
      top_factors: decision === "REJECT"
        ? [REASON_CODES[Math.floor(Math.random() * REASON_CODES.length)], REASON_CODES[Math.floor(Math.random() * REASON_CODES.length)]]
        : undefined,
      reviewer: decision === "MANUAL_REVIEW" ? REVIEWERS[Math.floor(Math.random() * REVIEWERS.length)] : undefined,
      review_complete_at: decision === "MANUAL_REVIEW" ? d.toISOString() : undefined,
      fraud_probability: parseFloat((Math.random() * 0.15).toFixed(3)),
      loan_purpose: PURPOSES[Math.floor(Math.random() * PURPOSES.length)],
      loan_term: [12, 24, 36, 48, 60][Math.floor(Math.random() * 5)],
      annual_income: Math.floor(Math.random() * 120000 + 30000),
      bureau_score: Math.floor(Math.random() * 350 + 450),
    };
  });

  return {
    total: 12547,
    approved: 7842,
    rejected: 3891,
    manual_review: 814,
    approval_rate: 62.5,
    avg_pd_score: 0.067,
    avg_fraud_probability: 0.041,
    fraud_flag_count: 312,
    daily_series,
    by_purpose: [
      { purpose: "Personal", count: 4200 },
      { purpose: "Debt Consolidation", count: 2800 },
      { purpose: "Home Improvement", count: 1900 },
      { purpose: "Auto", count: 1600 },
      { purpose: "Medical", count: 1200 },
      { purpose: "Education", count: 847 },
    ],
    weekly_trend: Array.from({ length: 8 }, (_, i) => ({
      week: `W${i + 1}`,
      APPROVE: 80 + i * 5 + Math.floor(Math.random() * 10),
      REJECT: 20 + Math.floor(Math.random() * 5),
      MANUAL_REVIEW: 10 + Math.floor(Math.random() * 3),
    })),
    decisions,
  };
}

function getMockModelMetrics(): ModelMetrics {
  return {
    credit_risk: {
      auc: 0.812,
      ks: 0.421,
      precision: 0.789,
      recall: 0.741,
      f1: 0.764,
      version: "v1",
      trained_at: "2026-02-01T10:00:00Z",
    },
    fraud_detection: {
      auc: 0.893,
      precision: 0.921,
      recall: 0.874,
      f1: 0.897,
      version: "v1",
      trained_at: "2026-02-01T10:30:00Z",
    },
    feature_importances: [
      { feature: "credit_score", importance: 0.28 },
      { feature: "debt_to_income_ratio", importance: 0.19 },
      { feature: "annual_income", importance: 0.15 },
      { feature: "repayment_capacity", importance: 0.12 },
      { feature: "credit_utilization", importance: 0.09 },
      { feature: "income_stability_score", importance: 0.07 },
      { feature: "derogatory_penalty", importance: 0.05 },
      { feature: "log_loan_amount", importance: 0.03 },
      { feature: "credit_age_score", importance: 0.02 },
    ],
    roc_curve: Array.from({ length: 50 }, (_, i) => {
      const fpr = i / 49;
      const tpr = Math.min(1, fpr + (0.3 + Math.random() * 0.2) * (1 - fpr));
      return { fpr, tpr };
    }),
    version_history: [
      { version: "v1", auc: 0.812, ks: 0.421, date: "2026-02-01" },
    ],
  };
}

function getMockDriftReport(): DriftReport {
  const features = [
    "credit_score", "annual_income", "debt_to_income_ratio",
    "credit_utilization", "income_stability_score", "repayment_capacity",
    "derogatory_penalty", "log_loan_amount",
  ];
  return {
    generated_at: new Date().toISOString(),
    drift_status: "minor",
    features: features.map((f) => {
      const psi = Math.random() * 0.3;
      return {
        feature: f,
        psi,
        ks_pvalue: Math.random(),
        status: psi < 0.1 ? "stable" : psi < 0.25 ? "minor" : "major",
      };
    }),
  };
}

function getMockFairLendingReport(): FairLendingReport {
  return {
    generated_at: new Date().toISOString(),
    dir_score: 0.87,
    dir_flag: false,
    approval_parity_p_value: 0.12,
    geographic_flags: ["MS", "WV"],
    summary_text: "Approval rates are broadly equitable across demographic groups. DIR of 0.87 exceeds the 4/5ths threshold (0.80). Geographic analysis flags 2 states with approval rates below mean.",
    approval_by_group: [
      { group: "Group A (Control)", approval_rate: 65.2, count: 4821 },
      { group: "Group B", approval_rate: 56.7, count: 3891 },
      { group: "Group C", approval_rate: 61.4, count: 2904 },
      { group: "Group D", approval_rate: 58.9, count: 931 },
    ],
    approval_by_state: [
      { state: "CA", approval_rate: 68.4, count: 1820 },
      { state: "TX", approval_rate: 64.1, count: 1540 },
      { state: "NY", approval_rate: 66.8, count: 1280 },
      { state: "FL", approval_rate: 61.2, count: 980 },
      { state: "IL", approval_rate: 63.5, count: 740 },
      { state: "MS", approval_rate: 48.9, count: 310 },
      { state: "WV", approval_rate: 46.2, count: 210 },
    ],
  };
}
