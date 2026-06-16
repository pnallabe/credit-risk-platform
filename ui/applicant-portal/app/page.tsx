import Link from "next/link";

export default function LandingPage() {
  return (
    <div className="flex flex-col">
      {/* ── Hero ── */}
      {/* Left-aligned, serif display headline, cream background — no gradient */}
      <section className="bg-[#fafaf8] py-20 md:py-28 px-4 border-b border-gray-100">
        <div className="container mx-auto max-w-5xl">
          <div className="max-w-2xl">
            {/* Trust signal pill */}
            <div className="inline-flex items-center gap-2 border border-[#0f172a]/20 rounded-full px-4 py-1.5 text-sm font-medium text-[#374151] mb-8">
              <span className="w-2 h-2 rounded-full bg-green-500 animate-pulse" aria-hidden="true" />
              Decision in under 2 seconds · No hard credit pull
            </div>

            {/* Display headline — Instrument Serif */}
            <h1 className="font-display text-5xl md:text-6xl text-[#0f172a] leading-[1.1] mb-6">
              Your rate. <br />
              Your terms. <br />
              <span className="text-[#1e3a5f]">Decided fairly.</span>
            </h1>

            <p className="text-lg md:text-xl text-[#374151] max-w-xl mb-10 leading-relaxed">
              Apply in 5 minutes. Know your rate before you commit.
              We show you exactly how we made the call — no black boxes.
            </p>

            {/* CTA group */}
            <div className="flex flex-col sm:flex-row gap-4">
              <Link
                href="/apply"
                className="inline-flex items-center justify-center bg-[#0f172a] hover:bg-[#1e3a5f] text-white font-semibold py-4 px-10 rounded-lg text-base transition-colors shadow-sm hover:shadow-md"
              >
                Check Your Rate →
              </Link>
              <a
                href="#how-it-works"
                className="inline-flex items-center justify-center border border-[#0f172a]/20 text-[#374151] hover:border-[#0f172a]/40 hover:text-[#0f172a] font-medium py-4 px-10 rounded-lg text-base transition-colors"
              >
                How It Works
              </a>
            </div>
          </div>
        </div>
      </section>

      {/* ── Trust Signals ── */}
      {/* Replace 3-column benefit cards with inline scannable signals */}
      <section className="bg-white py-8 border-b border-gray-100">
        <div className="container mx-auto px-4">
          <div className="flex flex-wrap gap-x-8 gap-y-3 items-center text-sm text-[#374151]">
            <TrustSignal icon={<LockIcon />} text="256-bit encryption" />
            <span className="hidden sm:block text-gray-200">|</span>
            <TrustSignal icon={<ScaleIcon />} text="ECOA & FCRA compliant" />
            <span className="hidden sm:block text-gray-200">|</span>
            <TrustSignal icon={<ShieldIcon />} text="SOC 2 Type II certified" />
            <span className="hidden sm:block text-gray-200">|</span>
            <TrustSignal icon={<ClockIcon />} text="Rates from 5.0% APR" />
          </div>
        </div>
      </section>

      {/* ── How It Works ── */}
      <section id="how-it-works" className="py-20 bg-white px-4">
        <div className="container mx-auto max-w-4xl">
          <h2 className="font-display text-3xl md:text-4xl text-[#0f172a] mb-2">
            Three steps, one decision.
          </h2>
          <p className="text-[#6b7280] mb-14 text-base">
            Most applicants finish in under 5 minutes.
          </p>

          <div className="grid md:grid-cols-3 gap-10">
            {[
              {
                step: "01",
                title: "Choose your loan",
                desc: "Pick your amount, purpose, and term. The calculator shows your estimated monthly payment as you go.",
              },
              {
                step: "02",
                title: "Share your information",
                desc: "Income, employment, and credit range. Encrypted end-to-end. We only request what we need.",
              },
              {
                step: "03",
                title: "Get your decision",
                desc: "Your rate, the factors that determined it, and your next step — all in under 2 seconds.",
              },
            ].map((item) => (
              <div key={item.step}>
                <p className="text-[#b87333] font-mono text-sm font-semibold mb-3 tracking-widest">
                  STEP {item.step}
                </p>
                <h3 className="text-lg font-semibold text-[#0f172a] mb-2">{item.title}</h3>
                <p className="text-[#6b7280] leading-relaxed">{item.desc}</p>
              </div>
            ))}
          </div>

          <div className="mt-14 pt-10 border-t border-gray-100">
            <Link
              href="/apply"
              className="inline-flex items-center bg-[#0f172a] hover:bg-[#1e3a5f] text-white font-semibold py-4 px-10 rounded-lg text-base transition-colors"
            >
              Start My Application →
            </Link>
            <p className="text-sm text-[#9ca3af] mt-3">
              Checking your rate won&apos;t affect your credit score.
            </p>
          </div>
        </div>
      </section>

      {/* ── Why Helix Decisions ── */}
      {/* One job: build final-mile trust before the form */}
      <section className="py-20 bg-[#f1f5f9] px-4">
        <div className="container mx-auto max-w-4xl">
          <h2 className="font-display text-3xl md:text-4xl text-[#0f172a] mb-12">
            Built around you, not around our models.
          </h2>

          <div className="grid md:grid-cols-2 gap-8">
            <WhyItem
              title="You see what we see"
              desc="Every decision comes with the top factors that influenced your offer — the same factors our underwriters review. You&apos;re never left guessing."
            />
            <WhyItem
              title="Fair lending, by design"
              desc="Our models are tested for bias before and after deployment. We follow the Equal Credit Opportunity Act — and we can prove it."
            />
            <WhyItem
              title="No surprises at signing"
              desc="Your rate is locked when you accept. No bait-and-switch, no hidden origination fees that appear on closing day."
            />
            <WhyItem
              title="Humans in the loop"
              desc="Complex applications go to a human underwriter within 1–2 business days. You&apos;ll hear back with a decision and a reason."
            />
          </div>
        </div>
      </section>

      {/* ── CTA Banner ── */}
      <section className="bg-[#0f172a] text-white py-20 px-4">
        <div className="container mx-auto max-w-4xl">
          <h2 className="font-display text-3xl md:text-4xl mb-4">
            Ready to check your rate?
          </h2>
          <p className="text-[#94a3b8] mb-8 text-lg max-w-lg">
            No hard credit inquiry. No commitment. A fast, honest answer.
          </p>
          <Link
            href="/apply"
            className="inline-flex items-center bg-[#b87333] hover:bg-[#a0622b] text-white font-semibold py-4 px-12 rounded-lg text-base transition-colors"
          >
            Check Your Rate — It&apos;s Free
          </Link>
        </div>
      </section>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Trust Signal — inline row, no cards
// ─────────────────────────────────────────────────────────────────────────────

function TrustSignal({ icon, text }: { icon: React.ReactNode; text: string }) {
  return (
    <span className="flex items-center gap-1.5 text-[#374151]">
      <span className="w-4 h-4 text-[#1e3a5f] flex-shrink-0" aria-hidden="true">{icon}</span>
      {text}
    </span>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Why Item — two-column text blocks, no card containers
// ─────────────────────────────────────────────────────────────────────────────

function WhyItem({ title, desc }: { title: string; desc: string }) {
  return (
    <div className="border-l-2 border-[#b87333] pl-5">
      <h3 className="font-semibold text-[#0f172a] mb-1">{title}</h3>
      <p className="text-[#6b7280] text-sm leading-relaxed">{desc}</p>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Inline SVG icons — minimal, no icon library dependency needed
// ─────────────────────────────────────────────────────────────────────────────

function LockIcon() {
  return (
    <svg fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2} className="w-4 h-4">
      <path strokeLinecap="round" strokeLinejoin="round" d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z" />
    </svg>
  );
}

function ScaleIcon() {
  return (
    <svg fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2} className="w-4 h-4">
      <path strokeLinecap="round" strokeLinejoin="round" d="M3 6l3 1m0 0l-3 9a5.002 5.002 0 006.001 0M6 7l3 9M6 7l6-2m6 2l3-1m-3 1l-3 9a5.002 5.002 0 006.001 0M18 7l3 9m-3-9l-6-2m0-2v2m0 16V5m0 16H9m3 0h3" />
    </svg>
  );
}

function ShieldIcon() {
  return (
    <svg fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2} className="w-4 h-4">
      <path strokeLinecap="round" strokeLinejoin="round" d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z" />
    </svg>
  );
}

function ClockIcon() {
  return (
    <svg fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2} className="w-4 h-4">
      <path strokeLinecap="round" strokeLinejoin="round" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
    </svg>
  );
}
