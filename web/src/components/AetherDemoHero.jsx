import React from "react";
import { motion } from "framer-motion";
import { Link } from "react-router-dom";
import { contactLink } from "../lib/contactLink.js";
import TerminalBlock from "./TerminalBlock.jsx";

const fadeUp = {
  hidden: { opacity: 0, y: 18 },
  show: (i = 0) => ({
    opacity: 1,
    y: 0,
    transition: {
      duration: 0.6,
      delay: 0.15 + i * 0.08,
      ease: [0.2, 0.8, 0.2, 1],
    },
  }),
};

const lines = [
  { kind: "prompt", text: "aetherctl --rotate ghost-protocol" },
  { kind: "log", text: "[boot] seeding entropy from quantum-tap :: 4.8 Mbps" },
  { kind: "log", text: "[boot] commitment vector generated :: SHA-256" },
  { kind: "log", text: "[net]  dropping stable endpoint 10.0.12.4" },
  { kind: "ok", text: "[ok]   new endpoint 10.0.12.7 :: ttl=24s signed" },
  { kind: "ok", text: "[ok]   rotation window active :: 142 peers acknowledged" },
  { kind: "prompt", text: "aetherctl --verify" },
  { kind: "ok", text: "[ok]   hardware attestation :: TPM 2.0 quote valid" },
  { kind: "ok", text: "[ok]   moving target armed" },
];

export default function AetherDemoHero({ imageSrc, imageAlt = "" }) {
  return (
    <section className="relative overflow-hidden border-b border-aether-border">
      <div className="absolute inset-0 -z-[1]">
        {imageSrc && (
          <img
            src={imageSrc}
            alt={imageAlt}
            className="h-full w-full object-cover opacity-40"
          />
        )}
        <div
          className="absolute inset-0"
          style={{
            background:
              "radial-gradient(ellipse 60% 60% at 50% 40%, rgba(0,212,255,0.12), transparent 60%), linear-gradient(180deg, rgba(4,5,7,0.4), rgba(4,5,7,0.95))",
          }}
        />
      </div>

      <div className="relative mx-auto grid max-w-[1400px] gap-16 px-[5%] pb-24 pt-28 lg:grid-cols-[1.1fr_1fr] lg:items-center lg:gap-20 lg:px-10 lg:pt-32">
        <motion.div initial="hidden" animate="show">
          <motion.p
            variants={fadeUp}
            custom={0}
            className="eyebrow mb-6 flex items-center gap-3"
          >
            <span className="inline-block h-1.5 w-1.5 rounded-full bg-aether-cyan" />
            LIVE DEMO // SANDBOX READY
          </motion.p>
          <motion.h1
            variants={fadeUp}
            custom={1}
            className="font-display text-[clamp(2.2rem,5vw,4.5rem)] font-semibold uppercase leading-[1] tracking-[-0.01em]"
          >
            See the moving target
            <br />
            <span className="text-aether-cyan">in motion.</span>
          </motion.h1>
          <motion.p
            variants={fadeUp}
            custom={2}
            className="mt-8 max-w-xl text-lg leading-relaxed text-aether-dim"
          >
            Watch Ghost Protocol rotate endpoints in under 30 seconds. Every
            rotation is hardware-attested, SHA-256 signed, and broadcast to an
            authenticated peer set. No fixed address. No predictable pattern.
          </motion.p>
          <motion.div
            variants={fadeUp}
            custom={3}
            className="mt-10 flex flex-wrap gap-4"
          >
            <Link
              to={contactLink({ intent: 'sales', product: 'aether_security', cta: 'demo_hero_sandbox' })}
              className="inline-flex items-center gap-3 border border-aether-cyan bg-aether-cyan/10 px-6 py-3.5 font-mono text-xs uppercase tracking-[0.2em] text-aether-text transition-all duration-200 hover:bg-aether-cyan hover:text-aether-bg"
              style={{ boxShadow: "0 0 28px rgba(0,212,255,0.22)" }}
            >
              Request a sandbox →
            </Link>
            <Link
              to="/documentation"
              className="inline-flex items-center gap-3 border border-aether-border px-6 py-3.5 font-mono text-xs uppercase tracking-[0.2em] text-aether-text transition-colors duration-200 hover:border-aether-cyan/60 hover:text-aether-cyan"
            >
              Read the protocol ↗
            </Link>
          </motion.div>
        </motion.div>

        <motion.div
          initial={{ opacity: 0, y: 24 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.5, duration: 0.7, ease: [0.2, 0.8, 0.2, 1] }}
        >
          <TerminalBlock title="aetherctl // live rotation" lines={lines} />
        </motion.div>
      </div>
    </section>
  );
}
