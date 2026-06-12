import type { ReactNode } from "react";
import { redirect } from "next/navigation";
import { canonicalizeTenantSlug, isCanonicalTenantSlug, userHasTenant } from "@/lib/tenant-routing";
import { getSessionTenant, getSessionToken, verifyTenantToken } from "@/lib/server-auth";

type TenantLayoutProps = {
  children: ReactNode;
  params: Promise<{ tenantSlug: string }>;
};

export default async function TenantLayout({ children, params }: TenantLayoutProps) {
  const { tenantSlug } = await params;
  const canonicalRequestedTenant = canonicalizeTenantSlug(tenantSlug);

  if (!canonicalRequestedTenant || !isCanonicalTenantSlug(canonicalRequestedTenant)) {
    redirect("/select-tenant?reason=invalid");
  }

  const token = await getSessionToken();
  if (!token) {
    redirect(`/login?returnTo=/t/${canonicalRequestedTenant}/dashboard`);
  }

  const claims = verifyTenantToken(token);
  if (!claims) {
    redirect(`/login?returnTo=/t/${canonicalRequestedTenant}/dashboard&reason=expired`);
  }

  const sessionTenant = getSessionTenant(claims);
  if (!sessionTenant) {
    redirect("/select-tenant?reason=missing");
  }

  if (tenantSlug !== canonicalRequestedTenant) {
    redirect(`/t/${canonicalRequestedTenant}/dashboard`);
  }

  if (!userHasTenant(claims, canonicalRequestedTenant)) {
    const subject = typeof claims.sub === "string" ? claims.sub : "unknown";
    console.warn("tenant_guard_denied", {
      userId: subject,
      tenantSlug: canonicalRequestedTenant,
      requestPath: `/t/${canonicalRequestedTenant}`,
      reason: "membership_mismatch",
    });
    redirect("/select-tenant?reason=unauthorized");
  }

  return <>{children}</>;
}
