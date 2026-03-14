"use client";

import { useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import type { UserRole } from "@/auth";
import { cn } from "@/lib/utils";

// ─────────────────────────────────────────────────────────────────────────────
// Navigation config per role
// ─────────────────────────────────────────────────────────────────────────────

interface NavItem {
  label: string;
  href: string;
  icon: string;
}

const ROLE_NAV: Record<UserRole, NavItem[]> = {
  underwriter: [
    { label: "Review Queue", href: "/underwriter/queue", icon: "📋" },
    { label: "History", href: "/underwriter/history", icon: "📁" },
    { label: "AI Assistant", href: "/agent", icon: "🤖" },
  ],
  risk_analyst: [
    { label: "Portfolio Health", href: "/risk-analyst/portfolio", icon: "📊" },
    { label: "Credit Risk", href: "/risk-analyst/credit-risk", icon: "⚠️" },
    { label: "Model Performance", href: "/risk-analyst/model-performance", icon: "🎯" },
    { label: "AI Assistant", href: "/agent", icon: "🤖" },
  ],
  compliance: [
    { label: "Fair Lending", href: "/compliance/fair-lending", icon: "⚖️" },
    { label: "Adverse Actions", href: "/compliance/adverse-actions", icon: "📛" },
    { label: "Audit Explorer", href: "/compliance/audit-explorer", icon: "🔍" },
    { label: "Model Governance", href: "/compliance/model-governance", icon: "🏛️" },
    { label: "AI Assistant", href: "/agent", icon: "🤖" },
  ],
  data_scientist: [
    { label: "Model Drift", href: "/data-scientist/drift", icon: "📉" },
    { label: "Feature Analysis", href: "/data-scientist/feature-analysis", icon: "🔬" },
    { label: "Experiments", href: "/data-scientist/experiments", icon: "🧪" },
    { label: "Data Quality", href: "/data-scientist/data-quality", icon: "✅" },
    { label: "AI Assistant", href: "/agent", icon: "🤖" },
  ],
  executive: [
    { label: "Executive Overview", href: "/executive", icon: "📈" },
    { label: "AI Assistant", href: "/agent", icon: "🤖" },
  ],
};

const ROLE_LABELS: Record<UserRole, string> = {
  underwriter: "Underwriter",
  risk_analyst: "Risk Analyst",
  compliance: "Compliance",
  data_scientist: "Data Scientist",
  executive: "Executive",
};

const ROLE_COLORS: Record<UserRole, string> = {
  underwriter: "bg-blue-100 text-blue-800",
  risk_analyst: "bg-purple-100 text-purple-800",
  compliance: "bg-red-100 text-red-800",
  data_scientist: "bg-green-100 text-green-800",
  executive: "bg-amber-100 text-amber-800",
};

// ─────────────────────────────────────────────────────────────────────────────
// DashboardShell — main layout wrapper
// ─────────────────────────────────────────────────────────────────────────────

export function DashboardShell({
  children,
  role,
  userName,
  dateRange,
  onDateRangeChange,
  notificationCount = 0,
}: {
  children: React.ReactNode;
  role: UserRole;
  userName: string;
  dateRange?: "7d" | "30d" | "90d" | "custom";
  onDateRangeChange?: (v: "7d" | "30d" | "90d" | "custom") => void;
  notificationCount?: number;
}) {
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const pathname = usePathname();
  const navItems = ROLE_NAV[role] ?? [];

  const pageName = navItems.find((n) => pathname.startsWith(n.href))?.label ?? "Dashboard";

  return (
    <div className="flex h-screen bg-gray-50 overflow-hidden">
      {/* ── Sidebar ── */}
      <aside
        className={cn(
          "flex flex-col bg-white border-r transition-all duration-200 flex-shrink-0",
          sidebarOpen ? "w-64" : "w-16"
        )}
      >
        {/* Logo */}
        <div className="h-16 flex items-center px-4 border-b gap-3">
          <div className="w-8 h-8 bg-blue-600 rounded-lg flex items-center justify-center text-white font-bold text-sm flex-shrink-0">
            LS
          </div>
          {sidebarOpen && (
            <span className="font-bold text-gray-900 text-sm">LendSmart Analytics</span>
          )}
          <button
            onClick={() => setSidebarOpen(!sidebarOpen)}
            className="ml-auto text-gray-400 hover:text-gray-600"
          >
            {sidebarOpen ? "◀" : "▶"}
          </button>
        </div>

        {/* Role badge */}
        {sidebarOpen && (
          <div className="px-4 py-3 border-b">
            <span className={cn("text-xs font-semibold px-2 py-1 rounded-full", ROLE_COLORS[role])}>
              {ROLE_LABELS[role]}
            </span>
          </div>
        )}

        {/* Nav items */}
        <nav className="flex-1 py-4 overflow-y-auto">
          {navItems.map((item) => {
            const active = pathname.startsWith(item.href);
            return (
              <Link
                key={item.href}
                href={item.href}
                className={cn(
                  "flex items-center gap-3 px-4 py-2.5 text-sm transition-colors mx-2 rounded-lg",
                  active
                    ? "bg-blue-50 text-blue-700 font-medium"
                    : "text-gray-600 hover:bg-gray-50 hover:text-gray-900"
                )}
                title={sidebarOpen ? undefined : item.label}
              >
                <span className="text-base flex-shrink-0">{item.icon}</span>
                {sidebarOpen && <span>{item.label}</span>}
              </Link>
            );
          })}
        </nav>

        {/* User footer */}
        {sidebarOpen && (
          <div className="px-4 py-4 border-t">
            <div className="flex items-center gap-3">
              <div className="w-8 h-8 bg-blue-100 rounded-full flex items-center justify-center text-blue-700 font-bold text-xs flex-shrink-0">
                {userName.slice(0, 2).toUpperCase()}
              </div>
              <div className="min-w-0 flex-1">
                <p className="text-xs font-semibold text-gray-800 truncate">{userName}</p>
                <p className="text-xs text-gray-400">{ROLE_LABELS[role]}</p>
              </div>
              <a href="/auth/signout" className="text-gray-400 hover:text-red-500 text-xs">
                ⏎
              </a>
            </div>
          </div>
        )}
      </aside>

      {/* ── Main area ── */}
      <div className="flex flex-col flex-1 min-w-0 overflow-hidden">
        {/* Top bar */}
        <header className="h-16 bg-white border-b flex items-center px-6 gap-4 flex-shrink-0">
          {/* Breadcrumb */}
          <div className="flex-1 min-w-0">
            <h1 className="text-sm font-semibold text-gray-900 truncate">{pageName}</h1>
          </div>

          {/* Date range selector */}
          {dateRange !== undefined && onDateRangeChange && (
            <select
              value={dateRange}
              onChange={(e) => onDateRangeChange(e.target.value as "7d" | "30d" | "90d" | "custom")}
              className="text-sm border border-gray-200 rounded-lg px-3 py-1.5 bg-white text-gray-700 focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              <option value="7d">Last 7 days</option>
              <option value="30d">Last 30 days</option>
              <option value="90d">Last 90 days</option>
              <option value="custom">Custom</option>
            </select>
          )}

          {/* Notification bell */}
          <button className="relative p-2 text-gray-500 hover:text-gray-700 rounded-lg hover:bg-gray-50">
            🔔
            {notificationCount > 0 && (
              <span className="absolute top-1 right-1 w-4 h-4 bg-red-500 text-white text-xs rounded-full flex items-center justify-center">
                {notificationCount}
              </span>
            )}
          </button>

          {/* Dark mode toggle (placeholder) */}
          <button className="p-2 text-gray-500 hover:text-gray-700 rounded-lg hover:bg-gray-50 text-sm">
            🌙
          </button>
        </header>

        {/* Page content */}
        <main className="flex-1 overflow-y-auto p-6">{children}</main>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Shared KPI Card
// ─────────────────────────────────────────────────────────────────────────────

export function KpiCard({
  label,
  value,
  trend,
  trendLabel,
  icon,
  color = "blue",
}: {
  label: string;
  value: string;
  trend?: number;
  trendLabel?: string;
  icon?: string;
  color?: "blue" | "green" | "red" | "amber" | "purple";
}) {
  const colorMap = {
    blue: "bg-blue-50 text-blue-700",
    green: "bg-green-50 text-green-700",
    red: "bg-red-50 text-red-700",
    amber: "bg-amber-50 text-amber-700",
    purple: "bg-purple-50 text-purple-700",
  };
  return (
    <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-5">
      <div className="flex items-center justify-between mb-3">
        <span className="text-xs font-medium text-gray-500 uppercase tracking-wide">{label}</span>
        {icon && (
          <span className={cn("text-lg w-9 h-9 rounded-lg flex items-center justify-center", colorMap[color])}>
            {icon}
          </span>
        )}
      </div>
      <p className="text-2xl font-black text-gray-900">{value}</p>
      {trend !== undefined && (
        <p className={cn("text-xs mt-1 font-medium", trend >= 0 ? "text-green-600" : "text-red-600")}>
          {trend >= 0 ? "↑" : "↓"} {Math.abs(trend).toFixed(1)}%{" "}
          <span className="text-gray-400 font-normal">{trendLabel}</span>
        </p>
      )}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Status Badge
// ─────────────────────────────────────────────────────────────────────────────

export function StatusBadge({ status }: { status: string }) {
  const map: Record<string, string> = {
    stable: "bg-green-100 text-green-800",
    minor: "bg-amber-100 text-amber-800",
    major: "bg-red-100 text-red-800",
    APPROVE: "bg-green-100 text-green-800",
    REJECT: "bg-red-100 text-red-800",
    MANUAL_REVIEW: "bg-amber-100 text-amber-800",
    approved: "bg-green-100 text-green-800",
    candidate: "bg-gray-100 text-gray-700",
    deprecated: "bg-red-100 text-red-800",
    PASS: "bg-green-100 text-green-700",
    FAIL: "bg-red-100 text-red-700",
  };
  return (
    <span className={cn("inline-flex items-center px-2 py-0.5 rounded-full text-xs font-semibold", map[status] ?? "bg-gray-100 text-gray-700")}>
      {status}
    </span>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Traffic Light for drift
// ─────────────────────────────────────────────────────────────────────────────

export function TrafficLight({ status }: { status: "stable" | "minor" | "major" }) {
  const colors = { stable: "🟢", minor: "🟡", major: "🔴" };
  return <span title={status}>{colors[status]}</span>;
}
