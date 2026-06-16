import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { resolvePrimaryTenant, sanitizeNextPath, userHasTenant } from "@/lib/tenant-routing";

describe("sanitizeNextPath", () => {
  it("rejects external urls", () => {
    assert.equal(sanitizeNextPath("https://evil.example/reports"), "/dashboard");
  });

  it("accepts in-app tenant pages and normalizes to route suffix", () => {
    assert.equal(sanitizeNextPath("/t/prosper/reports"), "/reports");
  });

  it("rejects malformed paths", () => {
    assert.equal(sanitizeNextPath("javascript:alert(1)"), "/dashboard");
  });
});

describe("resolvePrimaryTenant", () => {
  it("returns direct tenant claim first", () => {
    assert.equal(resolvePrimaryTenant({ tenant_slug: "prosper" }), "prosper");
  });

  it("returns first tenant membership when direct claim missing", () => {
    assert.equal(resolvePrimaryTenant({ tenants: ["lending-club", "freddie-mac"] }), "lending-club");
  });

  it("returns null when no tenant exists", () => {
    assert.equal(resolvePrimaryTenant({ sub: "user-1" }), null);
  });
});

describe("userHasTenant", () => {
  const claims = {
    tenant_slug: "prosper",
    tenants: ["prosper", { slug: "lending-club" }],
  };

  it("returns true for authorized tenant", () => {
    assert.equal(userHasTenant(claims, "prosper"), true);
  });

  it("returns false for unauthorized tenant", () => {
    assert.equal(userHasTenant(claims, "freddie-mac"), false);
  });
});
