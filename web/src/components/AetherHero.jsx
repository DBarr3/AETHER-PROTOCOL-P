import React from "react";
import { motion } from "framer-motion";
import { Link } from "react-router-dom";

const fadeUp = {
  hidden: { opacity: 0, y: 18 },
  show: (i = 0) => ({
    opacity: 1,
    y: 0,
    transition: { duration: 0.6, delay: 0.15 + i * 0.08, ease: [0.2, 0.8, 0.2, 1] },
  }),
};

export default function AetherHero({
  eyebrow = "AETHER // GHOST PROTOCOL v2.1",
  heading,
  sub,
  primary,
  secondary,
  imageSrc,
  imageAlt = "",
}) {
  return (
    <section className="relative overflow-hidden border-b border-aether-border">
      {/* Background image or CSS-only fallback */}
      <div className="absolute inset-0 -z-[1]">
        {imageSrc ? (
          <img
            src={imageSrc}
            alt={imageAlt}
            className="h-full w-full object-cover opacity-60"
          />
        ) : (
          <div
            className="h-full w-full"
            style={{
              background:
                "radial-gradient(ellipse 80% 60% at 30% 30%, rgba(0,212,255,0.18), transparent 60%), radial-gradient(ellipse 70% 50% at 80% 80%, rgba(212,160,23,0.10), transparent 60%)",
            }}
          />
        )}
        <div
          className="absolute inset-0"
          style={{
            background:
              "linear-gradient(180deg, rgba(4,5,7,0.2) 0%, rgba(4,5,7,0.6) 40%, rgba(4,5,7,0.92) 100%)",
          }}
        />
      </div>

      <div className="relative mx-auto flex min-h-[88vh] max-w-[1400px] flex-col justify-end px-[5%] pb-16 pt-28 lg:min-h-[92vh] lg:px-10 lg:pb-24 lg:pt-32">
        <motion.div
          initial="hidden"
          animate="show"
          className="max-w-4xl"
        >
          <motion.p
            custom={0}
            variants={fadeUp}
            className="eyebrow mb-8 flex items-center gap-3"
          >
            <span
              className="inline-block h-1.5 w-1.5 rounded-full bg-aether-green"
              style={{ boxShadow: "0 0 10px rgba(0,255,136,0.9)" }}
            />
            {eyebrow}
          </motion.p>

          <motion.h1
            custom={1}
            variants={fadeUp}
            className="font-display text-[clamp(2.5rem,6.4vw,5.5rem)] font-semibold uppercase leading-[0.95] tracking-[-0.01em] text-aether-text"
          >
            {heading}
          </motion.h1>

          <motion.p
            custom={3}
            variants={fadeUp}
            className="mt-8 max-w-2xl font-sans text-lg leading-relaxed text-aether-dim md:text-xl"
          >
            {sub}
          </motion.p>

          <motion.div
            custom={4}
            variants={fadeUp}
            className="mt-12 flex flex-wrap items-center gap-4"
          >
            {primary && (
              <Link
                to={primary.to}
                className="group relative inline-flex items-center gap-3 border border-aether-cyan bg-aether-cyan/10 px-7 py-4 font-mono text-xs uppercase tracking-[0.2em] text-aether-text transition-all duration-200 hover:bg-aether-cyan hover:text-aether-bg"
                style={{ boxShadow: "0 0 32px rgba(0,212,255,0.25)" }}
              >
                {primary.label}
                <span>→</span>
              </Link>
            )}
            {secondary && (
              <Link
                to={secondary.to}
                className="inline-flex items-center gap-3 border border-aether-border px-7 py-4 font-mono text-xs uppercase tracking-[0.2em] text-aether-text transition-colors duration-200 hover:border-aether-cyan/60 hover:text-aether-cyan"
              >
                {secondary.label}
                <span>↗</span>
              </Link>
            )}
          </motion.div>

          <motion.div
            custom={5}
            variants={fadeUp}
            className="mt-16 grid grid-cols-3 gap-6 border-t border-aether-border pt-8 font-mono text-[11px] uppercase tracking-[0.18em] text-aether-muted sm:max-w-xl"
          >
            <div>
              <div className="text-aether-cyan">0ms</div>
              <div className="mt-1">fixed endpoints</div>
            </div>
            <div>
              <div className="text-aether-cyan">∞</div>
              <div className="mt-1">rotation entropy</div>
            </div>
            <div>
              <div className="text-aether-cyan">SHA-256</div>
              <div className="mt-1">signed outputs</div>
            </div>
          </motion.div>
        </motion.div>
      </div>

      {/* Scanline decoration */}
      <div
        className="pointer-events-none absolute inset-x-0 bottom-0 h-[1px]"
        style={{
          background:
            "linear-gradient(90deg, transparent, rgba(0,212,255,0.6), transparent)",
        }}
      />
    </section>
  );
}
