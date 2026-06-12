import { auth } from "@/auth";
import PortfolioClient from "./PortfolioClient";
import { redirect } from "next/navigation";

export default async function PortfolioPage() {
  const session = await auth();

  if (!session?.user) {
    redirect("/auth/signin");
  }

  const userProps = {
    name: session.user.name ?? "Risk Analyst",
    role: session.user.role ?? "risk_analyst",
    tenantId: session.user.tenantId ?? "helixdecisions",
    tenantName: session.user.tenantName ?? "Helix Decisions",
  };

  return <PortfolioClient user={userProps} />;
}
