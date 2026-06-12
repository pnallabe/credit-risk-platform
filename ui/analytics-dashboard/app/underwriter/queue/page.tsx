import { auth } from "@/auth";
import UnderwriterQueueClient from "./UnderwriterQueueClient";
import { redirect } from "next/navigation";

export default async function UnderwriterQueuePage() {
  const session = await auth();

  if (!session?.user) {
    redirect("/auth/signin");
  }

  const userProps = {
    name: session.user.name ?? "Underwriter",
    role: session.user.role ?? "underwriter",
    tenantId: session.user.tenantId ?? "helixdecisions",
    tenantName: session.user.tenantName ?? "Helix Decisions",
  };

  return <UnderwriterQueueClient user={userProps} />;
}
