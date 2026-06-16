const TENANT_SEGMENT_PATTERN = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;

export type TenantClaims = {
  sub?: string;
  tenant_slug?: string;
  tenant_id?: string;
  tenants?: Array<string | { slug?: string; tenantSlug?: string; id?: string; tenantId?: string }>;
};

export function canonicalizeTenantSlug(input: string | null | undefined): string {
  const normalized = (input ?? "")
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9-]/g, "-")
    .replace(/-+/g, "-")
    .replace(/^-|-$/g, "");
  return normalized;
}

export function isCanonicalTenantSlug(input: string): boolean {
  return TENANT_SEGMENT_PATTERN.test(input);
}

export function sanitizeNextPath(nextPath: string | null | undefined): string {
  if (!nextPath) return "/dashboard";

  const candidate = nextPath.trim();
  if (!candidate.startsWith("/")) return "/dashboard";
  if (candidate.startsWith("//")) return "/dashboard";

  try {
    // Prevent absolute URLs and protocol-like payloads.
    const parsed = new URL(candidate, "http://localhost");
    if (parsed.origin !== "http://localhost") return "/dashboard";

    const pathname = parsed.pathname;
    if (pathname.startsWith("/t/")) {
      const parts = pathname.split("/").filter(Boolean);
      if (parts.length >= 3) {
        return `/${parts.slice(2).join("/")}${parsed.search}`;
      }
      return "/dashboard";
    }

    if (pathname === "/dashboard" || pathname === "/reports" || pathname === "/settings") {
      return `${pathname}${parsed.search}`;
    }
  } catch {
    return "/dashboard";
  }

  return "/dashboard";
}

export function normalizeTenantPagePath(nextPath: string | null | undefined): string {
  const sanitized = sanitizeNextPath(nextPath);
  if (sanitized.startsWith("/reports")) return "/reports";
  if (sanitized.startsWith("/settings")) return "/settings";
  return "/dashboard";
}

export function buildTenantPath(tenantSlug: string, nextPath: string | null | undefined): string {
  const canonical = canonicalizeTenantSlug(tenantSlug);
  const pagePath = normalizeTenantPagePath(nextPath);
  return `/t/${canonical}${pagePath}`;
}

function readTenantFromMembership(
  value: string | { slug?: string; tenantSlug?: string; id?: string; tenantId?: string }
): string {
  if (typeof value === "string") {
    return canonicalizeTenantSlug(value);
  }
  return canonicalizeTenantSlug(value.slug ?? value.tenantSlug ?? value.id ?? value.tenantId);
}

export function resolvePrimaryTenant(claims: TenantClaims | null | undefined): string | null {
  if (!claims) return null;

  const direct = canonicalizeTenantSlug(claims.tenant_slug ?? claims.tenant_id);
  if (direct) return direct;

  if (Array.isArray(claims.tenants) && claims.tenants.length > 0) {
    const first = readTenantFromMembership(claims.tenants[0]);
    return first || null;
  }

  return null;
}

export function userHasTenant(claims: TenantClaims | null | undefined, tenantSlug: string): boolean {
  if (!claims) return false;

  const canonicalRequested = canonicalizeTenantSlug(tenantSlug);
  if (!canonicalRequested) return false;

  const primary = resolvePrimaryTenant(claims);
  if (primary && primary === canonicalRequested) return true;

  if (!Array.isArray(claims.tenants)) return false;
  return claims.tenants.some((item) => readTenantFromMembership(item) === canonicalRequested);
}
