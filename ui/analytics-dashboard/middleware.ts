import { auth } from "@/auth";
import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";
import type { UserRole } from "@/auth";

const ROLE_ROUTES: Record<string, UserRole[]> = {
  "/underwriter": ["underwriter"],
  "/risk-analyst": ["risk_analyst"],
  "/compliance": ["compliance"],
  "/data-scientist": ["data_scientist"],
  "/executive": ["executive"],
  "/regulator": ["regulator"],
  "/agent": ["underwriter", "risk_analyst", "compliance", "data_scientist", "executive"],
};

export async function middleware(request: NextRequest) {
  const session = await auth();
  const { pathname } = request.nextUrl;

  // Allow auth routes
  if (pathname.startsWith("/auth")) return NextResponse.next();

  // Require login for all dashboard routes
  if (!session?.user) {
    return NextResponse.redirect(new URL("/auth/signin", request.url));
  }

  const userRole = (session.user as { role?: UserRole }).role;

  // Regulator routes: read-only enforcement — block non-GET methods
  if (pathname.startsWith("/regulator")) {
    if (request.method !== "GET" && request.method !== "HEAD") {
      return new NextResponse(null, { status: 405, statusText: "Method Not Allowed" });
    }
  }

  // Check role-based access
  for (const [routePrefix, allowedRoles] of Object.entries(ROLE_ROUTES)) {
    if (pathname.startsWith(routePrefix)) {
      if (!userRole || !allowedRoles.includes(userRole)) {
        return NextResponse.redirect(new URL("/unauthorized", request.url));
      }
    }
  }

  return NextResponse.next();
}

export const config = {
  matcher: [
    "/underwriter/:path*",
    "/risk-analyst/:path*",
    "/compliance/:path*",
    "/data-scientist/:path*",
    "/executive/:path*",
    "/regulator/:path*",
    "/agent/:path*",
  ],
};
