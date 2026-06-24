import { NextResponse } from "next/server";

export async function POST() {
  const response = NextResponse.json({ success: true });
  response.cookies.set({ name: "helix_tenant_token", value: "", maxAge: 0, path: "/" });
  response.cookies.set({ name: "helix_tenant_slug", value: "", maxAge: 0, path: "/" });
  return response;
}
