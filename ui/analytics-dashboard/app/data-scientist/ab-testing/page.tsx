"use client";

import { useState, useEffect } from "react";
import { DashboardShell } from "@/components/DashboardShell";

// ─── Types ────────────────────────────────────────────────────────────────────

interface Experiment {
  experiment_id: string;
  name: string;
  description: string;
  status: "DRAFT" | "RUNNING" | "PAUSED" | "COMPLETED" | "HALTED";
  champion_policy_version: string;
  challenger_policy_version: string;
  traffic_split: number;
  created_at: string;
  started_at?: string;
}

interface SignificanceReport {
  experiment_id: string;
  n_control: number;
  n_treatment: number;
  approval_rate_control: number;
  approval_rate_treatment: number;
  z_score: number;
  p_value: number;
  ci_lower: number;
  ci_upper: number;
  power_achieved: number;
  is_significant: boolean;
  guardrail_breached: boolean;
  recommendation: "PROMOTE" | "HOLD" | "REJECT" | "INSUFFICIENT_DATA";
}

// ─── Mock data ─────────────────────────────────────────────────────────────────

const MOCK_EXPERIMENTS: Experiment[] = [
  {
    experiment_id: "exp-001",
    name: "Credit Card PD Threshold Test",
    description: "Testing a relaxed PD threshold (0.20 → 0.22) on credit card originations",
    status: "RUNNING",
    champion_policy_version: "cc-v3.1",
    challenger_policy_version: "cc-v3.2-relaxed",
    traffic_split: 0.5,
    created_at: "2025-03-15T09:00:00Z",
    started_at: "2025-03-15T10:00:00Z",
  },
  {
    experiment_id: "exp-002",
    name: "BNPL Fraud Guardrail Test",
    description: "Stricter fraud hold threshold (0.60 → 0.55) for BNPL new accounts",
    status: "COMPLETED",
    champion_policy_version: "bnpl-v1.0",
    challenger_policy_version: "bnpl-v1.1-strict",
    traffic_split: 0.3,
    created_at: "2025-02-01T08:00:00Z",
    started_at: "2025-02-01T09:00:00Z",
  },
  {
    experiment_id: "exp-003",
    name: "DTI Cap Adjustment — Personal Loan",
    description: "Pilot raising DTI cap from 43% to 46% on personal loans under $15k",
    status: "DRAFT",
    champion_policy_version: "pl-v2.0",
    challenger_policy_version: "pl-v2.1-dti46",
    traffic_split: 0.2,
    created_at: "2025-04-08T14:00:00Z",
  },
];

const MOCK_REPORTS: Record<string, SignificanceReport> = {
  "exp-001": {
    experiment_id: "exp-001",
    n_control: 1_842,
    n_treatment: 1_789,
    approval_rate_control: 0.647,
    approval_rate_treatment: 0.681,
    z_score: 2.14,
    p_value: 0.032,
    ci_lower: 0.003,
    ci_upper: 0.065,
    power_achieved: 0.83,
    is_significant: true,
    guardrail_breached: false,
    recommendation: "PROMOTE",
  },
  "exp-002": {
    experiment_id: "exp-002",
    n_control: 3_210,
    n_treatment: 1_102,
    approval_rate_control: 0.712,
    approval_rate_treatment: 0.695,
    z_score: -1.23,
    p_value: 0.219,
    ci_lower: -0.044,
    ci_upper: 0.010,
    power_achieved: 0.65,
    is_significant: false,
    guardrail_breached: false,
    recommendation: "HOLD",
  },
};

// ─── Sub-components ────────────────────────────────────────────────────────────

const STATUS_STYLE: Record<string, string> = {
  DRAFT:     "bg-gray-100 text-gray-700",
  RUNNING:   "bg-blue-100 text-blue-700 animate-pulse",
  PAUSED:    "bg-amber-100 text-amber-700",
  COMPLETED: "bg-green-100 text-green-700",
  HALTED:    "bg-red-100 text-red-700",
};

const REC_STYLE: Record<string, string> = {
  PROMOTE:           "bg-green-50 border border-green-300 text-green-800",
  HOLD:              "bg-amber-50 border border-amber-300 text-amber-800",
  REJECT:            "bg-red-50 border border-red-300 text-red-800",
  INSUFFICIENT_DATA: "bg-gray-50 border border-gray-300 text-gray-600",
};

const REC_ICON: Record<string, string> = {
  PROMOTE: "🚀",
  HOLD: "⏸",
  REJECT: "❌",
  INSUFFICIENT_DATA: "🔲",
};

function StatCard({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="bg-white rounded-lg border border-gray-100 shadow-sm p-4">
      <p className="text-xs text-gray-500 mb-1">{label}</p>
      <p className="text-lg font-bold text-gray-900">{value}</p>
      {sub && <p className="text-xs text-gray-400 mt-0.5">{sub}</p>}
    </div>
  );
}

function SignificancePanel({ report }: { report: SignificanceReport }) {
  const delta = report.approval_rate_treatment - report.approval_rate_control;
  const pct = (v: number) => `${(v * 100).toFixed(1)}%`;

  return (
    <div className="space-y-4">
      <div className={`rounded-lg p-4 ${REC_STYLE[report.recommendation]}`}>
        <div className="flex items-center gap-2">
          <span className="text-xl">{REC_ICON[report.recommendation]}</span>
          <div>
            <p className="font-bold text-sm">Recommendation: {report.recommendation}</p>
            <p className="text-xs mt-0.5">
              {report.recommendation === "PROMOTE" && "Challenger significantly outperforms champion — safe to promote."}
              {report.recommendation === "HOLD" && "No significant difference detected yet. Continue collecting data."}
              {report.recommendation === "REJECT" && "Challenger underperforms or guardrail breached. Halt and review."}
              {report.recommendation === "INSUFFICIENT_DATA" && "Sample size too small. Wait for more observations."}
            </p>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <StatCard label="Control Approval Rate"   value={pct(report.approval_rate_control)} sub={`n = ${report.n_control.toLocaleString()}`} />
        <StatCard label="Treatment Approval Rate" value={pct(report.approval_rate_treatment)} sub={`n = ${report.n_treatment.toLocaleString()}`} />
        <StatCard label="Δ Approval Rate"         value={`${delta > 0 ? "+" : ""}${pct(delta)}`} sub={`95% CI [${pct(report.ci_lower)}, ${pct(report.ci_upper)}]`} />
        <StatCard label="Statistical Power"        value={pct(report.power_achieved)} sub={`α = 0.05`} />
      </div>

      <div className="grid grid-cols-3 gap-3">
        <StatCard label="Z-Score"  value={report.z_score.toFixed(3)} />
        <StatCard label="p-value"  value={report.p_value.toFixed(4)} sub={report.is_significant ? "✅ Significant" : "⚠️ Not Significant"} />
        <StatCard label="Guardrail" value={report.guardrail_breached ? "🔴 Breached" : "🟢 OK"} />
      </div>

      {/* Approval rate bar */}
      <div className="bg-white rounded-lg border border-gray-100 p-4">
        <p className="text-xs font-semibold text-gray-500 mb-3">Approval Rate Comparison</p>
        <div className="space-y-3">
          {[
            { label: "Champion (Control)", rate: report.approval_rate_control, color: "bg-blue-500" },
            { label: "Challenger (Treatment)", rate: report.approval_rate_treatment, color: "bg-emerald-500" },
          ].map(({ label, rate, color }) => (
            <div key={label}>
              <div className="flex justify-between text-xs text-gray-600 mb-1">
                <span>{label}</span>
                <span className="font-semibold">{pct(rate)}</span>
              </div>
              <div className="h-3 bg-gray-100 rounded-full overflow-hidden">
                <div className={`h-full ${color} rounded-full`} style={{ width: `${rate * 100}%` }} />
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

// ─── New Experiment Form ────────────────────────────────────────────────────────

function NewExperimentForm({ onClose }: { onClose: () => void }) {
  const [form, setForm] = useState({
    name: "",
    description: "",
    champion: "",
    challenger: "",
    split: "50",
    mde: "2",
    alpha: "5",
  });

  const update = (k: string, v: string) => setForm((p) => ({ ...p, [k]: v }));

  const handleCreate = () => {
    if (!form.name || !form.champion || !form.challenger) return;
    alert(`Experiment "${form.name}" created in DRAFT state.\n\nConnect to POST /v1/experiments to persist.`);
    onClose();
  };

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50">
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-lg p-6 space-y-4">
        <div className="flex items-center justify-between">
          <h3 className="font-bold text-gray-900 text-lg">New A/B Experiment</h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-xl">×</button>
        </div>
        {[
          { label: "Experiment Name *", key: "name", type: "text", placeholder: "e.g. Credit Card PD Threshold v2" },
          { label: "Description", key: "description", type: "text", placeholder: "Brief description of what's being tested" },
          { label: "Champion Policy Version *", key: "champion", type: "text", placeholder: "e.g. cc-v3.1" },
          { label: "Challenger Policy Version *", key: "challenger", type: "text", placeholder: "e.g. cc-v3.2-relaxed" },
          { label: "Traffic Split to Challenger (%)", key: "split", type: "number", placeholder: "50" },
          { label: "Minimum Detectable Effect (%)", key: "mde", type: "number", placeholder: "2" },
          { label: "Significance Level α (%)", key: "alpha", type: "number", placeholder: "5" },
        ].map(({ label, key, type, placeholder }) => (
          <div key={key}>
            <label className="block text-xs font-semibold text-gray-600 mb-1">{label}</label>
            <input
              type={type}
              value={form[key as keyof typeof form]}
              placeholder={placeholder}
              onChange={(e) => update(key, e.target.value)}
              className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>
        ))}
        <div className="flex gap-3 pt-2">
          <button
            onClick={handleCreate}
            className="flex-1 bg-blue-600 hover:bg-blue-700 text-white text-sm font-semibold py-2 rounded-lg transition-colors"
          >
            Create Experiment
          </button>
          <button onClick={onClose} className="flex-1 border border-gray-200 text-gray-600 text-sm py-2 rounded-lg hover:bg-gray-50">
            Cancel
          </button>
        </div>
      </div>
    </div>
  );
}

// ─── Main Page ─────────────────────────────────────────────────────────────────

export default function ABTestingPage() {
  const [dateRange, setDateRange] = useState<"7d" | "30d" | "90d" | "custom">("30d");
  const [experiments] = useState<Experiment[]>(MOCK_EXPERIMENTS);
  const [selected, setSelected] = useState<Experiment | null>(null);
  const [showForm, setShowForm] = useState(false);

  const report = selected ? MOCK_REPORTS[selected.experiment_id] : null;

  return (
    <DashboardShell role="data_scientist" userName="Jordan Kim" dateRange={dateRange} onDateRangeChange={setDateRange}>
      {showForm && <NewExperimentForm onClose={() => setShowForm(false)} />}

      <div className="space-y-6">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-xl font-black text-gray-900">A/B Policy Experiments</h2>
            <p className="text-sm text-gray-500">Statistical champion/challenger testing with guardrails</p>
          </div>
          <button
            onClick={() => setShowForm(true)}
            className="flex items-center gap-2 bg-blue-600 hover:bg-blue-700 text-white text-sm font-semibold px-4 py-2 rounded-lg transition-colors"
          >
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
            </svg>
            New Experiment
          </button>
        </div>

        {/* Summary KPIs */}
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          <StatCard label="Total Experiments"  value={experiments.length.toString()} />
          <StatCard label="Running"            value={experiments.filter((e) => e.status === "RUNNING").length.toString()} />
          <StatCard label="Completed"          value={experiments.filter((e) => e.status === "COMPLETED").length.toString()} />
          <StatCard label="Pending Start"      value={experiments.filter((e) => e.status === "DRAFT").length.toString()} />
        </div>

        {/* Experiment List + Detail */}
        <div className="grid lg:grid-cols-5 gap-6">
          {/* List */}
          <div className="lg:col-span-2 space-y-3">
            <h3 className="text-sm font-semibold text-gray-500 uppercase tracking-wide">Experiments</h3>
            {experiments.map((exp) => (
              <button
                key={exp.experiment_id}
                onClick={() => setSelected(exp)}
                className={`w-full text-left bg-white rounded-xl border shadow-sm p-4 hover:border-blue-300 transition-colors ${
                  selected?.experiment_id === exp.experiment_id ? "border-blue-400 ring-1 ring-blue-200" : "border-gray-100"
                }`}
              >
                <div className="flex items-start justify-between gap-2">
                  <p className="font-semibold text-gray-900 text-sm">{exp.name}</p>
                  <span className={`text-xs font-medium px-2 py-0.5 rounded-full shrink-0 ${STATUS_STYLE[exp.status]}`}>
                    {exp.status}
                  </span>
                </div>
                <p className="text-xs text-gray-500 mt-1 line-clamp-1">{exp.description}</p>
                <div className="flex gap-3 mt-2 text-xs text-gray-400">
                  <span>🏆 {exp.champion_policy_version}</span>
                  <span>⚔️ {exp.challenger_policy_version}</span>
                </div>
                <p className="text-xs text-gray-400 mt-1">
                  Split: {Math.round(exp.traffic_split * 100)}% challenger
                </p>
              </button>
            ))}
          </div>

          {/* Detail / Report */}
          <div className="lg:col-span-3">
            {selected ? (
              <div className="space-y-4">
                <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-5">
                  <div className="flex items-start justify-between">
                    <div>
                      <h3 className="font-bold text-gray-900">{selected.name}</h3>
                      <p className="text-xs text-gray-500 mt-1">{selected.description}</p>
                    </div>
                    <span className={`text-xs font-medium px-3 py-1 rounded-full ${STATUS_STYLE[selected.status]}`}>
                      {selected.status}
                    </span>
                  </div>
                  <div className="grid grid-cols-3 gap-3 mt-4 text-xs text-gray-600">
                    <div><span className="text-gray-400">Champion</span><br /><span className="font-semibold">{selected.champion_policy_version}</span></div>
                    <div><span className="text-gray-400">Challenger</span><br /><span className="font-semibold">{selected.challenger_policy_version}</span></div>
                    <div><span className="text-gray-400">Started</span><br /><span className="font-semibold">{selected.started_at ? new Date(selected.started_at).toLocaleDateString() : "Not started"}</span></div>
                  </div>
                  {selected.status === "DRAFT" && (
                    <button
                      onClick={() => alert(`POST /v1/experiments/${selected.experiment_id}/start`)}
                      className="mt-4 bg-blue-600 hover:bg-blue-700 text-white text-xs font-semibold px-4 py-2 rounded-lg"
                    >
                      Start Experiment
                    </button>
                  )}
                </div>

                {report ? (
                  <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-5">
                    <h3 className="font-bold text-gray-900 mb-4">Statistical Significance Report</h3>
                    <SignificancePanel report={report} />
                    <div className="flex gap-3 mt-4 pt-4 border-t border-gray-100">
                      <button
                        onClick={() => alert(`POST /v1/experiments/${selected.experiment_id}/export-evidence`)}
                        className="text-xs bg-gray-900 hover:bg-gray-800 text-white font-medium px-4 py-2 rounded-lg"
                      >
                        Export Evidence Bundle
                      </button>
                      {report.recommendation === "PROMOTE" && (
                        <button
                          onClick={() => alert(`Promoting challenger ${selected.challenger_policy_version} as new champion.`)}
                          className="text-xs bg-green-600 hover:bg-green-700 text-white font-medium px-4 py-2 rounded-lg"
                        >
                          Promote Challenger →
                        </button>
                      )}
                    </div>
                  </div>
                ) : (
                  <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-5 text-center py-12 text-gray-400 text-sm">
                    {selected.status === "DRAFT"
                      ? "Start the experiment to begin collecting outcome data."
                      : "No significance report available yet — insufficient data."}
                  </div>
                )}
              </div>
            ) : (
              <div className="bg-white rounded-xl border border-gray-100 shadow-sm flex items-center justify-center h-48 text-gray-400 text-sm">
                Select an experiment to see its significance report
              </div>
            )}
          </div>
        </div>
      </div>
    </DashboardShell>
  );
}
