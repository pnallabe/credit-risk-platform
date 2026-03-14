import Link from "next/link";

export default function LandingPage() {
  return (
    <div className="flex flex-col">
      {/* Hero Section */}
      <section className="relative bg-gradient-to-br from-blue-600 via-blue-700 to-indigo-800 text-white py-24 px-4">
        <div className="container mx-auto max-w-4xl text-center">
          <div className="inline-flex items-center gap-2 bg-blue-500/30 border border-blue-400/40 rounded-full px-4 py-1.5 text-sm font-medium mb-6">
            <span className="w-2 h-2 rounded-full bg-green-400 animate-pulse" />
            Decisions in under 2 seconds
          </div>
          <h1 className="text-5xl md:text-6xl font-extrabold leading-tight mb-6">
            The Smarter Way <br />
            to <span className="text-yellow-300">Get a Loan</span>
          </h1>
          <p className="text-xl md:text-2xl text-blue-100 max-w-2xl mx-auto mb-10">
            Apply in minutes. Get an instant decision. Know your rate before you commit — with full
            transparency on how we made the call.
          </p>
          <div className="flex flex-col sm:flex-row gap-4 justify-center">
            <Link
              href="/apply"
              className="bg-yellow-400 hover:bg-yellow-300 text-gray-900 font-bold py-4 px-10 rounded-xl text-lg transition-all shadow-lg hover:shadow-xl hover:-translate-y-0.5"
            >
              Check Your Rate →
            </Link>
            <a
              href="#how-it-works"
              className="bg-white/10 hover:bg-white/20 border border-white/30 text-white font-semibold py-4 px-10 rounded-xl text-lg transition-all"
            >
              How It Works
            </a>
          </div>
          <p className="text-blue-200 text-sm mt-6">
            Checking your rate won&apos;t affect your credit score
          </p>
        </div>
        {/* Decorative wave */}
        <div className="absolute bottom-0 left-0 right-0">
          <svg viewBox="0 0 1440 60" fill="none" xmlns="http://www.w3.org/2000/svg">
            <path
              d="M0 60H1440V20C1200 60 960 0 720 20C480 40 240 0 0 20V60Z"
              fill="white"
            />
          </svg>
        </div>
      </section>

      {/* Stats Row */}
      <section className="bg-white py-10 border-b">
        <div className="container mx-auto px-4">
          <div className="grid grid-cols-2 md:grid-cols-4 gap-6 text-center">
            {[
              { value: "$5B+", label: "Loans Originated" },
              { value: "250k+", label: "Customers Served" },
              { value: "< 2s", label: "Avg Decision Time" },
              { value: "4.8★", label: "Customer Rating" },
            ].map((stat) => (
              <div key={stat.label}>
                <p className="text-3xl font-bold text-blue-600">{stat.value}</p>
                <p className="text-gray-500 text-sm mt-1">{stat.label}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Benefit Cards */}
      <section className="py-20 bg-white px-4">
        <div className="container mx-auto max-w-5xl">
          <h2 className="text-3xl font-bold text-center text-gray-900 mb-4">
            Why Choose LendSmart?
          </h2>
          <p className="text-center text-gray-500 mb-12 max-w-2xl mx-auto">
            We combine advanced AI with human values to give you a fair, transparent loan
            experience.
          </p>
          <div className="grid md:grid-cols-3 gap-8">
            <BenefitCard
              icon={
                <svg className="w-8 h-8" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M13 10V3L4 14h7v7l9-11h-7z" />
                </svg>
              }
              title="Fast Decision"
              description="Our AI-powered underwriting engine analyzes your application in under 2 seconds, giving you a real-time decision without the wait."
              color="blue"
            />
            <BenefitCard
              icon={
                <svg className="w-8 h-8" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
                </svg>
              }
              title="Transparent Pricing"
              description="See exactly why your rate is what it is. We show you the top factors that influenced your loan offer — no black boxes."
              color="indigo"
            />
            <BenefitCard
              icon={
                <svg className="w-8 h-8" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z" />
                </svg>
              }
              title="Bank-Level Secure"
              description="256-bit encryption, SOC 2 Type II certified. Your personal and financial data is protected at every step of the process."
              color="green"
            />
          </div>
        </div>
      </section>

      {/* How It Works */}
      <section id="how-it-works" className="py-20 bg-gray-50 px-4">
        <div className="container mx-auto max-w-4xl">
          <h2 className="text-3xl font-bold text-center text-gray-900 mb-12">
            Three Simple Steps
          </h2>
          <div className="grid md:grid-cols-3 gap-8">
            {[
              {
                step: "01",
                title: "Tell us about your loan",
                desc: "Select your loan amount, purpose, and preferred term. Takes about 30 seconds.",
              },
              {
                step: "02",
                title: "Share your financial info",
                desc: "Enter your income, employment, and credit information. We use bank-level encryption.",
              },
              {
                step: "03",
                title: "Get your instant decision",
                desc: "Our AI reviews your application and returns a decision — with your rate and the reasons why.",
              },
            ].map((item) => (
              <div key={item.step} className="relative">
                <div className="text-5xl font-black text-blue-100 mb-2">{item.step}</div>
                <h3 className="text-lg font-bold text-gray-900 mb-2">{item.title}</h3>
                <p className="text-gray-500">{item.desc}</p>
              </div>
            ))}
          </div>
          <div className="text-center mt-14">
            <Link
              href="/apply"
              className="bg-blue-600 hover:bg-blue-700 text-white font-bold py-4 px-12 rounded-xl text-lg transition-all shadow-md hover:shadow-lg inline-block"
            >
              Start My Application →
            </Link>
          </div>
        </div>
      </section>

      {/* CTA Banner */}
      <section className="bg-blue-600 text-white py-16 px-4 text-center">
        <h2 className="text-3xl font-bold mb-4">Ready to check your rate?</h2>
        <p className="text-blue-100 mb-8 text-lg">
          No hard credit inquiry. No commitment. Just a fast, honest answer.
        </p>
        <Link
          href="/apply"
          className="bg-white text-blue-700 font-bold py-4 px-12 rounded-xl text-lg hover:bg-blue-50 transition-colors inline-block"
        >
          Check Your Rate — It&apos;s Free
        </Link>
      </section>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Benefit Card Component
// ─────────────────────────────────────────────────────────────────────────────

function BenefitCard({
  icon,
  title,
  description,
  color,
}: {
  icon: React.ReactNode;
  title: string;
  description: string;
  color: "blue" | "indigo" | "green";
}) {
  const colorMap = {
    blue: "bg-blue-50 text-blue-600",
    indigo: "bg-indigo-50 text-indigo-600",
    green: "bg-green-50 text-green-600",
  };
  return (
    <div className="rounded-2xl bg-white border border-gray-100 shadow-sm p-8 hover:shadow-md transition-shadow">
      <div className={`w-14 h-14 rounded-xl flex items-center justify-center mb-5 ${colorMap[color]}`}>
        {icon}
      </div>
      <h3 className="text-xl font-bold text-gray-900 mb-3">{title}</h3>
      <p className="text-gray-500 leading-relaxed">{description}</p>
    </div>
  );
}
