/**
 * POST /api/auth/firebase
 *
 * Accepts a Firebase ID token from AgentHiveHQ (passed as { idToken }).
 * Verifies it via the Firebase Admin REST endpoint (or Admin SDK if available),
 * resolves the tenant mapping, and issues a Helix HS256 JWT — the same format
 * that the rest of the tenant-portal expects from /api/auth/login.
 *
 * AgentHiveHQ crp-routing.ts should POST here immediately after Firebase login,
 * store the returned `token`, and then redirect to /t/{tenantSlug}/dashboard.
 */
import { NextResponse } from "next/server";
import jwt from "jsonwebtoken";
import { canonicalizeTenantSlug } from "@/lib/tenant-routing";

const JWT_SECRET = process.env.JWT_SECRET || "dev-secret-change-me-in-production";
const FIREBASE_PROJECT_ID = process.env.NEXT_PUBLIC_FIREBASE_PROJECT_ID || "";

// Fallback email→tenant map for demo / when Firebase project ID is not set.
const TENANT_MAPPING: Record<string, string> = {
  "admin@prosper.com": "prosper",
  "admin@lendingclub.com": "lending-club",
  "admin@freddiemac.com": "freddie-mac",
  "admin@synthetic.com": "synthetic-tenant",
};

async function verifyFirebaseToken(
  idToken: string
): Promise<{ email: string; uid: string } | null> {
  if (!FIREBASE_PROJECT_ID) {
    // Dev fallback: decode without verification (NOT for production).
    try {
      const decoded = jwt.decode(idToken) as Record<string, unknown> | null;
      if (!decoded) return null;
      return {
        email: typeof decoded.email === "string" ? decoded.email : "",
        uid: typeof decoded.sub === "string" ? decoded.sub : "",
      };
    } catch {
      return null;
    }
  }

  // Verify via Firebase public keys endpoint.
  const verifyUrl = `https://identitytoolkit.googleapis.com/v1/accounts:lookup?key=${process.env.NEXT_PUBLIC_FIREBASE_API_KEY}`;
  try {
    const res = await fetch(verifyUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ idToken }),
    });
    if (!res.ok) return null;
    const data = (await res.json()) as { users?: Array<{ email?: string; localId?: string }> };
    const user = data.users?.[0];
    if (!user) return null;
    return { email: user.email ?? "", uid: user.localId ?? "" };
  } catch {
    return null;
  }
}

function resolveTenantSlug(email: string): string {
  const direct = TENANT_MAPPING[email.toLowerCase()];
  if (direct) return canonicalizeTenantSlug(direct);

  // Domain-based fallback
  const domain = email.split("@")[1] ?? "";
  const domainMap: Record<string, string> = {
    "prosper.com": "prosper",
    "lendingclub.com": "lending-club",
    "freddiemac.com": "freddie-mac",
  };
  if (domainMap[domain]) return canonicalizeTenantSlug(domainMap[domain]);

  // Default demo tenant for unknown emails
  return "synthetic-tenant";
}

export async function POST(request: Request) {
  try {
    const body = await request.json();
    const { idToken } = body as { idToken?: string };

    if (!idToken || typeof idToken !== "string") {
      return NextResponse.json({ error: "idToken is required" }, { status: 400 });
    }

    const firebaseUser = await verifyFirebaseToken(idToken);
    if (!firebaseUser) {
      return NextResponse.json({ error: "Invalid or expired Firebase token" }, { status: 401 });
    }

    const tenantSlug = resolveTenantSlug(firebaseUser.email);

    const helixToken = jwt.sign(
      {
        sub: firebaseUser.email,
        uid: firebaseUser.uid,
        tenant_id: tenantSlug,
        tenant_slug: tenantSlug,
        tenants: [tenantSlug],
        role: "admin",
        auth_type: "firebase",
      },
      JWT_SECRET,
      { algorithm: "HS256", expiresIn: "8h", issuer: "risk-platform" }
    );

    const useSecureCookie = process.env.NODE_ENV === "production";
    const allowCrossSite = process.env.CROSS_SITE_COOKIE === "true";

    const response = NextResponse.json({
      success: true,
      token: helixToken,
      user: { email: firebaseUser.email, tenant_id: tenantSlug, tenant_slug: tenantSlug },
    });

    response.cookies.set({
      name: "helix_tenant_token",
      value: helixToken,
      httpOnly: true,
      secure: useSecureCookie,
      sameSite: allowCrossSite ? "none" : "lax",
      path: "/",
      maxAge: 60 * 60 * 8,
    });

    response.cookies.set({
      name: "helix_tenant_slug",
      value: tenantSlug,
      httpOnly: false,
      secure: useSecureCookie,
      sameSite: allowCrossSite ? "none" : "lax",
      path: "/",
      maxAge: 60 * 60 * 8,
    });

    return response;
  } catch (err) {
    console.error("firebase bridge error", err);
    return NextResponse.json({ error: "Internal server error" }, { status: 500 });
  }
}
