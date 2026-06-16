import { auth } from "@/auth";
import { NextResponse } from "next/server";

export async function GET() {
  const session = await auth();
  if (!session?.user) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  const tenantId = session.user.tenantId ?? "helixdecisions";

  let dir_score = 0.87;
  let dir_flag = false;
  let summary_text = "Approval rates are broadly equitable across demographic groups. DIR of 0.87 exceeds the 4/5ths threshold (0.80). Geographic analysis flags 2 states with approval rates below mean.";
  let approval_parity_p_value = 0.12;

  if (tenantId === "lending_club") {
    dir_score = 0.89;
    dir_flag = false;
    summary_text = "Approval rates are highly equitable. DIR of 0.89 exceeds the 4/5ths safety boundary (0.80). Compliance thresholds met.";
    approval_parity_p_value = 0.18;
  }

  return NextResponse.json({
    generated_at: new Date().toISOString(),
    dir_score,
    dir_flag,
    approval_parity_p_value,
    geographic_flags: ["MS", "WV"],
    summary_text,
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
  });
}
