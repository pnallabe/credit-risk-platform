"use client";

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import {
  loanDetailsSchema,
  personalInfoSchema,
  consentSchema,
  CREDIT_SCORE_MAP,
  LOAN_PURPOSE_LABELS,
  EMPLOYMENT_STATUS_LABELS,
  type LoanDetailsFormData,
  type PersonalInfoFormData,
  type ConsentFormData,
} from "@/lib/schemas";
import { apiClient, type LoanApplicationPayload } from "@/lib/api-client";
import { formatCurrency, estimateMonthlyPayment } from "@/lib/utils";

// ─────────────────────────────────────────────────────────────────────────────
// Step progress indicators
// ─────────────────────────────────────────────────────────────────────────────

const STEPS = ["Loan Details", "Your Info", "Review & Submit"];
const SESSION_KEY = "lendsmart_apply_draft";

// ─────────────────────────────────────────────────────────────────────────────
// Main multi-step form page
// ─────────────────────────────────────────────────────────────────────────────

export default function ApplyPage() {
  const router = useRouter();
  const [currentStep, setCurrentStep] = useState(0);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);

  // Persisted form state
  const [loanData, setLoanData] = useState<LoanDetailsFormData>({
    loan_amount: 10000,
    loan_purpose: "personal",
    loan_term_months: 36,
  });
  const [personalData, setPersonalData] = useState<PersonalInfoFormData | null>(null);

  // Restore from sessionStorage
  useEffect(() => {
    try {
      const saved = sessionStorage.getItem(SESSION_KEY);
      if (saved) {
        const parsed = JSON.parse(saved);
        if (parsed.loanData) setLoanData(parsed.loanData);
        if (parsed.personalData) setPersonalData(parsed.personalData);
        if (parsed.currentStep) setCurrentStep(Math.min(parsed.currentStep, 2));
      }
    } catch {}
  }, []);

  // Persist to sessionStorage on change
  useEffect(() => {
    try {
      sessionStorage.setItem(
        SESSION_KEY,
        JSON.stringify({ loanData, personalData, currentStep })
      );
    } catch {}
  }, [loanData, personalData, currentStep]);

  // ── Submit handler ──

  const handleSubmit = async (consented: boolean) => {
    if (!personalData) return;
    setIsSubmitting(true);
    setSubmitError(null);

    const applicationId = `app-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
    const creditScore = CREDIT_SCORE_MAP[personalData.credit_score_range];
    const dti =
      personalData.annual_income > 0
        ? Math.min(personalData.existing_debt_amount / personalData.annual_income, 0.65)
        : 0;

    const payload: LoanApplicationPayload = {
      application_id: applicationId,
      customer_id: `cust-${Date.now()}`,
      credit_score: creditScore,
      annual_income: personalData.annual_income,
      employment_status: personalData.employment_status,
      employer_tenure_months: personalData.employer_tenure_months ?? 0,
      debt_to_income_ratio: parseFloat(dti.toFixed(4)),
      existing_debt_amount: personalData.existing_debt_amount,
      loan_amount: loanData.loan_amount,
      loan_purpose: loanData.loan_purpose,
      loan_term_months: loanData.loan_term_months,
      num_open_accounts: personalData.num_open_accounts,
      num_derogatory_marks: personalData.num_derogatory_marks,
      months_since_last_delinquency: personalData.months_since_last_delinquency ?? null,
    };

    const result = await apiClient.submitDecision(payload);

    if (!result.ok) {
      setSubmitError(
        `Submission failed (${result.error.status}): ${result.error.message}. Please try again.`
      );
      setIsSubmitting(false);
      return;
    }

    // Clear session storage on success
    try {
      sessionStorage.removeItem(SESSION_KEY);
    } catch {}

    // Store result for decision page
    try {
      sessionStorage.setItem("lendsmart_decision", JSON.stringify(result.data));
    } catch {}

    router.push(`/decision?id=${applicationId}`);
  };

  return (
    <div className="min-h-screen bg-gray-50 py-10 px-4">
      <div className="container mx-auto max-w-2xl">
        {/* Header */}
        <div className="text-center mb-8">
          <h1 className="text-3xl font-bold text-gray-900">Apply for a Loan</h1>
          <p className="text-gray-600 mt-2">Fill in your details to get an instant decision</p>
        </div>

        {/* Step progress */}
        <StepIndicator currentStep={currentStep} steps={STEPS} />

        {/* Form card */}
        <div className="bg-white rounded-2xl shadow-sm border border-gray-100 p-8 mt-6">
          {currentStep === 0 && (
            <Step1LoanDetails
              defaultValues={loanData}
              onNext={(data) => {
                setLoanData(data);
                setCurrentStep(1);
              }}
            />
          )}
          {currentStep === 1 && (
            <Step2PersonalInfo
              defaultValues={personalData ?? undefined}
              onBack={() => setCurrentStep(0)}
              onNext={(data) => {
                setPersonalData(data);
                setCurrentStep(2);
              }}
            />
          )}
          {currentStep === 2 && personalData && (
            <Step3Review
              loanData={loanData}
              personalData={personalData}
              isSubmitting={isSubmitting}
              submitError={submitError}
              onBack={() => setCurrentStep(1)}
              onSubmit={handleSubmit}
            />
          )}
        </div>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Step Indicator
// ─────────────────────────────────────────────────────────────────────────────

function StepIndicator({ currentStep, steps }: { currentStep: number; steps: string[] }) {
  return (
    <div className="flex items-center justify-center gap-0">
      {steps.map((step, i) => (
        <div key={step} className="flex items-center">
          <div className="flex flex-col items-center">
            <div
              className={`w-9 h-9 rounded-full flex items-center justify-center text-sm font-bold transition-colors ${
                i < currentStep
                  ? "bg-green-500 text-white"
                  : i === currentStep
                  ? "bg-blue-600 text-white"
                  : "bg-gray-200 text-gray-500"
              }`}
            >
              {i < currentStep ? "✓" : i + 1}
            </div>
            <span
              className={`text-xs mt-1.5 font-medium hidden sm:block ${
                i === currentStep ? "text-blue-600" : "text-gray-400"
              }`}
            >
              {step}
            </span>
          </div>
          {i < steps.length - 1 && (
            <div
              className={`w-16 h-0.5 mx-1 mb-5 transition-colors ${
                i < currentStep ? "bg-green-500" : "bg-gray-200"
              }`}
            />
          )}
        </div>
      ))}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Step 1 — Loan Details
// ─────────────────────────────────────────────────────────────────────────────

function Step1LoanDetails({
  defaultValues,
  onNext,
}: {
  defaultValues: LoanDetailsFormData;
  onNext: (data: LoanDetailsFormData) => void;
}) {
  const {
    register,
    handleSubmit,
    watch,
    setValue,
    formState: { errors },
  } = useForm<LoanDetailsFormData>({
    resolver: zodResolver(loanDetailsSchema),
    defaultValues,
  });

  const loanAmount = watch("loan_amount");
  const termMonths = watch("loan_term_months");
  const estimatedRate = 12.5; // display estimate before real decision
  const monthly = estimateMonthlyPayment(loanAmount || 0, estimatedRate, termMonths || 36);

  return (
    <form onSubmit={handleSubmit(onNext)} className="space-y-6">
      <h2 className="text-xl font-bold text-gray-900 mb-1">Loan Details</h2>
      <p className="text-gray-600 text-sm mb-6">Tell us what you need the loan for.</p>

      {/* Loan amount slider */}
      <div>
        <label htmlFor="loan_amount" className="block text-sm font-medium text-gray-700 mb-2">
          Loan Amount
        </label>
        <div className="flex items-center gap-4 mb-2">
          <span className="text-2xl font-bold text-blue-600">
            {formatCurrency(loanAmount || 0)}
          </span>
          <span className="text-sm text-gray-400">
            ≈ {formatCurrency(monthly)}/mo*
          </span>
        </div>
        <input
          id="loan_amount"
          type="range"
          min={1000}
          max={100000}
          step={500}
          className="w-full h-2 bg-blue-200 rounded-full appearance-none cursor-pointer accent-blue-600"
          {...register("loan_amount", { valueAsNumber: true })}
        />
        <div className="flex justify-between text-xs text-gray-400 mt-1">
          <span>$1,000</span>
          <span>$100,000</span>
        </div>
        {errors.loan_amount && (
          <p className="text-red-500 text-xs mt-1">{errors.loan_amount.message}</p>
        )}
        <p className="text-xs text-gray-400 mt-2">*Estimated at {estimatedRate}% APR. Actual rate determined after decision.</p>
      </div>

      {/* Loan purpose */}
      <div>
        <label htmlFor="loan_purpose" className="block text-sm font-medium text-gray-700 mb-2">
          Loan Purpose
        </label>
        <select
          id="loan_purpose"
          className="w-full border border-gray-300 rounded-lg px-3 py-2.5 text-gray-900 bg-white focus:outline-none focus:ring-2 focus:ring-blue-500"
          {...register("loan_purpose")}
        >
          {Object.entries(LOAN_PURPOSE_LABELS).map(([val, label]) => (
            <option key={val} value={val}>
              {label}
            </option>
          ))}
        </select>
        {errors.loan_purpose && (
          <p className="text-red-500 text-xs mt-1">{errors.loan_purpose.message}</p>
        )}
      </div>

      {/* Loan term */}
      <div>
        <label className="block text-sm font-medium text-gray-700 mb-3">
          Loan Term
        </label>
        <div className="grid grid-cols-5 gap-2">
          {([12, 24, 36, 48, 60] as const).map((m) => (
            <button
              key={m}
              type="button"
              onClick={() => setValue("loan_term_months", m)}
              className={`border-2 rounded-lg py-2.5 text-sm font-medium transition-colors ${
                termMonths === m
                  ? "border-blue-600 bg-blue-50 text-blue-700"
                  : "border-gray-200 text-gray-600 hover:border-gray-300"
              }`}
            >
              {m} mo
            </button>
          ))}
        </div>
        {errors.loan_term_months && (
          <p className="text-red-500 text-xs mt-1">{errors.loan_term_months.message}</p>
        )}
      </div>

      <div className="pt-4">
        <button
          type="submit"
          className="w-full bg-blue-600 hover:bg-blue-700 text-white font-bold py-3 rounded-xl transition-colors"
        >
          Continue →
        </button>
      </div>
    </form>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Step 2 — Personal & Financial Info
// ─────────────────────────────────────────────────────────────────────────────

function Step2PersonalInfo({
  defaultValues,
  onBack,
  onNext,
}: {
  defaultValues?: PersonalInfoFormData;
  onBack: () => void;
  onNext: (data: PersonalInfoFormData) => void;
}) {
  const {
    register,
    handleSubmit,
    watch,
    formState: { errors },
  } = useForm<PersonalInfoFormData>({
    resolver: zodResolver(personalInfoSchema),
    defaultValues: defaultValues ?? {
      annual_income: 0,
      employment_status: "employed",
      employer_tenure_months: 12,
      credit_score_range: "good",
      existing_debt_amount: 0,
      num_open_accounts: 3,
      num_derogatory_marks: 0,
      months_since_last_delinquency: null,
    },
  });

  const employmentStatus = watch("employment_status");
  const annualIncome = watch("annual_income") || 0;
  const existingDebt = watch("existing_debt_amount") || 0;
  const dti = annualIncome > 0 ? Math.min(existingDebt / annualIncome, 0.65) : 0;

  return (
    <form onSubmit={handleSubmit(onNext)} className="space-y-5">
      <h2 className="text-xl font-bold text-gray-900 mb-1">Personal & Financial Info</h2>
      <p className="text-gray-600 text-sm mb-6">Your information is encrypted and never sold.</p>

      <FormField label="Annual Income" htmlFor="annual_income" error={errors.annual_income?.message}>
        <div className="relative">
          <span className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-500">$</span>
          <input
            id="annual_income"
            type="number"
            min={1}
            className="w-full border border-gray-300 rounded-lg pl-7 pr-3 py-2.5 focus:outline-none focus:ring-2 focus:ring-blue-500"
            placeholder="75,000"
            {...register("annual_income", { valueAsNumber: true })}
          />
        </div>
      </FormField>

      <FormField label="Employment Status" htmlFor="employment_status" error={errors.employment_status?.message}>
        <select
          id="employment_status"
          className="w-full border border-gray-300 rounded-lg px-3 py-2.5 bg-white focus:outline-none focus:ring-2 focus:ring-blue-500"
          {...register("employment_status")}
        >
          {Object.entries(EMPLOYMENT_STATUS_LABELS).map(([val, label]) => (
            <option key={val} value={val}>
              {label}
            </option>
          ))}
        </select>
      </FormField>

      {["employed", "self-employed"].includes(employmentStatus) && (
        <FormField label="Months with Current Employer" htmlFor="employer_tenure_months" error={errors.employer_tenure_months?.message}>
          <input
            id="employer_tenure_months"
            type="number"
            min={0}
            className="w-full border border-gray-300 rounded-lg px-3 py-2.5 focus:outline-none focus:ring-2 focus:ring-blue-500"
            placeholder="24"
            {...register("employer_tenure_months", { valueAsNumber: true })}
          />
        </FormField>
      )}

      <FormField label="Credit Score Range" htmlFor="credit_score_range" error={errors.credit_score_range?.message}>
        <select
          id="credit_score_range"
          className="w-full border border-gray-300 rounded-lg px-3 py-2.5 bg-white focus:outline-none focus:ring-2 focus:ring-blue-500"
          {...register("credit_score_range")}
        >
          <option value="excellent">Excellent (750+)</option>
          <option value="good">Good (700–749)</option>
          <option value="fair">Fair (650–699)</option>
          <option value="poor">Poor (&lt;650)</option>
        </select>
      </FormField>

      <FormField label="Existing Debt Amount" htmlFor="existing_debt_amount" error={errors.existing_debt_amount?.message}>
        <div className="relative">
          <span className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-500">$</span>
          <input
            id="existing_debt_amount"
            type="number"
            min={0}
            className="w-full border border-gray-300 rounded-lg pl-7 pr-3 py-2.5 focus:outline-none focus:ring-2 focus:ring-blue-500"
            placeholder="0"
            {...register("existing_debt_amount", { valueAsNumber: true })}
          />
        </div>
      </FormField>

      {/* Auto-calculated DTI */}
      <div className="bg-blue-50 border border-blue-100 rounded-lg px-4 py-3 text-sm text-blue-800">
        Estimated Debt-to-Income Ratio:{" "}
        <strong>{(dti * 100).toFixed(1)}%</strong>{" "}
        {dti > 0.43 && (
          <span className="text-orange-600 font-medium">(High — may affect approval)</span>
        )}
      </div>

      <div className="grid grid-cols-2 gap-4">
        <FormField label="Open Accounts" htmlFor="num_open_accounts" error={errors.num_open_accounts?.message}>
          <input
            id="num_open_accounts"
            type="number"
            min={0}
            max={100}
            className="w-full border border-gray-300 rounded-lg px-3 py-2.5 focus:outline-none focus:ring-2 focus:ring-blue-500"
            {...register("num_open_accounts", { valueAsNumber: true })}
          />
        </FormField>
        <FormField label="Derogatory Marks" htmlFor="num_derogatory_marks" error={errors.num_derogatory_marks?.message}>
          <input
            id="num_derogatory_marks"
            type="number"
            min={0}
            max={20}
            className="w-full border border-gray-300 rounded-lg px-3 py-2.5 focus:outline-none focus:ring-2 focus:ring-blue-500"
            {...register("num_derogatory_marks", { valueAsNumber: true })}
          />
        </FormField>
      </div>

      <div className="flex gap-3 pt-4">
        <button
          type="button"
          onClick={onBack}
          className="flex-1 border border-gray-300 text-gray-700 font-semibold py-3 rounded-xl hover:bg-gray-50 transition-colors"
        >
          ← Back
        </button>
        <button
          type="submit"
          className="flex-2 flex-grow bg-blue-600 hover:bg-blue-700 text-white font-bold py-3 rounded-xl transition-colors"
        >
          Continue →
        </button>
      </div>
    </form>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Step 3 — Review & Submit
// ─────────────────────────────────────────────────────────────────────────────

function Step3Review({
  loanData,
  personalData,
  isSubmitting,
  submitError,
  onBack,
  onSubmit,
}: {
  loanData: LoanDetailsFormData;
  personalData: PersonalInfoFormData;
  isSubmitting: boolean;
  submitError: string | null;
  onBack: () => void;
  onSubmit: (consented: boolean) => void;
}) {
  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<ConsentFormData>({
    resolver: zodResolver(consentSchema),
    defaultValues: { consent_credit_check: false },
  });

  return (
    <form onSubmit={handleSubmit(() => onSubmit(true))} className="space-y-6">
      <h2 className="text-xl font-bold text-gray-900 mb-1">Review Your Application</h2>
      <p className="text-gray-600 text-sm mb-4">Please confirm everything looks correct.</p>

      {/* Summary card */}
      <div className="border border-gray-200 rounded-xl divide-y">
        <SummaryRow label="Loan Amount" value={formatCurrency(loanData.loan_amount)} />
        <SummaryRow label="Loan Purpose" value={LOAN_PURPOSE_LABELS[loanData.loan_purpose]} />
        <SummaryRow label="Loan Term" value={`${loanData.loan_term_months} months`} />
        <SummaryRow
          label="Annual Income"
          value={formatCurrency(personalData.annual_income)}
        />
        <SummaryRow
          label="Employment Status"
          value={EMPLOYMENT_STATUS_LABELS[personalData.employment_status]}
        />
        <SummaryRow
          label="Credit Score Range"
          value={
            {
              excellent: "Excellent (750+)",
              good: "Good (700–749)",
              fair: "Fair (650–699)",
              poor: "Poor (<650)",
            }[personalData.credit_score_range]
          }
        />
        <SummaryRow
          label="Existing Debt"
          value={formatCurrency(personalData.existing_debt_amount)}
        />
      </div>

      {/* Consent checkbox */}
      <div className="flex items-start gap-3 bg-amber-50 border border-amber-200 rounded-xl p-4">
        <input
          id="consent"
          type="checkbox"
          className="mt-0.5 w-4 h-4 accent-blue-600"
          {...register("consent_credit_check")}
        />
        <label htmlFor="consent" className="text-sm text-gray-700 leading-relaxed cursor-pointer">
          I authorize LendSmart to obtain my credit report and verify my financial information for
          the purpose of evaluating this loan application. I understand this may result in a hard
          credit inquiry.
        </label>
      </div>
      {errors.consent_credit_check && (
        <p className="text-red-500 text-sm">{errors.consent_credit_check.message}</p>
      )}

      {submitError && (
        <div className="bg-red-50 border border-red-200 text-red-700 rounded-xl p-4 text-sm">
          {submitError}
        </div>
      )}

      <div className="flex gap-3 pt-2">
        <button
          type="button"
          onClick={onBack}
          disabled={isSubmitting}
          className="flex-1 border border-gray-300 text-gray-700 font-semibold py-3 rounded-xl hover:bg-gray-50 transition-colors disabled:opacity-50"
        >
          ← Back
        </button>
        <button
          type="submit"
          disabled={isSubmitting}
          className="flex-2 flex-grow bg-blue-600 hover:bg-blue-700 text-white font-bold py-3 rounded-xl transition-colors disabled:opacity-70 flex items-center justify-center gap-2"
        >
          {isSubmitting ? (
            <>
              <svg className="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
                <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" className="opacity-25" />
                <path
                  fill="currentColor"
                  d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"
                  className="opacity-75"
                />
              </svg>
              Submitting…
            </>
          ) : (
            "Submit Application →"
          )}
        </button>
      </div>
    </form>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Small helper components
// ─────────────────────────────────────────────────────────────────────────────

function FormField({
  label,
  htmlFor,
  error,
  children,
}: {
  label: string;
  htmlFor?: string;
  error?: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <label htmlFor={htmlFor} className="block text-sm font-medium text-gray-700 mb-1.5">{label}</label>
      {children}
      {error && <p className="text-red-500 text-xs mt-1">{error}</p>}
    </div>
  );
}

function SummaryRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between items-center px-4 py-3">
      <span className="text-sm text-gray-600">{label}</span>
      <span className="text-sm font-semibold text-gray-900">{value}</span>
    </div>
  );
}
