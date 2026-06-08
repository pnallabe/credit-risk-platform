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
    tenantId: session.user.tenantId ?? "lendsmart",
    tenantName: session.user.tenantName ?? "LendSmart",
  };

  return <UnderwriterQueueClient user={userProps} />;
}
