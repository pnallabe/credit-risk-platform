import type { Metadata } from "next";
import { Inter, Instrument_Serif } from "next/font/google";
import "./globals.css";

const inter = Inter({ subsets: ["latin"], variable: "--font-body" });
const instrumentSerif = Instrument_Serif({
  weight: ["400"],
  subsets: ["latin"],
  variable: "--font-display",
});

export const metadata: Metadata = {
  title: "Helix Decisions — Fast, Transparent Loan Decisions",
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
      <body className={`${inter.variable} ${instrumentSerif.variable} font-body`}>
        <div className="min-h-screen flex flex-col">
          <header className="border-b bg-white sticky top-0 z-50">
            <div className="container mx-auto px-4 h-16 flex items-center justify-between">
              <a href="/" className="flex items-center gap-2 font-bold text-xl text-[#0f172a]">
                {/* Helix Decisions double-helix logomark */}
                <svg
                  width="28"
                  height="28"
                  viewBox="0 0 28 28"
                  fill="none"
                  xmlns="http://www.w3.org/2000/svg"
                  aria-label="Helix Decisions"
                >
                  {/* Brand blue rounded background */}
                  <rect width="28" height="28" rx="6" fill="#3366F4" />
                  {/* Strand 1 — front */}
                  <path
                    d="M 8,4 C 8,9 20,9 20,14 C 20,19 8,19 8,24"
                    stroke="white"
                    strokeWidth="2"
                    strokeLinecap="round"
                  />
                  {/* Strand 2 — back, reduced opacity */}
                  <path
                    d="M 20,4 C 20,9 8,9 8,14 C 8,19 20,19 20,24"
                    stroke="white"
                    strokeWidth="2"
                    strokeLinecap="round"
                    strokeOpacity="0.5"
                  />
                  {/* Rung — above first crossing */}
                  <line x1="10" y1="7" x2="18" y2="7" stroke="white" strokeWidth="1.4" strokeLinecap="round" strokeOpacity="0.75" />
                  {/* Rung — center */}
                  <line x1="8" y1="14" x2="20" y2="14" stroke="white" strokeWidth="1.4" strokeLinecap="round" strokeOpacity="0.75" />
                  {/* Rung — below second crossing */}
                  <line x1="10" y1="21" x2="18" y2="21" stroke="white" strokeWidth="1.4" strokeLinecap="round" strokeOpacity="0.75" />
                </svg>
                Helix Decisions
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
              <p className="font-medium">Helix Decisions Financial Services</p>
              <p>
                Helix Decisions is not a bank. Loans are subject to credit approval. APR ranges from
                5.0%–36.0%. Loan amounts from $1,000–$100,000. Terms from 12–60 months.
              </p>
              <p>
                All lending decisions comply with the Equal Credit Opportunity Act (ECOA) and the
                Fair Credit Reporting Act (FCRA). We do not discriminate based on race, color,
                religion, national origin, sex, marital status, age, or other protected
                characteristics.
              </p>
              <p>
                For adverse action inquiries, contact compliance@helixdecisions.ai or call
                1-800-555-0100.
              </p>
              <p className="mt-4">© {new Date().getFullYear()} Helix Decisions, Inc. All rights reserved.</p>
            </div>
          </footer>
        </div>
      </body>
    </html>
  );
}
