import { auth } from "@/auth";
import { redirect } from "next/navigation";
import type { UserRole } from "@/auth";

const ROLE_HOME: Record<UserRole, string> = {
  underwriter: "/underwriter/queue",
  risk_analyst: "/risk-analyst/portfolio",
  compliance: "/compliance/command-center",
  data_scientist: "/data-scientist/drift",
  executive: "/executive",
  regulator: "/regulator",
};

export default async function RootPage() {
  const session = await auth();

  if (!session?.user) {
    redirect("/auth/signin");
  }

  const role = (session.user as { role?: UserRole }).role;
  const home = role ? ROLE_HOME[role] : "/agent";
  redirect(home);
}
