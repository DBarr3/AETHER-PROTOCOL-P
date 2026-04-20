import React, { useState } from "react";
import { motion } from "framer-motion";
import { Link } from "react-router-dom";
import { contactLink } from "../../lib/contactLink.js";

const fadeUp = {
  hidden: { opacity: 0, y: 30 },
  visible: (i = 0) => ({
    opacity: 1,
    y: 0,
    transition: { duration: 0.6, delay: i * 0.12, ease: "easeOut" },
  }),
};

const CheckIcon = () => (
  <svg
    className="w-4 h-4 text-aether-cyan shrink-0 mt-0.5"
    fill="none"
    viewBox="0 0 24 24"
    stroke="currentColor"
    strokeWidth={2}
  >
    <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
  </svg>
);

function TierCard({ name, price, priceSub, description, features, cta, ctaLink, recommended, accent = "cyan", sla }) {
  const isCyan = accent === "cyan";
  const borderClass = recommended
    ? isCyan
      ? "border-aether-cyan/40 shadow-glow-cyan"
      : "border-red-500/40 shadow-[0_0_24px_rgba(239,68,68,0.3)]"
    : "border-aether-border";
  const badgeBg = isCyan ? "bg-aether-cyan/10 text-aether-cyan" : "bg-red-500/10 text-red-400";
  const btnClass = recommended
    ? isCyan
      ? "bg-aether-cyan text-aether-bg hover:bg-aether-cyan/90"
      : "bg-red-500 text-white hover:bg-red-600"
    : isCyan
    ? "border border-aether-cyan/40 text-aether-cyan hover:bg-aether-cyan/10"
    : "border border-red-500/40 text-red-400 hover:bg-red-500/10";

  return (
    <motion.div
      variants={fadeUp}
      initial="hidden"
      whileInView="visible"
      viewport={{ once: true, margin: "-40px" }}
      className={`relative flex flex-col rounded-lg border ${borderClass} bg-aether-surface p-6 md:p-8`}
    >
      {recommended && (
        <span className={`absolute -top-3 left-6 px-3 py-0.5 rounded text-[10px] font-mono uppercase tracking-brand ${badgeBg}`}>
          Recommended
        </span>
      )}
      <h3 className="font-mono text-xs uppercase tracking-brand text-aether-dim mb-2">{name}</h3>
      <div className="mb-1">
        <span className="text-3xl md:text-4xl font-bold text-aether-text font-mono">{price}</span>
        {priceSub && <span className="text-aether-muted text-sm ml-1 font-mono">{priceSub}</span>}
      </div>
      <p className="text-aether-dim text-sm leading-relaxed mb-6">{description}</p>
      {sla && (
        <p className="text-xs font-mono text-aether-muted mb-4 border-t border-aether-border pt-3">
          SLA: <span className="text-aether-text">{sla}</span>
        </p>
      )}
      <ul className="space-y-2.5 mb-8 flex-1">
        {features.map((f, i) => (
          <li key={i} className="flex items-start gap-2 text-sm text-aether-dim">
            <CheckIcon />
            <span>{f}</span>
          </li>
        ))}
      </ul>
      <Link
        to={ctaLink || "/contact"}
        className={`block text-center font-mono text-xs uppercase tracking-brand py-3 px-6 rounded transition-colors ${btnClass}`}
      >
        {cta}
      </Link>
    </motion.div>
  );
}

function Toggle({ annual, setAnnual }) {
  return (
    <div className="flex items-center justify-center gap-4 mb-12">
      <span className={`text-sm font-mono ${!annual ? "text-aether-text" : "text-aether-muted"}`}>Monthly</span>
      <button
        onClick={() => setAnnual(!annual)}
        className="relative w-14 h-7 rounded-full bg-aether-raised border border-aether-border transition-colors"
        aria-label="Toggle annual pricing"
      >
        <motion.div
          className="absolute top-0.5 w-6 h-6 rounded-full bg-aether-cyan"
          animate={{ left: annual ? "calc(100% - 26px)" : "2px" }}
          transition={{ type: "spring", stiffness: 500, damping: 30 }}
        />
      </button>
      <span className={`text-sm font-mono ${annual ? "text-aether-text" : "text-aether-muted"}`}>
        Annual <span className="text-aether-cyan text-xs">(save 17%)</span>
      </span>
    </div>
  );
}

export default function Page() {
  const [annual, setAnnual] = useState(false);

  const shieldPrice = annual ? "$248" : "$299";
  const shieldSub = annual ? "/mo billed annually" : "/month";
  const fortressPrice = annual ? "$2,075" : "$2,500";
  const fortressSub = annual ? "/mo billed annually" : "/month";
  const retainerPrice = annual ? "$7,055" : "$8,500";
  const retainerSub = annual ? "/mo billed annually" : "/month";

  return (
    <div className="bg-aether-bg min-h-screen">
      {/* ───── HERO ───── */}
      <section className="relative pt-32 pb-16 px-6 text-center overflow-hidden">
        <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_top,rgba(0,212,255,0.06)_0%,transparent_60%)]" />
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.7 }}
          className="relative max-w-3xl mx-auto"
        >
          <p className="font-mono text-xs uppercase tracking-brand text-aether-cyan mb-4">
            AETHER // PRICING
          </p>
          <h1 className="text-4xl md:text-5xl lg:text-6xl font-bold text-aether-text font-mono leading-tight mb-6">
            Defense &amp; Offense<br />
            <span className="text-aether-cyan">Pricing.</span>
          </h1>
          <p className="text-aether-dim max-w-xl mx-auto leading-relaxed">
            Every tier ships the full Protocol Family, hardware attestation, quantum-tap entropy, and a signed receipt for every rotation. Choose your posture below.
          </p>
        </motion.div>
      </section>

      {/* ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
         SECTION 1 — DEFENSE PRICING
      ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ */}
      <section className="px-6 pb-24">
        <div className="max-w-6xl mx-auto">
          <motion.div
            variants={fadeUp}
            initial="hidden"
            whileInView="visible"
            viewport={{ once: true }}
            className="text-center mb-4"
          >
            <h2 className="font-mono text-2xl md:text-3xl font-bold text-aether-text uppercase tracking-brand">
              Choose Your Defense Posture
            </h2>
          </motion.div>

          <Toggle annual={annual} setAnnual={setAnnual} />

          <div className="grid gap-6 md:grid-cols-3">
            <TierCard
              name="Aether Shield"
              price={shieldPrice}
              priceSub={shieldSub}
              description="For developers and independent traders who need institutional-grade protection."
              features={[
                "Ghost Protocol MTD",
                "3,000,000+ states",
                "Shared 3-VPS infra",
                "Quantum tarpit DDoS",
                "Pooled IBM session",
              ]}
              sla="Best effort"
              cta="Get Started"
              ctaLink={contactLink({ intent: 'sales', product: 'aether_security', cta: 'pricing_shield' })}
            />
            <TierCard
              name="Aether Fortress"
              price={fortressPrice}
              priceSub={fortressSub}
              description="For prop firms and RIAs that require dedicated isolated infrastructure."
              features={[
                "Everything in Shield",
                "Dedicated VPS infra",
                "Dedicated IBM session",
                "99.9% uptime SLA",
                "Monthly security review",
              ]}
              sla="99.9% guaranteed"
              cta="Book Onboarding"
              ctaLink={contactLink({ intent: 'sales', product: 'aether_security', cta: 'pricing_fortress' })}
              recommended
            />
            <TierCard
              name="Aether Enterprise"
              price="$35k+"
              priceSub="one-time"
              description="The complete Aether defense stack. Full source access."
              features={[
                "Full source license",
                "AETHER PROTOCOL source (C/L/T variants + dispute reports)",
                "AETHER-SCRAMBLER Ghost Protocol v2.1",
                "On-premise support",
                "Dedicated manager",
                "White-label rights",
              ]}
              sla="Custom per contract"
              cta="Contact Sales"
              ctaLink={contactLink({ intent: 'sales', product: 'aether_security', cta: 'pricing_enterprise_defense' })}
            />
          </div>

          {/* RED TEAM callout */}
          <motion.p
            variants={fadeUp}
            initial="hidden"
            whileInView="visible"
            viewport={{ once: true }}
            className="text-center text-xs font-mono text-red-400 mt-6"
          >
            RED TEAM: Predator engagements available separately under Offense Posture pricing below.
          </motion.p>

          {/* Defense footnote */}
          <motion.div
            variants={fadeUp}
            initial="hidden"
            whileInView="visible"
            viewport={{ once: true }}
            className="mt-10 border border-aether-border rounded-lg bg-aether-surface/60 p-6 max-w-4xl mx-auto"
          >
            <p className="text-xs text-aether-muted leading-relaxed font-mono">
              All tiers include provisional patent protection. IBM Job ID{" "}
              <span className="text-aether-dim">d6sonabbjfas73fonq3g</span> available for technical verification.
              First Fortress client: 3 months at $500/mo with case study agreement.
            </p>
          </motion.div>
        </div>
      </section>

      {/* ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
         SECTION 2 — OFFENSE PRICING (PREDATOR)
      ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ */}
      <section className="px-6 pb-32">
        <div className="max-w-6xl mx-auto">
          {/* Divider */}
          <div className="flex items-center gap-4 mb-16">
            <div className="flex-1 h-px bg-gradient-to-r from-transparent via-red-500/30 to-transparent" />
            <span className="font-mono text-[10px] uppercase tracking-brand text-red-400">
              Offense Posture
            </span>
            <div className="flex-1 h-px bg-gradient-to-r from-transparent via-red-500/30 to-transparent" />
          </div>

          <motion.div
            variants={fadeUp}
            initial="hidden"
            whileInView="visible"
            viewport={{ once: true }}
            className="text-center mb-4"
          >
            <h2 className="font-mono text-2xl md:text-3xl font-bold text-red-400 uppercase tracking-brand">
              Choose Your Offense Posture
            </h2>
          </motion.div>

          <motion.p
            variants={fadeUp}
            initial="hidden"
            whileInView="visible"
            viewport={{ once: true }}
            className="text-center text-sm text-aether-dim max-w-2xl mx-auto mb-12 italic leading-relaxed"
          >
            &ldquo;Predator doesn&rsquo;t just find attack paths&nbsp;&mdash; it selects them through a patented quantum circuit
            that produces a non-deterministic attack sequence no defender can anticipate.&rdquo;
          </motion.p>

          <div className="grid gap-6 md:grid-cols-3">
            <TierCard
              accent="red"
              name="Single Engagement"
              price="$4,500"
              description="One full Predator pentest session. Ideal for first engagements, compliance snapshots, or scoped red team exercises."
              features={[
                "350 MITRE ATT&CK chain sweep",
                "40-qubit ZZFeatureMap selection",
                "Q\u2192C\u2192Q convergence report",
                "Quantum-verified findings doc",
                "1B+ state surface mapping",
                "Patent-backed methodology",
              ]}
              cta="Get Started"
              ctaLink={contactLink({ intent: 'sales', product: 'aether_security', cta: 'pricing_predator_single' })}
            />
            <TierCard
              accent="red"
              name="Monthly Retainer"
              price={retainerPrice}
              priceSub={retainerSub}
              description="Continuous offensive coverage for organizations running active red team programs or ongoing compliance cycles."
              features={[
                "Everything in Single Engagement",
                "Up to 4 engagements/month",
                "Priority IBM session scheduling",
                "Monthly threat surface report",
                "Dedicated quantum session",
                "Chain update notifications",
              ]}
              cta="Book Onboarding"
              ctaLink={contactLink({ intent: 'sales', product: 'aether_security', cta: 'pricing_predator_retainer' })}
              recommended
            />
            <TierCard
              accent="red"
              name="Enterprise SOW"
              price="Custom"
              description="Embedded red team operations, custom chain development, white-label deployment."
              features={[
                "Everything in Retainer",
                "Custom MITRE chain development",
                "Embedded red team operations",
                "White-label rights",
                "On-premise deployment",
                "Patent-backed methodology license",
              ]}
              cta="Contact Sales"
              ctaLink={contactLink({ intent: 'sales', product: 'aether_security', cta: 'pricing_predator_enterprise' })}
            />
          </div>

          {/* Offense footnote */}
          <motion.div
            variants={fadeUp}
            initial="hidden"
            whileInView="visible"
            viewport={{ once: true }}
            className="mt-10 border border-red-500/20 rounded-lg bg-aether-surface/60 p-6 max-w-4xl mx-auto"
          >
            <p className="text-xs text-aether-muted leading-relaxed font-mono text-center">
              All engagements include provisional patent protection coverage &middot; IBM Job ID provided on every session
              &middot; Publicly verifiable &middot; Q&rarr;C&rarr;Q methodology &middot; 350 MITRE ATT&amp;CK chains
              &middot; 40-qubit ZZFeatureMap &middot; 1,000,000,000+ quantum states
            </p>
          </motion.div>
        </div>
      </section>
    </div>
  );
}
