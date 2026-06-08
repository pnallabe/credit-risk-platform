import { auth } from "@/auth";
import { NextResponse } from "next/server";

export async function GET() {
  const session = await auth();
  if (!session?.user) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  const tenantId = session.user.tenantId ?? "lendsmart";

  let auc = 0.812;
  let ks = 0.421;
  let precision = 0.789;
  let recall = 0.741;
  let f1 = 0.764;
  let version = "LightGBM v3.2";

  if (tenantId === "lending_club") {
    auc = 0.837;
    ks = 0.458;
    precision = 0.812;
    recall = 0.768;
    f1 = 0.789;
    version = "XGBoost v4.1";
  }

  return NextResponse.json({
    credit_risk: {
      auc,
      ks,
      precision,
      recall,
      f1,
      version,
      trained_at: "2026-05-15T08:00:00Z",
    },
    fraud_detection: {
      auc: 0.893,
      precision: 0.921,
      recall: 0.874,
      f1: 0.897,
      version: "v1.4",
      trained_at: "2026-05-15T08:30:00Z",
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
      const tpr = Math.min(1, fpr + (0.35 + Math.random() * 0.1) * (1 - fpr));
      return { fpr, tpr };
    }),
    version_history: [
      { version: "v1.0", auc: 0.795, ks: 0.392, date: "2026-01-15" },
      { version, auc, ks, date: "2026-05-15" },
    ],
  });
}
