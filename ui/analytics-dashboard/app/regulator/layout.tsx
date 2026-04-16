import { auth } from "@/auth";
import { redirect } from "next/navigation";
import type { UserRole } from "@/auth";
import Link from "next/link";

export default async function RegulatorLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const session = await auth();
  const role = (session?.user as { role?: UserRole })?.role;

  if (!session?.user || role !== "regulator") {
    redirect("/unauthorized");
  }

  return (
    <div className="min-h-screen bg-gray-50 flex flex-col">
      {/* Read-only header */}
      <header className="bg-white border-b border-gray-200 px-6 py-3 flex items-center justify-between shadow-sm">
        <div className="flex items-center gap-3">
          <span className="text-lg font-bold text-gray-900">LendSmart</span>
          <span className="text-gray-300">|</span>
          <span className="text-sm font-medium text-gray-600">Regulator Portal</span>
        </div>
        <div className="flex items-center gap-2">
          <span className="inline-flex items-center gap-1.5 rounded-full bg-amber-50 border border-amber-200 px-3 py-1 text-xs font-semibold text-amber-800">
            🔒 Read-Only Regulator View
          </span>
          <span className="text-xs text-gray-400">{(session.user as { email?: string }).email}</span>
        </div>
      </header>

      <div className="flex flex-1">
        {/* Sidebar */}
        <nav className="w-56 bg-white border-r border-gray-200 p-4 flex flex-col gap-1">
          <p className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2 px-2">
            Regulator Access
          </p>
          <Link
            href="/regulator"
            className="flex items-center gap-2 px-3 py-2 rounded-lg text-sm text-gray-700 hover:bg-gray-100 transition-colors"
          >
            <span>📊</span> Overview
          </Link>
          <Link
            href="/regulator/audit-records"
            className="flex items-center gap-2 px-3 py-2 rounded-lg text-sm text-gray-700 hover:bg-gray-100 transition-colors"
          >
            <span>🔍</span> Audit Records
          </Link>
          <Link
            href="/regulator/exam-packets"
            className="flex items-center gap-2 px-3 py-2 rounded-lg text-sm text-gray-700 hover:bg-gray-100 transition-colors"
          >
            <span>📦</span> Exam Packets
          </Link>
        </nav>

        {/* Main content */}
        <main className="flex-1 p-6 overflow-auto">{children}</main>
      </div>
    </div>
  );
}
