"use client";

import { useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  ClipboardList,
  FolderOpen,
  BarChart3,
  AlertTriangle,
  Target,
  LayoutDashboard,
  Scale,
  AlertCircle,
  Search,
  Building2,
  TrendingDown,
  Microscope,
  FlaskConical,
  CheckSquare,
  TrendingUp,
  Bot,
  Bell,
  Moon,
  LogOut,
  ChevronLeft,
  ChevronRight,
  Menu,
  X,
  Check,
  Clock,
  Settings,
} from "lucide-react";
import type { UserRole } from "@/auth";
import { cn } from "@/lib/utils";

// ─────────────────────────────────────────────────────────────────────────────
// Navigation config per role
// ─────────────────────────────────────────────────────────────────────────────

interface NavItem {
  label: string;
  href: string;
  icon: React.ReactNode;
}

const ROLE_NAV: Record<UserRole, NavItem[]> = {
  underwriter: [
    { label: "Review Queue", href: "/underwriter/queue", icon: <ClipboardList className="w-4 h-4" /> },
    { label: "History", href: "/underwriter/history", icon: <FolderOpen className="w-4 h-4" /> },
    { label: "AI Assistant", href: "/agent", icon: <Bot className="w-4 h-4" /> },
  ],
  risk_analyst: [
    { label: "Portfolio Health", href: "/risk-analyst/portfolio", icon: <BarChart3 className="w-4 h-4" /> },
    { label: "Credit Risk", href: "/risk-analyst/credit-risk", icon: <AlertTriangle className="w-4 h-4" /> },
    { label: "Model Performance", href: "/risk-analyst/model-performance", icon: <Target className="w-4 h-4" /> },
    { label: "AI Assistant", href: "/agent", icon: <Bot className="w-4 h-4" /> },
  ],
  compliance: [
    { label: "Command Center", href: "/compliance/command-center", icon: <LayoutDashboard className="w-4 h-4" /> },
    { label: "Fair Lending", href: "/compliance/fair-lending", icon: <Scale className="w-4 h-4" /> },
    { label: "Adverse Actions", href: "/compliance/adverse-actions", icon: <AlertCircle className="w-4 h-4" /> },
    { label: "Audit Explorer", href: "/compliance/audit-explorer", icon: <Search className="w-4 h-4" /> },
    { label: "Model Governance", href: "/compliance/model-governance", icon: <Building2 className="w-4 h-4" /> },
    { label: "AI Assistant", href: "/agent", icon: <Bot className="w-4 h-4" /> },
  ],
  data_scientist: [
    { label: "Model Drift", href: "/data-scientist/drift", icon: <TrendingDown className="w-4 h-4" /> },
    { label: "Feature Analysis", href: "/data-scientist/feature-analysis", icon: <Microscope className="w-4 h-4" /> },
    { label: "Experiments", href: "/data-scientist/experiments", icon: <FlaskConical className="w-4 h-4" /> },
    { label: "Data Quality", href: "/data-scientist/data-quality", icon: <CheckSquare className="w-4 h-4" /> },
    { label: "AI Assistant", href: "/agent", icon: <Bot className="w-4 h-4" /> },
  ],
  executive: [
    { label: "Executive Overview", href: "/executive", icon: <TrendingUp className="w-4 h-4" /> },
    { label: "AI Assistant", href: "/agent", icon: <Bot className="w-4 h-4" /> },
  ],
  regulator: [
    { label: "Exam Packets", href: "/regulator/exam-packets", icon: <FolderOpen className="w-4 h-4" /> },
    { label: "Audit Records", href: "/regulator/audit-records", icon: <Search className="w-4 h-4" /> },
    { label: "AI Assistant", href: "/agent", icon: <Bot className="w-4 h-4" /> },
  ],
};

const ROLE_LABELS: Record<UserRole, string> = {
  underwriter: "Underwriter",
  risk_analyst: "Risk Analyst",
  compliance: "Compliance",
  data_scientist: "Data Scientist",
  executive: "Executive",
  regulator: "Regulator",
};

const ROLE_COLORS: Record<UserRole, string> = {
  underwriter: "bg-brand-500/10 text-brand-400 border border-brand-500/20",
  risk_analyst: "bg-violet-500/10 text-violet-400 border border-violet-500/20",
  compliance: "bg-rose-500/10 text-rose-400 border border-rose-500/20",
  data_scientist: "bg-emerald-500/10 text-emerald-400 border border-emerald-500/20",
  executive: "bg-amber-500/10 text-amber-400 border border-amber-500/20",
  regulator: "bg-zinc-500/10 text-zinc-400 border border-zinc-500/20",
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
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const pathname = usePathname();
  const navItems = ROLE_NAV[role] ?? [];

  const pageName = navItems.find((n) => pathname.startsWith(n.href))?.label ?? "Dashboard";

  return (
    <div className="flex h-screen bg-[#09090b] text-[#fafafa] overflow-hidden font-sans">
      {/* ── Mobile nav overlay ── */}
      {mobileNavOpen && (
        <div
          className="fixed inset-0 z-40 bg-black/60 backdrop-blur-sm md:hidden"
          onClick={() => setMobileNavOpen(false)}
          aria-hidden="true"
        />
      )}

      {/* ── Mobile nav drawer ── */}
      <div
        id="mobile-nav"
        role="navigation"
        aria-label="Mobile navigation"
        className={cn(
          "fixed inset-y-0 left-0 z-50 w-72 bg-[#0c0c0e] border-r border-[#27272a] flex flex-col md:hidden transition-transform duration-200 shadow-2xl",
          mobileNavOpen ? "translate-x-0" : "-translate-x-full"
        )}
      >
        <div className="h-16 flex items-center px-4 border-b border-[#27272a] gap-3">
          <svg width="24" height="24" viewBox="0 0 28 28" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true" className="text-brand-500">
            <path d="M14 2L24.7 8V20L14 26L3.3 20V8L14 2Z" fill="currentColor"></path>
            <path d="M14 8L19.2 11V17L14 20L8.8 17V11L14 8Z" fill="none" stroke="white" strokeWidth="1.2" strokeOpacity="0.9"></path>
            <circle cx="14" cy="14" r="1.5" fill="white" fillOpacity="0.9"></circle>
          </svg>
          <span className="font-bold text-[#fafafa] text-sm tracking-tight">AgentHive Analytics</span>
          <button
            onClick={() => setMobileNavOpen(false)}
            className="ml-auto text-zinc-400 hover:text-zinc-200"
            aria-label="Close navigation"
          >
            <X className="w-5 h-5" />
          </button>
        </div>
        <div className="px-4 py-3 border-b border-[#27272a]">
          <span className={cn("text-xs font-semibold px-2 py-1 rounded-full", ROLE_COLORS[role])}>
            {ROLE_LABELS[role]}
          </span>
        </div>
        <nav className="flex-1 py-4 overflow-y-auto space-y-1">
          {navItems.map((item) => {
            const active = pathname.startsWith(item.href);
            return (
              <Link
                key={`mobile-${item.href}`}
                href={item.href}
                onClick={() => setMobileNavOpen(false)}
                className={cn(
                  "flex items-center gap-3 px-4 py-2.5 text-sm transition-all mx-2 rounded-lg",
                  active
                    ? "bg-brand-500/10 text-brand-400 font-semibold border-l-2 border-brand-500"
                    : "text-zinc-400 hover:bg-zinc-800/50 hover:text-[#fafafa]"
                )}
              >
                <span className="flex-shrink-0">{item.icon}</span>
                <span>{item.label}</span>
              </Link>
            );
          })}
        </nav>
        <div className="px-4 py-4 border-t border-[#27272a]">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 bg-brand-500/10 text-brand-400 rounded-full flex items-center justify-center font-bold text-xs flex-shrink-0">
              {userName.slice(0, 2).toUpperCase()}
            </div>
            <div className="min-w-0 flex-1">
              <p className="text-xs font-semibold text-zinc-200 truncate">{userName}</p>
              <p className="text-xs text-zinc-500">{ROLE_LABELS[role]}</p>
            </div>
            <a href="/auth/signout" className="text-zinc-400 hover:text-rose-400" aria-label="Sign out">
              <LogOut className="w-3.5 h-3.5" />
            </a>
          </div>
        </div>
      </div>

      {/* ── Desktop Sidebar ── */}
      <aside
        className={cn(
          "hidden md:flex flex-col bg-[#0c0c0e] border-r border-[#27272a] transition-all duration-200 flex-shrink-0 relative radial-glow-bg",
          sidebarOpen ? "w-64" : "w-16"
        )}
      >
        {/* Logo */}
        <div className="h-16 flex items-center px-4 border-b border-[#27272a] gap-3">
          <svg width="24" height="24" viewBox="0 0 28 28" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true" className="text-brand-500 flex-shrink-0">
            <path d="M14 2L24.7 8V20L14 26L3.3 20V8L14 2Z" fill="currentColor"></path>
            <path d="M14 8L19.2 11V17L14 20L8.8 17V11L14 8Z" fill="none" stroke="white" strokeWidth="1.2" strokeOpacity="0.9"></path>
            <circle cx="14" cy="14" r="1.5" fill="white" fillOpacity="0.9"></circle>
          </svg>
          {sidebarOpen && (
            <span className="font-bold text-[#fafafa] text-sm tracking-tight bg-gradient-to-r from-white via-zinc-100 to-zinc-300 bg-clip-text text-transparent">
              AgentHive Analytics
            </span>
          )}
          <button
            onClick={() => setSidebarOpen(!sidebarOpen)}
            className="ml-auto text-zinc-400 hover:text-zinc-200 p-1 rounded-md hover:bg-zinc-800/40"
            aria-label={sidebarOpen ? "Collapse sidebar" : "Expand sidebar"}
          >
            {sidebarOpen ? <ChevronLeft className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
          </button>
        </div>

        {/* Role badge */}
        {sidebarOpen && (
          <div className="px-4 py-3 border-b border-[#27272a]">
            <span className={cn("text-xs font-semibold px-2 py-1 rounded-full", ROLE_COLORS[role])}>
              {ROLE_LABELS[role]}
            </span>
          </div>
        )}

        {/* Nav items */}
        <nav className="flex-1 py-4 overflow-y-auto space-y-1">
          {navItems.map((item) => {
            const active = pathname.startsWith(item.href);
            return (
              <Link
                key={item.href}
                href={item.href}
                className={cn(
                  "flex items-center gap-3 px-4 py-2.5 text-sm transition-all mx-2 rounded-lg",
                  active
                    ? "bg-brand-500/10 text-brand-400 font-semibold border-l-2 border-brand-500"
                    : "text-zinc-400 hover:bg-zinc-800/40 hover:text-[#fafafa]"
                )}
                title={!sidebarOpen ? item.label : undefined}
                aria-label={!sidebarOpen ? item.label : undefined}
              >
                <span className="text-base flex-shrink-0">{item.icon}</span>
                {sidebarOpen && <span>{item.label}</span>}
              </Link>
            );
          })}
        </nav>

        {/* User footer */}
        {sidebarOpen && (
          <div className="px-4 py-4 border-t border-[#27272a]">
            <div className="flex items-center gap-3">
              <div className="w-8 h-8 bg-brand-500/10 text-brand-400 rounded-full flex items-center justify-center font-bold text-xs flex-shrink-0">
                {userName.slice(0, 2).toUpperCase()}
              </div>
              <div className="min-w-0 flex-1">
                <p className="text-xs font-semibold text-zinc-200 truncate">{userName}</p>
                <p className="text-xs text-zinc-500">{ROLE_LABELS[role]}</p>
              </div>
              <a href="/auth/signout" className="text-zinc-400 hover:text-rose-400" aria-label="Sign out">
                <LogOut className="w-3.5 h-3.5" />
              </a>
            </div>
          </div>
        )}
      </aside>

      {/* ── Main area ── */}
      <div className="flex flex-col flex-1 min-w-0 overflow-hidden relative">
        {/* Decorative background glow circles */}
        <div className="absolute top-0 right-1/4 w-96 h-96 bg-brand-500/5 rounded-full blur-3xl pointer-events-none z-0"></div>

        {/* Top bar */}
        <header className="h-16 bg-[#09090b]/80 backdrop-blur-md border-b border-[#27272a] flex items-center px-4 md:px-6 gap-4 flex-shrink-0 z-10">
          {/* Mobile hamburger */}
          <button
            className="md:hidden p-2 -ml-1 text-zinc-400 hover:text-zinc-200 rounded-lg hover:bg-zinc-800"
            onClick={() => setMobileNavOpen(true)}
            aria-label="Open navigation"
            aria-expanded={mobileNavOpen}
            aria-controls="mobile-nav"
          >
            <Menu className="w-5 h-5" />
          </button>

          {/* Breadcrumb */}
          <div className="flex-1 min-w-0">
            <h1 className="text-sm font-semibold text-[#fafafa] tracking-tight truncate">{pageName}</h1>
          </div>

          {/* Date range selector */}
          {dateRange !== undefined && onDateRangeChange && (
            <select
              value={dateRange}
              onChange={(e) => onDateRangeChange(e.target.value as "7d" | "30d" | "90d" | "custom")}
              className="text-xs border border-[#27272a] rounded-lg px-3 py-1.5 bg-[#18181b] text-zinc-200 focus:outline-none focus:ring-2 focus:ring-brand-500"
            >
              <option value="7d">Last 7 days</option>
              <option value="30d">Last 30 days</option>
              <option value="90d">Last 90 days</option>
              <option value="custom">Custom</option>
            </select>
          )}

          {/* Notification bell */}
          <button className="relative p-2 text-zinc-400 hover:text-zinc-200 rounded-lg hover:bg-zinc-800/40" aria-label="Notifications">
            <Bell className="w-4 h-4" />
            {notificationCount > 0 && (
              <span className="absolute top-1.5 right-1.5 w-3.5 h-3.5 bg-rose-500 text-white text-[9px] rounded-full flex items-center justify-center animate-pulse">
                {notificationCount}
              </span>
            )}
          </button>

          {/* Dark mode indicator (showing active) */}
          <button className="p-2 text-brand-400 hover:text-brand-300 rounded-lg hover:bg-zinc-800/40" aria-label="Dark mode active">
            <Moon className="w-4 h-4" />
          </button>
        </header>

        {/* Page content */}
        <main className="flex-1 overflow-y-auto p-6 z-10 relative">{children}</main>
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
    blue: "bg-brand-500/10 text-brand-400 border border-brand-500/20",
    green: "bg-emerald-500/10 text-emerald-400 border border-emerald-500/20",
    red: "bg-rose-500/10 text-rose-400 border border-rose-500/20",
    amber: "bg-amber-500/10 text-amber-400 border border-amber-500/20",
    purple: "bg-violet-500/10 text-violet-400 border border-violet-500/20",
  };
  return (
    <div className="bg-[#18181b] rounded-xl border border-[#27272a] p-5 card-hover-effect">
      <div className="flex items-center justify-between mb-3">
        <span className="text-xs font-semibold text-zinc-400 uppercase tracking-wider">{label}</span>
        {icon && (
          <span className={cn("text-base w-9 h-9 rounded-lg flex items-center justify-center", colorMap[color])}>
            {icon}
          </span>
        )}
      </div>
      <p className="text-2xl font-black text-white tracking-tight">{value}</p>
      {trend !== undefined && (
        <p className={cn("text-xs mt-1.5 font-semibold", trend >= 0 ? "text-emerald-400" : "text-rose-400")}>
          {trend >= 0 ? "↑" : "↓"} {Math.abs(trend).toFixed(1)}%{" "}
          <span className="text-zinc-500 font-normal">{trendLabel}</span>
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
    stable: "bg-emerald-500/15 text-emerald-400 border border-emerald-500/20",
    minor: "bg-amber-500/15 text-amber-400 border border-amber-500/20",
    major: "bg-rose-500/15 text-rose-400 border border-rose-500/20",
    APPROVE: "bg-emerald-500/15 text-emerald-400 border border-emerald-500/20",
    REJECT: "bg-rose-500/15 text-rose-400 border border-rose-500/20",
    MANUAL_REVIEW: "bg-amber-500/15 text-amber-400 border border-amber-500/20",
    approved: "bg-emerald-500/15 text-emerald-400 border border-emerald-500/20",
    candidate: "bg-zinc-800 text-zinc-300 border border-zinc-700",
    deprecated: "bg-rose-500/15 text-rose-400 border border-rose-500/20",
    PASS: "bg-emerald-500/15 text-emerald-400 border border-emerald-500/20",
    FAIL: "bg-rose-500/15 text-rose-400 border border-rose-500/20",
  };
  const iconMap: Record<string, React.ReactNode> = {
    APPROVE: <Check className="w-3 h-3" aria-hidden="true" />,
    approved: <Check className="w-3 h-3" aria-hidden="true" />,
    PASS: <Check className="w-3 h-3" aria-hidden="true" />,
    REJECT: <X className="w-3 h-3" aria-hidden="true" />,
    FAIL: <X className="w-3 h-3" aria-hidden="true" />,
    MANUAL_REVIEW: <Clock className="w-3 h-3" aria-hidden="true" />,
  };
  const label = status.replace(/_/g, " ");
  return (
    <span className={cn("inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-semibold", map[status] ?? "bg-zinc-800 text-zinc-300 border border-zinc-700")}>
      {iconMap[status]}
      {label}
    </span>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Traffic Light for drift
// ─────────────────────────────────────────────────────────────────────────────

export function TrafficLight({ status }: { status: "stable" | "minor" | "major" }) {
  const config: Record<"stable" | "minor" | "major", { dot: string; label: string }> = {
    stable: { dot: "bg-emerald-500 shadow-sm shadow-emerald-500/50", label: "Stable" },
    minor: { dot: "bg-amber-500 shadow-sm shadow-amber-500/50", label: "Caution" },
    major: { dot: "bg-rose-500 shadow-sm shadow-rose-500/50", label: "Critical" },
  };
  const { dot, label } = config[status];
  return (
    <span className="inline-flex items-center gap-2" aria-label={label}>
      <span className={`w-2 h-2 rounded-full flex-shrink-0 ${dot}`} aria-hidden="true" />
      <span className="text-xs font-semibold text-zinc-300">{label}</span>
    </span>
  );
}
