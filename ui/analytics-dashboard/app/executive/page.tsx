import { auth } from "@/auth";
import ExecutiveDashboardClient from "./ExecutiveDashboardClient";
import { redirect } from "next/navigation";

export default async function ExecutivePage() {
  const session = await auth();

  if (!session?.user) {
    redirect("/auth/signin");
  }

  const userProps = {
    name: session.user.name ?? "Executive User",
    role: session.user.role ?? "executive",
    tenantId: session.user.tenantId ?? "helixdecisions",
    tenantName: session.user.tenantName ?? "Helix Decisions",
  };

  return <ExecutiveDashboardClient user={userProps} />;
}
