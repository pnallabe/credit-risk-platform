import { auth } from "@/auth";
import { NextResponse } from "next/server";

export async function GET() {
  const session = await auth();
  if (!session?.user) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  const features = [
    "credit_score", "annual_income", "debt_to_income_ratio",
    "credit_utilization", "income_stability_score", "repayment_capacity",
    "derogatory_penalty", "log_loan_amount",
  ];

  const reportFeatures = features.map((f, i) => {
    // Generate deterministic values based on indices to avoid UI hydration mismatches
    const psi = 0.05 + (i * 0.03) % 0.25;
    return {
      feature: f,
      psi,
      ks_pvalue: 0.1 + (i * 0.15) % 0.8,
      status: psi < 0.1 ? ("stable" as const) : psi < 0.25 ? ("minor" as const) : ("major" as const),
    };
  });

  const drift_status = reportFeatures.some(f => f.status === "major")
    ? ("major" as const)
    : reportFeatures.some(f => f.status === "minor")
    ? ("minor" as const)
    : ("stable" as const);

  return NextResponse.json({
    generated_at: new Date().toISOString(),
    drift_status,
    features: reportFeatures,
  });
}
