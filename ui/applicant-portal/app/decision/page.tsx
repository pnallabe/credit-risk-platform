"use client";

export const dynamic = "force-dynamic";

import { Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import Link from "next/link";
import { type DecisionResponse } from "@/lib/api-client";
import { formatCurrency, estimateMonthlyPayment } from "@/lib/utils";

// ─────────────────────────────────────────────────────────────────────────────
// FCRA-compliant reason code translations
// ─────────────────────────────────────────────────────────────────────────────

const REASON_CODE_TEXT: Record<string, string> = {
  AA01: "High probability of default based on your credit profile",
  AA02: "Fraud indicators detected in your application",
  AA03: "Insufficient credit history to make a lending decision",
  AA04: "Debt-to-income ratio exceeds our lending guidelines",
  AA05: "Your application requires manual review by our team",
};

export default function DecisionPage() {
  return (
    <Suspense
      fallback={
        <div className="min-h-screen flex items-center justify-center">
          <div className="text-center text-gray-500">
            <svg className="w-8 h-8 animate-spin mx-auto mb-3" fill="none" viewBox="0 0 24 24">
              <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" className="opacity-25" />
              <path fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" className="opacity-75" />
            </svg>
            Loading your decision…
          </div>
        </div>
      }
    >
      <DecisionContent />
    </Suspense>
  );
}

function DecisionContent() {
  const searchParams = useSearchParams();
  const applicationId = searchParams.get("id") ?? "";
  const [decision, setDecision] = useState<DecisionResponse | null>(null);
  const [loadTimedOut, setLoadTimedOut] = useState(false);

  useEffect(() => {
    // Try to load the fresh decision result from sessionStorage
    try {
      const raw = sessionStorage.getItem("lendsmart_decision");
      if (raw) {
        const data: DecisionResponse = JSON.parse(raw);
        setDecision(data);
        return;
      }
    } catch {}
    // If no session data, give 2 seconds then show recovery state
    const timer = setTimeout(() => setLoadTimedOut(true), 2000);
    return () => clearTimeout(timer);
  }, []);

  if (!decision && loadTimedOut) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50 px-4">
        <div className="max-w-md w-full bg-white rounded-2xl border border-gray-100 shadow-sm p-8 text-center">
          <div className="w-12 h-12 bg-amber-50 rounded-full flex items-center justify-center mx-auto mb-4">
            <svg className="w-6 h-6 text-amber-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
            </svg>
          </div>
          <h2 className="text-lg font-bold text-gray-900 mb-2">We couldn&apos;t load your decision</h2>
          <p className="text-sm text-gray-500 mb-6">
            Check your email for your decision, or contact our support team for help.
          </p>
          <div className="flex flex-col gap-3">
            <Link
              href="/apply"
              className="inline-flex justify-center items-center bg-[#0f172a] hover:bg-[#1e3a5f] text-white font-semibold py-3 px-6 rounded-lg text-sm transition-colors"
            >
              Start a new application
            </Link>
            <a
              href="mailto:support@lendsmart.com"
              className="text-sm text-[#374151] hover:text-[#0f172a] underline"
            >
              Contact support
            </a>
          </div>
        </div>
      </div>
    );
  }

  if (!decision) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="text-center text-gray-500">
          <svg className="w-8 h-8 animate-spin mx-auto mb-3" fill="none" viewBox="0 0 24 24">
            <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" className="opacity-25" />
            <path fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" className="opacity-75" />
          </svg>
          Loading your decision…
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-50 py-12 px-4">
      <div className="container mx-auto max-w-xl">
        {decision.decision === "APPROVE" && <ApproveView decision={decision} />}
        {decision.decision === "REJECT" && <RejectView decision={decision} />}
        {decision.decision === "MANUAL_REVIEW" && <ManualReviewView decision={decision} />}

        {/* SHAP Explanation factors */}
        {decision.explanation && decision.explanation.length > 0 && (
          <div className="mt-6 bg-white rounded-2xl border border-gray-100 shadow-sm p-6">
            <h3 className="font-bold text-gray-900 mb-4">Top Factors in Your Decision</h3>
            <div className="space-y-3">
              {decision.explanation.map((f, i) => (
                <div key={i} className="flex items-center gap-3">
                  <span
                    className={`w-7 h-7 rounded-full flex items-center justify-center text-sm flex-shrink-0 ${
                      f.direction === "positive"
                        ? "bg-green-100 text-green-700"
                        : "bg-red-100 text-red-700"
                    }`}
                  >
                    {f.direction === "positive" ? "+" : "−"}
                  </span>
                  <div className="flex-1 min-w-0">
                    <div className="text-sm font-medium text-gray-800 capitalize">
                      {f.feature.replace(/_/g, " ")}
                    </div>
                    <div className="text-xs text-gray-500">
                      Impact: {f.shap_value > 0 ? "+" : ""}{f.shap_value.toFixed(3)}
                    </div>
                  </div>
                  <div
                    className={`text-xs font-semibold px-2 py-0.5 rounded-full ${
                      f.direction === "positive"
                        ? "bg-green-100 text-green-700"
                        : "bg-red-100 text-red-700"
                    }`}
                  >
                    {f.direction === "positive" ? "Helps" : "Hurts"}
                  </div>
                </div>
              ))}
            </div>
            <p className="text-xs text-gray-400 mt-4">
              These factors are calculated using AI model explanations (SHAP values) as required by
              fair lending regulations.
            </p>
          </div>
        )}

        {/* Application reference */}
        <div className="mt-4 text-center text-xs text-gray-400">
          Application ID: <span className="font-mono">{applicationId || decision.application_id}</span>
          {" · "}
          <Link href={`/status/${applicationId || decision.application_id}`} className="underline hover:text-gray-600">
            Track status →
          </Link>
        </div>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Approve View
// ─────────────────────────────────────────────────────────────────────────────

function ApproveView({ decision }: { decision: DecisionResponse }) {
  const loanTerms = decision.loan_terms as {
    loan_amount?: number;
    loan_term_months?: number;
  };
  const amount = loanTerms.loan_amount ?? 0;
  const term = loanTerms.loan_term_months ?? 36;
  const rate = decision.recommended_rate ?? 0;
  const monthly = estimateMonthlyPayment(amount, rate, term);

  return (
    <div className="bg-white rounded-2xl border-2 border-green-400 shadow-sm overflow-hidden">
      <div className="bg-green-500 text-white px-6 py-8 text-center">
        <div className="w-16 h-16 bg-white/20 rounded-full flex items-center justify-center mx-auto mb-4">
          <svg className="w-9 h-9" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
          </svg>
        </div>
        <h1 className="text-3xl font-extrabold">Congratulations!</h1>
        <p className="text-green-100 mt-2 text-lg">Your loan has been approved</p>
      </div>
      <div className="p-6 space-y-4">
        <div className="grid grid-cols-3 gap-4 text-center">
          <MetricBox label="Loan Amount" value={formatCurrency(amount)} />
          <MetricBox label="Interest Rate" value={`${rate.toFixed(2)}%`} />
          <MetricBox label="Monthly Payment" value={formatCurrency(monthly)} />
        </div>
        <div className="bg-gray-50 rounded-xl p-4">
          <div className="flex justify-between text-sm mb-1">
            <span className="text-gray-500">Term</span>
            <span className="font-semibold">{term} months</span>
          </div>
          <div className="flex justify-between text-sm mb-1">
            <span className="text-gray-500">Decision Latency</span>
            <span className="font-semibold">{decision.decision_latency_ms}ms</span>
          </div>
          <div className="flex justify-between text-sm">
            <span className="text-gray-500">Audit Reference</span>
            <span className="font-mono text-xs text-gray-600 truncate ml-2">{decision.audit_log_id}</span>
          </div>
        </div>
        <h3 className="font-bold text-gray-900 mt-2">Next Steps</h3>
        <ol className="space-y-2 text-sm text-gray-600 list-decimal list-inside">
          <li>Review and sign your loan agreement (sent to your email)</li>
          <li>Verify your identity with a government-issued ID</li>
          <li>Connect your bank account for disbursement</li>
          <li>Funds typically arrive within 1–2 business days after verification</li>
        </ol>
        <button className="w-full mt-2 bg-green-600 hover:bg-green-700 text-white font-bold py-3 rounded-xl transition-colors">
          Continue to Loan Agreement →
        </button>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Reject View
// ─────────────────────────────────────────────────────────────────────────────

function RejectView({ decision }: { decision: DecisionResponse }) {
  return (
    <div className="bg-white rounded-2xl border-2 border-red-300 shadow-sm overflow-hidden">
      <div className="bg-red-500 text-white px-6 py-8 text-center">
        <div className="w-16 h-16 bg-white/20 rounded-full flex items-center justify-center mx-auto mb-4">
          <svg className="w-9 h-9" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
          </svg>
        </div>
        <h1 className="text-3xl font-extrabold">Application Declined</h1>
        <p className="text-red-100 mt-2">We&apos;re unable to offer you a loan at this time</p>
      </div>
      <div className="p-6 space-y-4">
        <p className="text-gray-600 text-sm">
          As required by the Equal Credit Opportunity Act (ECOA) and the Fair Credit Reporting Act
          (FCRA), we are providing the specific reasons for this decision:
        </p>
        <div className="space-y-2">
          {(decision.reason_codes ?? []).map((code) => (
            <div key={code} className="flex items-start gap-2 bg-red-50 rounded-lg px-4 py-3">
              <span className="text-red-600 font-bold text-sm flex-shrink-0">{code}</span>
              <span className="text-sm text-gray-700">
                {REASON_CODE_TEXT[code] ?? `Decision factor code: ${code}`}
              </span>
            </div>
          ))}
        </div>
        <div className="bg-amber-50 border border-amber-200 rounded-xl p-4">
          <p className="text-sm font-semibold text-amber-800 mb-1">Your Rights</p>
          <p className="text-sm text-amber-700">
            You have the right to request a free copy of your credit report within 60 days. You
            also have the right to dispute inaccurate information. Contact:{" "}
            <a href="mailto:disputes@lendsmart.example.com" className="underline">
              disputes@lendsmart.example.com
            </a>
          </p>
        </div>
        <Link
          href="/apply"
          className="block w-full text-center bg-gray-100 hover:bg-gray-200 text-gray-800 font-semibold py-3 rounded-xl transition-colors"
        >
          Review & Reapply
        </Link>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Manual Review View
// ─────────────────────────────────────────────────────────────────────────────

function ManualReviewView({ decision }: { decision: DecisionResponse }) {
  return (
    <div className="bg-white rounded-2xl border-2 border-amber-400 shadow-sm overflow-hidden">
      <div className="bg-amber-500 text-white px-6 py-8 text-center">
        <div className="w-16 h-16 bg-white/20 rounded-full flex items-center justify-center mx-auto mb-4">
          <svg className="w-9 h-9" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
        </div>
        <h1 className="text-3xl font-extrabold">Under Review</h1>
        <p className="text-amber-100 mt-2">Your application is being reviewed by our team</p>
      </div>
      <div className="p-6 space-y-4">
        <p className="text-gray-600 text-sm">
          Your application has been flagged for manual review by our underwriting team. This is not
          a denial — we simply need a little more time to evaluate your application.
        </p>
        <div className="bg-amber-50 border border-amber-200 rounded-xl p-4 space-y-2">
          <p className="text-sm font-semibold text-amber-800">Expected Timeline</p>
          <p className="text-sm text-amber-700">
            Our underwriting team typically reviews applications within{" "}
            <strong>1–2 business days</strong>. You will receive an email notification once a
            decision has been made.
          </p>
        </div>
        <p className="text-sm text-gray-500">
          Application ID:{" "}
          <span className="font-mono text-gray-700">{decision.application_id}</span>
        </p>
        <Link
          href={`/status/${decision.application_id}`}
          className="block w-full text-center bg-amber-500 hover:bg-amber-600 text-white font-bold py-3 rounded-xl transition-colors"
        >
          Track Application Status →
        </Link>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Metric box helper
// ─────────────────────────────────────────────────────────────────────────────

function MetricBox({ label, value }: { label: string; value: string }) {
  return (
    <div className="bg-green-50 rounded-xl p-3">
      <p className="text-xs text-green-700 mb-1">{label}</p>
      <p className="text-lg font-black text-green-800">{value}</p>
    </div>
  );
}
