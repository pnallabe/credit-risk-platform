"use client";

import { useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { canonicalizeTenantSlug } from "@/lib/tenant-routing";

function asTenantArray(raw: unknown): string[] {
  if (!Array.isArray(raw)) return [];
  return raw
    .map((item) => {
      if (typeof item === "string") return canonicalizeTenantSlug(item);
      if (item && typeof item === "object") {
        const value = (item as { slug?: string; tenantSlug?: string; id?: string; tenantId?: string }).slug
          ?? (item as { slug?: string; tenantSlug?: string; id?: string; tenantId?: string }).tenantSlug
          ?? (item as { slug?: string; tenantSlug?: string; id?: string; tenantId?: string }).id
          ?? (item as { slug?: string; tenantSlug?: string; id?: string; tenantId?: string }).tenantId;
        return canonicalizeTenantSlug(value ?? "");
      }
      return "";
    })
    .filter(Boolean);
}

export default function TenantSettingsPage() {
  const params = useParams<{ tenantSlug: string }>();
  const router = useRouter();
  const currentTenant = canonicalizeTenantSlug(params.tenantSlug);
  const [selectedTenant, setSelectedTenant] = useState(currentTenant);

  let availableTenants: string[] = [currentTenant];
  if (typeof window !== "undefined") {
    try {
      const fromStorage = asTenantArray(
        JSON.parse(window.localStorage.getItem("helix_tenants") ?? "[]")
      );
      if (fromStorage.length > 0) {
        availableTenants = fromStorage.includes(currentTenant)
          ? fromStorage
          : [currentTenant, ...fromStorage];
      }
    } catch {
      availableTenants = [currentTenant];
    }
  }

  const handleSwitchTenant = () => {
    const canonical = canonicalizeTenantSlug(selectedTenant);
    if (!canonical || canonical === currentTenant) return;

    if (typeof window !== "undefined") {
      window.localStorage.setItem("helix_tenant_slug", canonical);
    }
    router.push(`/t/${canonical}/dashboard`);
  };

  return (
    <div className="flex flex-col gap-4">
      <div>
        <h2 style={{ fontSize: "1.5rem", fontWeight: 700, marginBottom: "0.25rem" }}>Tenant Settings</h2>
        <p style={{ color: "var(--text-secondary)" }}>
          Manage active tenant context for this session.
        </p>
      </div>

      <div className="card" style={{ padding: "1.25rem", maxWidth: "560px" }}>
        <label style={{ display: "block", marginBottom: "0.5rem", color: "var(--text-secondary)" }}>
          Active Tenant
        </label>
        <select
          value={selectedTenant}
          onChange={(event) => setSelectedTenant(event.target.value)}
          style={{
            width: "100%",
            border: "1px solid var(--border-light)",
            borderRadius: "var(--radius-md)",
            padding: "0.75rem",
            background: "var(--bg-main)",
            color: "var(--text-primary)",
            marginBottom: "1rem",
          }}
        >
          {availableTenants.map((tenant) => (
            <option key={tenant} value={tenant}>
              {tenant}
            </option>
          ))}
        </select>

        <button
          type="button"
          className="btn btn-primary"
          onClick={handleSwitchTenant}
          disabled={selectedTenant === currentTenant}
        >
          Switch Tenant
        </button>
      </div>
    </div>
  );
}
