import Link from "next/link";
import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { buildTenantPath } from "@/lib/tenant-routing";
import { getSessionTenant, verifyTenantToken } from "@/lib/server-auth";

export default async function SelectTenantPage({
  searchParams,
}: {
  searchParams: Promise<{ reason?: string }>;
}) {
  const params = await searchParams;
  const cookieStore = await cookies();
  const token = cookieStore.get("helix_tenant_token")?.value;

  if (token) {
    const claims = verifyTenantToken(token);
    const tenant = getSessionTenant(claims);
    if (tenant) {
      redirect(buildTenantPath(tenant, "/dashboard"));
    }
  }

  const reasonText: Record<string, string> = {
    missing: "No tenant was found for your account.",
    invalid: "The tenant in the URL is malformed.",
    unauthorized: "You do not have access to that tenant.",
    loop: "We detected a redirect loop and stopped navigation.",
  };

  const reason = params.reason ?? "missing";
  const message = reasonText[reason] ?? reasonText.missing;

  return (
    <main
      style={{
        minHeight: "100vh",
        display: "grid",
        placeItems: "center",
        background: "var(--bg-main)",
        padding: "1.5rem",
      }}
    >
      <section className="card" style={{ maxWidth: "560px", width: "100%", padding: "1.5rem" }}>
        <h1 style={{ margin: 0, marginBottom: "0.5rem", color: "var(--text-primary)" }}>Select Tenant</h1>
        <p style={{ color: "var(--text-secondary)", marginTop: 0 }}>{message}</p>
        <p style={{ color: "var(--text-tertiary)" }}>
          Return to AgentHiveHQ and sign in with an account that has tenant membership.
        </p>

        <div style={{ marginTop: "1rem" }}>
          <Link className="btn btn-primary" href="/login">
            Continue to Sign In
          </Link>
        </div>
      </section>
    </main>
  );
}
