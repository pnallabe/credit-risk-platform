/**
 * Zod validation schemas for the loan application multi-step form.
 */
import { z } from "zod";

// ─────────────────────────────────────────────────────────────────────────────
// Step 1 — Loan Details
// ─────────────────────────────────────────────────────────────────────────────

export const loanDetailsSchema = z.object({
  loan_amount: z
    .number({ required_error: "Loan amount is required" })
    .min(1000, "Minimum loan amount is $1,000")
    .max(100000, "Maximum loan amount is $100,000"),
  loan_purpose: z.enum(
    ["personal", "auto", "home_improvement", "medical", "education", "debt_consolidation"],
    { required_error: "Please select a loan purpose" }
  ),
  loan_term_months: z.union([
    z.literal(12),
    z.literal(24),
    z.literal(36),
    z.literal(48),
    z.literal(60),
  ]),
});

export type LoanDetailsFormData = z.infer<typeof loanDetailsSchema>;

// ─────────────────────────────────────────────────────────────────────────────
// Step 2 — Personal & Financial Info
// ─────────────────────────────────────────────────────────────────────────────

const _personalInfoBase = z.object({
    annual_income: z
      .number({ required_error: "Annual income is required" })
      .min(1, "Annual income must be greater than zero"),
    employment_status: z.enum(["employed", "self-employed", "unemployed", "retired"], {
      required_error: "Please select your employment status",
    }),
    employer_tenure_months: z.number().min(0).optional().default(0),
    credit_score_range: z.enum(["excellent", "good", "fair", "poor"], {
      required_error: "Please select your credit score range",
    }),
    existing_debt_amount: z
      .number({ required_error: "Please enter your existing debt" })
      .min(0, "Existing debt cannot be negative"),
    num_open_accounts: z.number().min(0).max(100).default(3),
    num_derogatory_marks: z.number().min(0).max(20).default(0),
    months_since_last_delinquency: z.number().min(0).nullable().optional(),
  });

export const personalInfoSchema = _personalInfoBase.superRefine((data, ctx) => {
    if (
      ["employed", "self-employed"].includes(data.employment_status) &&
      (data.employer_tenure_months === undefined || data.employer_tenure_months === null)
    ) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        message: "Employer tenure is required for employed/self-employed status",
        path: ["employer_tenure_months"],
      });
    }
  });

export type PersonalInfoFormData = z.infer<typeof personalInfoSchema>;

// ─────────────────────────────────────────────────────────────────────────────
// Step 3 — Consent
// ─────────────────────────────────────────────────────────────────────────────

export const consentSchema = z.object({
  consent_credit_check: z.boolean().refine((v) => v === true, {
    message: "You must consent to a credit check to proceed",
  }),
});

export type ConsentFormData = z.infer<typeof consentSchema>;

// ─────────────────────────────────────────────────────────────────────────────
// Combined full form schema
// ─────────────────────────────────────────────────────────────────────────────

export const fullApplicationSchema = loanDetailsSchema
  .merge(_personalInfoBase)
  .merge(consentSchema);

export type FullApplicationFormData = z.infer<typeof fullApplicationSchema>;

// ─────────────────────────────────────────────────────────────────────────────
// Credit score range → numeric midpoint
// ─────────────────────────────────────────────────────────────────────────────

export const CREDIT_SCORE_MAP: Record<string, number> = {
  excellent: 800,
  good: 725,
  fair: 675,
  poor: 600,
};

export const LOAN_PURPOSE_LABELS: Record<string, string> = {
  personal: "Personal",
  auto: "Auto",
  home_improvement: "Home Improvement",
  medical: "Medical",
  education: "Education",
  debt_consolidation: "Debt Consolidation",
};

export const EMPLOYMENT_STATUS_LABELS: Record<string, string> = {
  employed: "Employed (Full-time / Part-time)",
  "self-employed": "Self-Employed",
  unemployed: "Unemployed",
  retired: "Retired",
};
