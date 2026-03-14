import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";

const inter = Inter({ subsets: ["latin"] });

export const metadata: Metadata = {
  title: "LendSmart — Fast, Transparent Loan Decisions",
  description:
    "Apply for a personal loan in minutes. Get a decision in seconds with clear, transparent terms.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className={inter.className}>
        <div className="min-h-screen flex flex-col">
          <header className="border-b bg-white sticky top-0 z-50">
            <div className="container mx-auto px-4 h-16 flex items-center justify-between">
              <a href="/" className="flex items-center gap-2 font-bold text-xl text-blue-600">
                <svg
                  className="w-7 h-7"
                  fill="none"
                  viewBox="0 0 24 24"
                  stroke="currentColor"
                  strokeWidth={2}
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    d="M12 8c-1.657 0-3 .895-3 2s1.343 2 3 2 3 .895 3 2-1.343 2-3 2m0-8c1.11 0 2.08.402 2.599 1M12 8V7m0 1v8m0 0v1m0-1c-1.11 0-2.08-.402-2.599-1M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
                  />
                </svg>
                LendSmart
              </a>
              <nav className="hidden md:flex items-center gap-6 text-sm">
                <a href="/" className="text-gray-600 hover:text-gray-900 transition-colors">
                  Home
                </a>
                <a href="/apply" className="text-gray-600 hover:text-gray-900 transition-colors">
                  Apply
                </a>
                <a
                  href="/apply"
                  className="bg-blue-600 text-white px-4 py-2 rounded-lg hover:bg-blue-700 transition-colors font-medium"
                >
                  Check Your Rate
                </a>
              </nav>
            </div>
          </header>
          <main className="flex-1">{children}</main>
          <footer className="border-t bg-gray-50 py-8 mt-auto">
            <div className="container mx-auto px-4 text-center text-xs text-gray-500 space-y-2">
              <p className="font-medium">LendSmart Financial Services</p>
              <p>
                LendSmart is not a bank. Loans are subject to credit approval. APR ranges from
                5.0%–36.0%. Loan amounts from $1,000–$100,000. Terms from 12–60 months.
              </p>
              <p>
                All lending decisions comply with the Equal Credit Opportunity Act (ECOA) and the
                Fair Credit Reporting Act (FCRA). We do not discriminate based on race, color,
                religion, national origin, sex, marital status, age, or other protected
                characteristics.
              </p>
              <p>
                For adverse action inquiries, contact compliance@lendsmart.example.com or call
                1-800-555-0100.
              </p>
              <p className="mt-4">© {new Date().getFullYear()} LendSmart. All rights reserved.</p>
            </div>
          </footer>
        </div>
      </body>
    </html>
  );
}
