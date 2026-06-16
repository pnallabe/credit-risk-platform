import { describe, it, expect } from "vitest";
import {
  loanDetailsSchema,
  personalInfoSchema,
  consentSchema,
  CREDIT_SCORE_MAP,
} from "@/lib/schemas";

// ─────────────────────────────────────────────────────────────────────────────
// Loan Details Schema
// ─────────────────────────────────────────────────────────────────────────────

describe("loanDetailsSchema", () => {
  it("accepts valid loan details", () => {
    const result = loanDetailsSchema.safeParse({
      loan_amount: 15000,
      loan_purpose: "personal",
      loan_term_months: 36,
    });
    expect(result.success).toBe(true);
  });

  it("rejects loan_amount below minimum", () => {
    const result = loanDetailsSchema.safeParse({
      loan_amount: 500,
      loan_purpose: "personal",
      loan_term_months: 36,
    });
    expect(result.success).toBe(false);
    if (!result.success) {
      expect(result.error.issues[0].path).toContain("loan_amount");
    }
  });

  it("rejects loan_amount above maximum", () => {
    const result = loanDetailsSchema.safeParse({
      loan_amount: 200000,
      loan_purpose: "auto",
      loan_term_months: 60,
    });
    expect(result.success).toBe(false);
  });

  it("rejects invalid loan_purpose", () => {
    const result = loanDetailsSchema.safeParse({
      loan_amount: 10000,
      loan_purpose: "gambling",
      loan_term_months: 36,
    });
    expect(result.success).toBe(false);
  });

  it("accepts all valid loan purposes", () => {
    const purposes = [
      "personal",
      "auto",
      "home_improvement",
      "medical",
      "education",
      "debt_consolidation",
    ] as const;
    for (const purpose of purposes) {
      const result = loanDetailsSchema.safeParse({
        loan_amount: 10000,
        loan_purpose: purpose,
        loan_term_months: 36,
      });
      expect(result.success).toBe(true);
    }
  });

  it("only accepts valid loan term months", () => {
    for (const term of [12, 24, 36, 48, 60]) {
      expect(
        loanDetailsSchema.safeParse({
          loan_amount: 10000,
          loan_purpose: "personal",
          loan_term_months: term,
        }).success
      ).toBe(true);
    }
    expect(
      loanDetailsSchema.safeParse({
        loan_amount: 10000,
        loan_purpose: "personal",
        loan_term_months: 18,
      }).success
    ).toBe(false);
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// Personal Info Schema
// ─────────────────────────────────────────────────────────────────────────────

describe("personalInfoSchema", () => {
  const validBase = {
    annual_income: 80000,
    employment_status: "employed" as const,
    employer_tenure_months: 24,
    credit_score_range: "good" as const,
    existing_debt_amount: 5000,
    num_open_accounts: 5,
    num_derogatory_marks: 0,
    months_since_last_delinquency: null,
  };

  it("accepts valid personal data", () => {
    expect(personalInfoSchema.safeParse(validBase).success).toBe(true);
  });

  it("rejects zero or negative annual income", () => {
    const result = personalInfoSchema.safeParse({ ...validBase, annual_income: 0 });
    expect(result.success).toBe(false);
  });

  it("accepts unemployed without tenure", () => {
    const result = personalInfoSchema.safeParse({
      ...validBase,
      employment_status: "unemployed",
      employer_tenure_months: undefined,
    });
    expect(result.success).toBe(true);
  });

  it("accepts null months_since_last_delinquency", () => {
    const result = personalInfoSchema.safeParse({
      ...validBase,
      months_since_last_delinquency: null,
    });
    expect(result.success).toBe(true);
  });

  it("rejects negative existing_debt_amount", () => {
    const result = personalInfoSchema.safeParse({
      ...validBase,
      existing_debt_amount: -100,
    });
    expect(result.success).toBe(false);
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// Consent Schema
// ─────────────────────────────────────────────────────────────────────────────

describe("consentSchema", () => {
  it("requires consent to be true", () => {
    expect(
      consentSchema.safeParse({ consent_credit_check: false }).success
    ).toBe(false);
    expect(
      consentSchema.safeParse({ consent_credit_check: true }).success
    ).toBe(true);
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// CREDIT_SCORE_MAP
// ─────────────────────────────────────────────────────────────────────────────

describe("CREDIT_SCORE_MAP", () => {
  it("maps all four ranges to valid credit scores", () => {
    expect(CREDIT_SCORE_MAP.excellent).toBeGreaterThanOrEqual(750);
    expect(CREDIT_SCORE_MAP.good).toBeGreaterThanOrEqual(700);
    expect(CREDIT_SCORE_MAP.fair).toBeGreaterThanOrEqual(650);
    expect(CREDIT_SCORE_MAP.poor).toBeGreaterThanOrEqual(300);
  });
});
