import jwt, { type JwtPayload } from "jsonwebtoken";
import { cookies } from "next/headers";
import { canonicalizeTenantSlug, resolvePrimaryTenant, type TenantClaims } from "@/lib/tenant-routing";

export type VerifiedTenantClaims = JwtPayload & TenantClaims;

const JWT_SECRET = process.env.JWT_SECRET || "dev-secret-change-me-in-production";
const AUTH_COOKIE_NAME = "helix_tenant_token";

export async function getSessionToken(): Promise<string | null> {
  const cookieStore = await cookies();
  return cookieStore.get(AUTH_COOKIE_NAME)?.value ?? null;
}

export function verifyTenantToken(token: string): VerifiedTenantClaims | null {
  try {
    const decoded = jwt.verify(token, JWT_SECRET) as VerifiedTenantClaims;
    return decoded;
  } catch {
    return null;
  }
}

export function getSessionTenant(claims: VerifiedTenantClaims | null): string | null {
  const tenant = resolvePrimaryTenant(claims);
  return tenant ? canonicalizeTenantSlug(tenant) : null;
}
