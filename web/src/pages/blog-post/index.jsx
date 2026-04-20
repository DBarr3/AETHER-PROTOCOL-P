import React from "react";
import { motion } from "framer-motion";
import { Link } from "react-router-dom";
import { contactLink } from "../../lib/contactLink.js";
import TerminalBlock from "../../components/TerminalBlock.jsx";

const fadeUp = {
  hidden: { opacity: 0, y: 18 },
  show: (i = 0) => ({
    opacity: 1,
    y: 0,
    transition: {
      duration: 0.6,
      delay: 0.1 + i * 0.08,
      ease: [0.2, 0.8, 0.2, 1],
    },
  }),
};

const proofLines = [
  { kind: "prompt", text: "aetherctl proof verify --bundle 2026-04-15.aep" },
  { kind: "log", text: "[proof] parsing commitment manifest" },
  { kind: "log", text: "[proof] 18,412 rotations :: window 00:00..23:59 UTC" },
  { kind: "log", text: "[proof] anchor: merkle root 0x9a…c4e1" },
  { kind: "ok", text: "[ok]    all SHA-256 receipts verified" },
  { kind: "ok", text: "[ok]    quantum-tap entropy signed by hardware root" },
  { kind: "ok", text: "[ok]    bundle integrity :: PASS" },
];

export default function Page() {
  return (
    <article>
      <section className="relative overflow-hidden border-b border-aether-border">
        <div
          className="absolute inset-0 -z-[1]"
          style={{
            background:
              "radial-gradient(ellipse 50% 40% at 25% 30%, rgba(0,212,255,0.12), transparent 60%), radial-gradient(ellipse 60% 60% at 80% 80%, rgba(232,64,64,0.07), transparent 60%)",
          }}
        />
        <div className="mx-auto max-w-3xl px-[5%] pb-12 pt-28 lg:pt-36">
          <motion.div
            initial="hidden"
            animate="show"
            variants={fadeUp}
            custom={0}
            className="mb-6 flex items-center gap-3 font-mono text-[11px] uppercase tracking-[0.2em] text-aether-cyan"
          >
            <Link to="/blog" className="hover:text-aether-text">
              ← Blog
            </Link>
            <span className="text-aether-border">·</span>
            <span className="text-aether-muted">Field Notes · Vol. 01</span>
            <span className="text-aether-border">·</span>
            <span className="text-aether-muted">7 min read</span>
          </motion.div>
          <motion.h1
            initial="hidden"
            animate="show"
            variants={fadeUp}
            custom={1}
            className="font-display text-[clamp(2rem,5vw,4rem)] font-semibold uppercase leading-[1] tracking-[-0.01em]"
          >
            What a moving target
            <br />
            <span className="text-aether-cyan">actually costs an attacker.</span>
          </motion.h1>
          <motion.p
            initial="hidden"
            animate="show"
            variants={fadeUp}
            custom={2}
            className="mt-8 text-aether-dim"
          >
            By <span className="text-aether-text">Iris Kaminski</span> — Head of
            Red Team · <span className="text-aether-muted">2026-04-15</span>
          </motion.p>
        </div>
      </section>

      <section className="relative">
        <div className="mx-auto max-w-3xl px-[5%] py-16 lg:py-24">
          <p className="text-lg leading-[1.85] text-aether-text">
            <span className="float-left mr-3 font-display text-[4.2rem] font-semibold leading-[0.85] text-aether-cyan">
              F
            </span>
            or twenty years, offense has had one advantage the defender could
            never take back: <em>time</em>. Scan the perimeter, map the ports,
            leave the shell in place — the fixed address is still the fixed
            address tomorrow morning. The attacker's patience is the defender's
            debt. Aether Security is, at its core, a rewrite of that equation.
          </p>

          <p className="mt-6 text-lg leading-[1.85] text-aether-dim">
            Ghost Protocol rotates endpoints on a cadence sourced from a
            quantum-tap, then broadcasts the new address to an authenticated
            peer set with a hardware-attested signature. The old endpoint is
            dropped. Not firewalled — <em>dropped</em>. A scan from four
            seconds ago is now a map of nothing.
          </p>

          <blockquote className="my-12 border-l-2 border-aether-cyan pl-6 font-mono text-xl uppercase leading-[1.4] tracking-[0.02em] text-aether-text">
            "The attacker's most valuable input — a stable address — stops
            being a valid input. Everything built on top of that assumption
            breaks at the same time."
          </blockquote>

          <h2 className="mt-12 font-display text-2xl font-semibold uppercase tracking-[-0.005em] text-aether-text">
            The receipts are the product.
          </h2>

          <p className="mt-4 text-lg leading-[1.85] text-aether-dim">
            The second thing Aether does is tell you it happened. Every
            rotation signs a receipt into a commitment ledger. Every receipt
            chains to a daily merkle anchor. The result is an audit surface
            your compliance team can read in one sitting:
          </p>

          <div className="my-10">
            <TerminalBlock title="aetherctl // proof verify" lines={proofLines} />
          </div>

          <h2 className="mt-12 font-display text-2xl font-semibold uppercase tracking-[-0.005em] text-aether-text">
            What it costs the adversary.
          </h2>

          <p className="mt-4 text-lg leading-[1.85] text-aether-dim">
            In our own red team engagements, time-to-shell against a
            Ghost-protected target rose from a median of{" "}
            <span className="text-aether-text">14 minutes</span> to an observed
            floor of{" "}
            <span className="text-aether-cyan">never</span>. Not once in six
            months of continuous adversarial simulation did a stable pivot
            survive a rotation window. The attack surface didn't get smaller;
            it stopped being coherent.
          </p>

          <p className="mt-6 text-lg leading-[1.85] text-aether-dim">
            That is the whole pitch. No new endpoint protection. No new agent
            on every box. A protocol that quietly makes the enemy's most
            valuable input — patience — worth zero.
          </p>

          <div className="mt-16 flex flex-wrap gap-4 border-t border-aether-border pt-10">
            <Link
              to={contactLink({ intent: 'general', product: 'site_wide', cta: 'blogpost_cta' })}
              className="inline-flex items-center gap-3 border border-aether-cyan bg-aether-cyan/10 px-6 py-3.5 font-mono text-xs uppercase tracking-[0.2em] text-aether-text transition-all duration-200 hover:bg-aether-cyan hover:text-aether-bg"
              style={{ boxShadow: "0 0 28px rgba(0,212,255,0.22)" }}
            >
              Talk to red team →
            </Link>
            <Link
              to="/blog"
              className="inline-flex items-center gap-3 border border-aether-border px-6 py-3.5 font-mono text-xs uppercase tracking-[0.2em] text-aether-text transition-colors duration-200 hover:border-aether-cyan/60 hover:text-aether-cyan"
            >
              More field notes ↗
            </Link>
          </div>
        </div>
      </section>
    </article>
  );
}
