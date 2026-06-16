import { NextRequest, NextResponse } from "next/server";

const LOOP_COOKIE = "crp_bridge_state";
const LOOP_MARKER_QUERY_PARAM = "bridge";
const LOGIN_PATH = "/login";

const LEGACY_ROUTE_TO_TENANT_PATH: Record<string, string> = {
  "/": "/dashboard",
  "/model-diagnostics": "/dashboard",
  "/portfolio": "/reports",
  "/audit": "/reports",
  "/compliance": "/reports",
  "/settings": "/settings",
};

function buildLoginRedirect(request: NextRequest): NextResponse {
  const loginUrl = request.nextUrl.clone();
  loginUrl.pathname = LOGIN_PATH;
  loginUrl.searchParams.set("returnTo", `${request.nextUrl.pathname}${request.nextUrl.search}`);
  return NextResponse.redirect(loginUrl);
}

export function middleware(request: NextRequest): NextResponse {
  const { pathname, searchParams } = request.nextUrl;
  const token = request.cookies.get("helix_tenant_token")?.value;

  const mappedLegacyPath = LEGACY_ROUTE_TO_TENANT_PATH[pathname];
  if (mappedLegacyPath) {
    const tenantSlug = request.cookies.get("helix_tenant_slug")?.value;
    if (!token) {
      return buildLoginRedirect(request);
    }
    if (!tenantSlug) {
      const tenantUrl = request.nextUrl.clone();
      tenantUrl.pathname = "/select-tenant";
      tenantUrl.searchParams.set("reason", "missing");
      return NextResponse.redirect(tenantUrl);
    }
    const canonicalUrl = request.nextUrl.clone();
    canonicalUrl.pathname = `/t/${tenantSlug}${mappedLegacyPath}`;
    return NextResponse.redirect(canonicalUrl);
  }

  if (!pathname.startsWith("/t/")) {
    return NextResponse.next();
  }

  if (!token) {
    return buildLoginRedirect(request);
  }

  const marker = searchParams.get(LOOP_MARKER_QUERY_PARAM);
  if (!marker) {
    return NextResponse.next();
  }

  const previousMarker = request.cookies.get(LOOP_COOKIE)?.value;
  if (previousMarker && previousMarker === marker) {
    const loopUrl = request.nextUrl.clone();
    loopUrl.pathname = "/select-tenant";
    loopUrl.searchParams.set("reason", "loop");
    return NextResponse.redirect(loopUrl);
  }

  const response = NextResponse.next();
  response.cookies.set({
    name: LOOP_COOKIE,
    value: marker,
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "lax",
    path: "/",
    maxAge: 60,
  });
  return response;
}

export const config = {
  matcher: ["/", "/model-diagnostics", "/portfolio", "/audit", "/compliance", "/settings", "/t/:path*"],
};
