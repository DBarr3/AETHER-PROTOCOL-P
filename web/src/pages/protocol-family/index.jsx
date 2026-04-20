import React from "react";
import { motion } from "framer-motion";
import { Link } from "react-router-dom";
import { contactLink } from "../../lib/contactLink.js";

/* ── animation presets ─────────────────────────────────── */
const fadeUp = {
  hidden: { opacity: 0, y: 22 },
  show: (i = 0) => ({
    opacity: 1,
    y: 0,
    transition: { duration: 0.6, delay: 0.1 + i * 0.08, ease: [0.2, 0.8, 0.2, 1] },
  }),
};

const stagger = {
  hidden: {},
  show: { transition: { staggerChildren: 0.12 } },
};

/* ── colour tokens ─────────────────────────────────────── */
const PROTO = {
  C: { accent: "#10b981", label: "COMMERCIAL READY", glow: "rgba(16,185,129,0.25)" },
  L: { accent: "#06b6d4", label: "SEALED \u00b7 PATENT PENDING", glow: "rgba(6,182,212,0.25)" },
  T: { accent: "#a78bfa", label: "COMMERCIAL READY", glow: "rgba(167,139,250,0.25)" },
};

/* ── reusable stat pill ────────────────────────────────── */
function StatPill({ children, color }) {
  return (
    <span
      className="inline-block border px-4 py-2 font-mono text-[11px] uppercase tracking-[0.14em]"
      style={{ borderColor: color, color }}
    >
      {children}
    </span>
  );
}

/* ── protocol overview card (Section 2) ────────────────── */
function ProtocolCard({ id, letter, tagline, subtitle, description, builtFor, accent, glowColor, label }) {
  return (
    <motion.div
      id={id}
      variants={fadeUp}
      className="group relative flex flex-col border border-aether-border bg-aether-surface/60 p-8 lg:p-10"
      style={{ borderTopColor: accent, borderTopWidth: 2 }}
    >
      {/* glow */}
      <div
        className="pointer-events-none absolute inset-0 -z-[1] opacity-0 transition-opacity duration-500 group-hover:opacity-100"
        style={{ background: `radial-gradient(ellipse 70% 60% at 50% 0%, ${glowColor}, transparent 70%)` }}
      />

      {/* badge */}
      <span
        className="mb-6 inline-block w-fit border px-3 py-1 font-mono text-[10px] uppercase tracking-[0.18em]"
        style={{ borderColor: accent, color: accent }}
      >
        {label}
      </span>

      <h3
        className="font-display text-2xl font-semibold uppercase tracking-tight lg:text-3xl"
        style={{ color: accent }}
      >
        Protocol-{letter}
      </h3>
      <p className="mt-2 font-mono text-sm uppercase tracking-[0.08em] text-aether-text">
        {tagline}
      </p>
      <p className="mt-1 text-sm italic text-aether-dim">{subtitle}</p>
      <p className="mt-6 flex-1 text-[15px] leading-relaxed text-aether-dim">
        {description}
      </p>

      <div className="mt-8">
        <p className="mb-3 font-mono text-[11px] uppercase tracking-[0.16em] text-aether-muted">
          Built for
        </p>
        <ul className="space-y-1.5">
          {builtFor.map((item) => (
            <li key={item} className="flex items-start gap-2 text-[13px] text-aether-dim">
              <span className="mt-1.5 inline-block h-1 w-1 shrink-0 rounded-full" style={{ backgroundColor: accent }} />
              {item}
            </li>
          ))}
        </ul>
      </div>

      <Link
        to={contactLink({ intent: 'sales', product: 'aether_protocol', cta: 'protocol_card_access' })}
        className="mt-8 inline-flex w-fit items-center gap-2 border px-6 py-3 font-mono text-[12px] uppercase tracking-[0.14em] transition-colors hover:bg-white/5"
        style={{ borderColor: accent, color: accent }}
      >
        Contact for access
        <span aria-hidden="true">&rarr;</span>
      </Link>
    </motion.div>
  );
}

/* ── deep-dive numbered subsection ─────────────────────── */
function DeepDiveBlock({ num, title, children, accent }) {
  return (
    <div className="border-l-2 py-1 pl-6 lg:pl-8" style={{ borderColor: accent }}>
      <p className="mb-2 font-mono text-[11px] uppercase tracking-[0.16em] text-aether-muted">
        {String(num).padStart(2, "0")}
      </p>
      <h4 className="mb-3 font-display text-lg font-semibold uppercase tracking-tight text-aether-text lg:text-xl">
        {title}
      </h4>
      <div className="space-y-3 text-[15px] leading-relaxed text-aether-dim">{children}</div>
    </div>
  );
}

/* ── deep-dive section wrapper ─────────────────────────── */
function DeepDive({ id, heading, accent, stats, children }) {
  return (
    <motion.section
      id={id}
      initial="hidden"
      whileInView="show"
      viewport={{ once: true, amount: 0.15 }}
      variants={stagger}
      className="border-b border-aether-border"
    >
      <div className="mx-auto max-w-[1400px] px-[5%] py-20 lg:px-10 lg:py-28">
        <motion.h3
          variants={fadeUp}
          className="mb-14 max-w-4xl font-display text-[clamp(1.4rem,3vw,2.4rem)] font-semibold uppercase leading-[1.15] tracking-tight text-aether-text"
        >
          {heading}
        </motion.h3>

        <motion.div variants={fadeUp} className="grid gap-12 lg:grid-cols-3 lg:gap-10">
          {children}
        </motion.div>

        {/* stat pills */}
        <motion.div variants={fadeUp} className="mt-14 flex flex-wrap gap-3">
          {stats.map((s) => (
            <StatPill key={s} color={accent}>
              {s}
            </StatPill>
          ))}
        </motion.div>
      </div>
    </motion.section>
  );
}

/* ================================================================
   PAGE
   ================================================================ */
export default function Page() {
  return (
    <div className="bg-aether-bg text-aether-text">
      {/* ── SECTION 1 : Hero ──────────────────────────────── */}
      <section className="relative overflow-hidden border-b border-aether-border">
        <div
          className="absolute inset-0 -z-[1]"
          style={{
            background:
              "radial-gradient(ellipse 60% 50% at 20% 20%, rgba(6,182,212,0.12), transparent 60%), radial-gradient(ellipse 60% 60% at 80% 80%, rgba(167,139,250,0.08), transparent 60%)",
          }}
        />
        <div className="mx-auto max-w-[1400px] px-[5%] pb-16 pt-28 lg:px-10 lg:pb-24 lg:pt-36">
          <motion.p
            initial="hidden"
            animate="show"
            variants={fadeUp}
            custom={0}
            className="mb-6 flex items-center gap-3 font-mono text-[12px] uppercase tracking-[0.16em] text-aether-muted"
          >
            <span
              className="inline-block h-1.5 w-1.5 rounded-full bg-aether-cyan"
              style={{ boxShadow: "0 0 10px rgba(0,212,255,0.9)" }}
            />
            AETHER // PROTOCOL FAMILY
          </motion.p>

          <motion.h1
            initial="hidden"
            animate="show"
            variants={fadeUp}
            custom={1}
            className="max-w-5xl font-display text-[clamp(2rem,5vw,4.2rem)] font-semibold uppercase leading-[1.05] tracking-[-0.01em] text-aether-text"
          >
            The Protocol Family
          </motion.h1>

          <motion.p
            initial="hidden"
            animate="show"
            variants={fadeUp}
            custom={2}
            className="mt-6 max-w-3xl text-lg leading-relaxed text-aether-dim"
          >
            One commitment chain architecture. Three entropy sources. Every
            security maturity level.
          </motion.p>

          <motion.div
            initial="hidden"
            animate="show"
            variants={fadeUp}
            custom={3}
            className="mt-10 flex flex-wrap gap-4"
          >
            <Link
              to={contactLink({ intent: 'sales', product: 'aether_protocol', cta: 'protocol_hero_briefing' })}
              className="inline-flex items-center gap-2 border border-aether-cyan bg-aether-cyan/10 px-7 py-3 font-mono text-[12px] uppercase tracking-[0.14em] text-aether-cyan transition-colors hover:bg-aether-cyan/20"
            >
              Request briefing
            </Link>
            <a
              href="#protocol-c"
              className="inline-flex items-center gap-2 border border-aether-border px-7 py-3 font-mono text-[12px] uppercase tracking-[0.14em] text-aether-dim transition-colors hover:border-aether-dim hover:text-aether-text"
            >
              Explore protocols &darr;
            </a>
          </motion.div>
        </div>
      </section>

      {/* ── SECTION 2 : Three Protocol Cards ──────────────── */}
      <section className="border-b border-aether-border">
        <div className="mx-auto max-w-[1400px] px-[5%] py-20 lg:px-10 lg:py-28">
          <motion.div
            initial="hidden"
            whileInView="show"
            viewport={{ once: true, amount: 0.1 }}
            variants={stagger}
            className="grid gap-8 lg:grid-cols-3"
          >
            <ProtocolCard
              id="protocol-c"
              letter="C"
              tagline="Zero-Cost Commitment Infrastructure"
              subtitle="Every audit trail sealed. Every decision provable. Zero infrastructure cost."
              description="Protocol-C creates tamper-evident commitments — SHA-256 chain, RFC 3161 trusted timestamp, ephemeral key destroyed after signing. Pure Python, zero dependencies, runs on any CPU. No external accounts. No per-call fees."
              builtFor={[
                "SaaS platforms at scale",
                "AI companies committing model outputs",
                "Financial systems requiring trade audit trails",
                "Any team that needs tamper-proof records at volume",
              ]}
              accent={PROTO.C.accent}
              glowColor={PROTO.C.glow}
              label={PROTO.C.label}
            />

            <ProtocolCard
              id="protocol-l"
              letter="L"
              tagline="Quantum-Authenticated Commitments"
              subtitle="Entropy sourced from quantum hardware. Physically unpredictable. Legally defensible."
              description="Protocol-L seeds every signing key from IBM Fez — a 156-qubit quantum circuit. Quantum measurement is non-deterministic by physical law. Three-phase lifecycle, independent quantum seed per phase, ephemeral keys destroyed after use."
              builtFor={[
                "Cybersecurity firms",
                "Legal/compliance teams",
                "Financial institutions under SEC/MiFID II/DORA",
                "Environments where classical entropy trust is insufficient",
              ]}
              accent={PROTO.L.accent}
              glowColor={PROTO.L.glow}
              label={PROTO.L.label}
            />

            <ProtocolCard
              id="protocol-t"
              letter="T"
              tagline="Execution Context Attestation"
              subtitle="Cryptographic proof that your code ran where you say it ran — and no one touched it."
              description="Protocol-T binds every commitment to a hardware attestation quote from Intel SGX or AMD SEV-SNP. MRENCLAVE is SHA-256 of exact binary. Host OS/cloud provider cannot observe or modify the enclave."
              builtFor={[
                "Healthcare AI (HIPAA/FDA)",
                "Financial model governance (OCC/SEC)",
                "AI labs proving safety evaluations",
                "Confidential compute",
              ]}
              accent={PROTO.T.accent}
              glowColor={PROTO.T.glow}
              label={PROTO.T.label}
            />
          </motion.div>
        </div>
      </section>

      {/* ── SECTION 3 : Protocol-C Deep Dive ──────────────── */}
      <DeepDive
        id="deep-c"
        heading="Protocol-C: Commitment Infrastructure at Zero Cost"
        accent={PROTO.C.accent}
        stats={["ZERO QPU COST", "OS KERNEL ENTROPY", "SHA-256 + RFC 3161", "41 TESTS"]}
      >
        <DeepDiveBlock num={1} title="The Economics: Why $0 Matters at Scale" accent={PROTO.C.accent}>
          <p>
            IBM QPU time costs roughly $100/min. At 10,000 users generating
            commitments, that translates to ~$3,300/month for operations that
            don&apos;t need quantum entropy. Protocol-C eliminates that cost
            entirely by sourcing entropy from the OS kernel — same chain
            architecture, zero QPU overhead.
          </p>
        </DeepDiveBlock>

        <DeepDiveBlock num={2} title="What It Guarantees: Same Chain, Different Source" accent={PROTO.C.accent}>
          <p>
            SHA-256 commitment chain. RFC 3161 trusted timestamps. Ephemeral key
            destruction after every signing operation. The output is
            computationally indistinguishable from quantum-seeded commitments —
            identical chain format, identical verification path.
          </p>
        </DeepDiveBlock>

        <DeepDiveBlock num={3} title="Who Uses It" accent={PROTO.C.accent}>
          <p>
            SaaS platforms, AI companies committing model outputs, financial
            institutions operating at scale. One environment variable switches
            any Protocol-C deployment to Protocol-L when quantum assurance
            becomes necessary.
          </p>
        </DeepDiveBlock>
      </DeepDive>

      {/* ── SECTION 4 : Protocol-L Deep Dive ──────────────── */}
      <DeepDive
        id="deep-l"
        heading="Protocol-L: Cryptographic Accountability for Autonomous AI"
        accent={PROTO.L.accent}
        stats={[
          "COMMIT\u2192EXECUTE\u2192SETTLE",
          "secp256k1 + RFC 6979",
          "RFC 3161 / DigiCert",
          "PATENT FILED",
        ]}
      >
        <DeepDiveBlock num={1} title="The Lifecycle: Commit \u2192 Execute \u2192 Settle" accent={PROTO.L.accent}>
          <p>
            Three independently signed phases. Each phase receives its own
            ephemeral secp256k1 key, seeded from a unique quantum measurement.
            SHA-256 binding chains the phases together — tampering with any
            phase invalidates the entire commitment.
          </p>
        </DeepDiveBlock>

        <DeepDiveBlock num={2} title="Quantum Entropy Foundation" accent={PROTO.L.accent}>
          <p>
            156-qubit IBM circuit (Fez). Quantum measurement is non-deterministic
            by physical law — no seed, no state, no replay. Ephemeral keys live
            approximately one hour. 168x safety margin against Shor&apos;s
            algorithm at current qubit counts.
          </p>
        </DeepDiveBlock>

        <DeepDiveBlock num={3} title="Dispute Resolution: Evidence, Not Logs" accent={PROTO.L.accent}>
          <p>
            Exportable proof packages for regulators and counterparties.
            Structured for DORA, SEC, MiFID II, and FCA compliance frameworks.
            Every commitment is independently verifiable — no trust in the
            issuing party required.
          </p>
        </DeepDiveBlock>
      </DeepDive>

      {/* ── SECTION 5 : Protocol-T Deep Dive ──────────────── */}
      <DeepDive
        id="deep-t"
        heading="Protocol-T: Prove What Ran, Not Just What Was Signed"
        accent={PROTO.T.accent}
        stats={[
          "INTEL SGX / AMD SEV-SNP",
          "MRENCLAVE BINDING",
          "REMOTE ATTESTATION",
          "76 TESTS",
        ]}
      >
        <DeepDiveBlock num={1} title="The Problem" accent={PROTO.T.accent}>
          <p>
            There is a gap in every AI audit trail. Logs are circumstantial —
            they cannot prove which model version ran, whether the pipeline was
            intact, or if intermediate data was modified. Signatures prove intent,
            not execution context.
          </p>
        </DeepDiveBlock>

        <DeepDiveBlock num={2} title="How Attestation Works" accent={PROTO.T.accent}>
          <p>
            MRENCLAVE — the SHA-256 measurement of the exact binary loaded into
            the enclave. The enclave cannot be observed or modified by the host
            OS, hypervisor, or cloud provider. Attestation quotes are verifiable
            via Intel or AMD root certificates.
          </p>
        </DeepDiveBlock>

        <DeepDiveBlock num={3} title="Who Needs It" accent={PROTO.T.accent}>
          <p>
            Healthcare AI under HIPAA/FDA. Financial institutions governed by
            OCC/SEC. AI labs required to prove safety evaluations ran unmodified.
            Any confidential compute environment where execution integrity is
            non-negotiable.
          </p>
        </DeepDiveBlock>
      </DeepDive>

      {/* ── SECTION 6 : Footer Note ───────────────────────── */}
      <section className="border-b border-aether-border">
        <div className="mx-auto max-w-[1400px] px-[5%] py-16 lg:px-10 lg:py-20">
          <motion.div
            initial="hidden"
            whileInView="show"
            viewport={{ once: true, amount: 0.3 }}
            variants={fadeUp}
            className="text-center"
          >
            <p className="mx-auto max-w-3xl font-mono text-[13px] leading-relaxed tracking-[0.06em] text-aether-dim">
              All three variants share one commitment chain architecture.
            </p>
            <p className="mt-3 font-mono text-[12px] uppercase tracking-[0.14em] text-aether-muted">
              SHA-256 &middot; RFC 3161 &middot; Perfect Forward Secrecy &middot; Patent Pending
            </p>
            <div className="mx-auto mt-8 flex justify-center gap-4">
              <Link
                to={contactLink({ intent: 'sales', product: 'aether_protocol', cta: 'protocol_footer_access' })}
                className="inline-flex items-center gap-2 border border-aether-cyan bg-aether-cyan/10 px-7 py-3 font-mono text-[12px] uppercase tracking-[0.14em] text-aether-cyan transition-colors hover:bg-aether-cyan/20"
              >
                Contact for access
              </Link>
            </div>
          </motion.div>
        </div>
      </section>
    </div>
  );
}
