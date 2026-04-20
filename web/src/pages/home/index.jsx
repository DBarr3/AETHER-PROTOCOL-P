import React, { useState, useEffect, useRef } from "react";
import { Link } from "react-router-dom";
import { motion, useInView } from "framer-motion";
import { contactLink } from "../../lib/contactLink.js";

/* ───────────────────────── animation helpers ───────────────────────── */
const fadeUp = {
  hidden: { opacity: 0, y: 22 },
  show: (i = 0) => ({
    opacity: 1,
    y: 0,
    transition: { duration: 0.55, delay: i * 0.08, ease: [0.2, 0.8, 0.2, 1] },
  }),
};

function Section({ children, className = "", id }) {
  const ref = useRef(null);
  const inView = useInView(ref, { once: true, margin: "-60px" });
  return (
    <motion.section
      ref={ref}
      id={id}
      initial="hidden"
      animate={inView ? "show" : "hidden"}
      className={className}
    >
      {children}
    </motion.section>
  );
}

function SectionHeading({ eyebrow, title, sub }) {
  return (
    <div className="mb-12 max-w-3xl">
      {eyebrow && (
        <motion.p variants={fadeUp} custom={0} className="eyebrow mb-4 flex items-center gap-2">
          <span className="inline-block h-1.5 w-1.5 rounded-full bg-aether-green" style={{ boxShadow: "0 0 8px rgba(0,255,136,0.8)" }} />
          {eyebrow}
        </motion.p>
      )}
      <motion.h2 variants={fadeUp} custom={1} className="font-display text-[clamp(1.8rem,4vw,3rem)] font-semibold uppercase leading-[1.05] tracking-tight text-aether-text">
        {title}
      </motion.h2>
      {sub && (
        <motion.p variants={fadeUp} custom={2} className="mt-4 max-w-2xl text-base leading-relaxed text-aether-dim md:text-lg">
          {sub}
        </motion.p>
      )}
    </div>
  );
}

/* card wrapper */
function Card({ children, className = "", glow = false }) {
  return (
    <div
      className={`rounded border border-aether-border bg-aether-surface p-6 ${glow ? "shadow-glow-cyan" : ""} ${className}`}
    >
      {children}
    </div>
  );
}

/* label badge */
function Badge({ children, variant = "cyan" }) {
  const colors = {
    cyan: "border-aether-cyan/40 text-aether-cyan bg-aether-cyan/10",
    gold: "border-aether-gold/40 text-aether-gold bg-aether-gold/10",
    red: "border-aether-red/40 text-aether-red bg-aether-red/10",
    green: "border-aether-green/40 text-aether-green bg-aether-green/10",
    muted: "border-aether-border text-aether-dim bg-aether-raised",
  };
  return (
    <span className={`inline-block rounded-sm border px-2 py-0.5 font-mono text-[10px] uppercase tracking-[0.18em] ${colors[variant] || colors.cyan}`}>
      {children}
    </span>
  );
}

/* stat row inside cards */
function StatRow({ label, value }) {
  return (
    <div className="flex items-baseline justify-between border-b border-aether-border/40 py-2 font-mono text-xs">
      <span className="uppercase tracking-wider text-aether-muted">{label}</span>
      <span className="text-aether-text">{value}</span>
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════════════
   HOME PAGE
   ═══════════════════════════════════════════════════════════════════════ */
export default function Page() {
  const [annual, setAnnual] = useState(false);
  const [protocolVariant, setProtocolVariant] = useState("L");

  return (
    <div>
      {/* ─────────────── 1 · HERO ─────────────── */}
      <section className="relative overflow-hidden border-b border-aether-border">
        <div className="absolute inset-0 -z-[1]">
          <div
            className="h-full w-full"
            style={{
              background:
                "radial-gradient(ellipse 80% 60% at 30% 30%, rgba(0,212,255,0.18), transparent 60%), radial-gradient(ellipse 70% 50% at 80% 80%, rgba(212,160,23,0.10), transparent 60%)",
            }}
          />
          <div
            className="absolute inset-0"
            style={{
              background:
                "linear-gradient(180deg, rgba(4,5,7,0.2) 0%, rgba(4,5,7,0.6) 40%, rgba(4,5,7,0.92) 100%)",
            }}
          />
        </div>

        <div className="relative mx-auto flex min-h-[88vh] max-w-[1400px] flex-col justify-end px-[5%] pb-16 pt-28 lg:min-h-[92vh] lg:px-10 lg:pb-24 lg:pt-32">
          <motion.div initial="hidden" animate="show" className="max-w-4xl">
            <motion.p custom={0} variants={fadeUp} className="eyebrow mb-8 flex items-center gap-3">
              <span className="inline-block h-1.5 w-1.5 rounded-full bg-aether-green" style={{ boxShadow: "0 0 10px rgba(0,255,136,0.9)" }} />
              AETHER // GHOST PROTOCOL v2.1
            </motion.p>

            <motion.h1 custom={1} variants={fadeUp} className="font-display text-[clamp(2.5rem,6.4vw,5.5rem)] font-semibold uppercase leading-[0.95] tracking-[-0.01em] text-aether-text">
              Your Infrastructure Has A Fixed Address.{" "}
              <span className="text-aether-cyan">Attackers Know It.</span>
            </motion.h1>

            <motion.p custom={3} variants={fadeUp} className="mt-8 max-w-2xl font-sans text-lg leading-relaxed text-aether-dim md:text-xl">
              Aether Security replaces static endpoints with a quantum-seeded moving target. No fixed IP. No predictable pattern. No stable attack surface.
            </motion.p>

            <motion.div custom={4} variants={fadeUp} className="mt-12 flex flex-wrap items-center gap-4">
              <Link
                to={contactLink({ intent: 'sales', product: 'aether_security', cta: 'home_hero_live_demo' })}
                className="group relative inline-flex items-center gap-3 border border-aether-cyan bg-aether-cyan/10 px-7 py-4 font-mono text-xs uppercase tracking-[0.2em] text-aether-text transition-all duration-200 hover:bg-aether-cyan hover:text-aether-bg"
                style={{ boxShadow: "0 0 32px rgba(0,212,255,0.25)" }}
              >
                LIVE DEMO <span>→</span>
              </Link>
              <a
                href="#defense-stack"
                className="inline-flex items-center gap-3 border border-aether-border px-7 py-4 font-mono text-xs uppercase tracking-[0.2em] text-aether-text transition-colors duration-200 hover:border-aether-cyan/60 hover:text-aether-cyan"
              >
                VIEW THE STACK <span>↗</span>
              </a>
            </motion.div>

            <motion.div custom={5} variants={fadeUp} className="mt-16 grid grid-cols-1 gap-6 border-t border-aether-border pt-8 font-mono text-[11px] uppercase tracking-[0.18em] text-aether-muted sm:grid-cols-3 sm:max-w-2xl">
              <div>
                <div className="text-aether-cyan">1,387 TESTS &middot; 4 PRODUCTS</div>
              </div>
              <div>
                <div className="text-aether-cyan">3,000,000+ SURFACE STATES</div>
              </div>
              <div>
                <div className="text-aether-cyan">&lt;60s BOTNET EXHAUSTION</div>
              </div>
            </motion.div>
          </motion.div>
        </div>
        <div className="pointer-events-none absolute inset-x-0 bottom-0 h-[1px]" style={{ background: "linear-gradient(90deg, transparent, rgba(0,212,255,0.6), transparent)" }} />
      </section>

      {/* ─────────────── 2 · ATTACK TIMELINE COMPARISON ─────────────── */}
      <Section className="border-b border-aether-border px-[5%] py-20 lg:px-10">
        <div className="mx-auto max-w-[1400px]">
          <SectionHeading
            eyebrow="ATTACK SURFACE COMPARISON"
            title="What Happens When They Scan You"
            sub="Shodan indexed your current infrastructure within hours of provisioning. We verified this ourselves."
          />

          <div className="mt-8 grid gap-8 md:grid-cols-2">
            {/* Static column */}
            <motion.div variants={fadeUp} custom={2}>
              <Card>
                <h3 className="mb-6 font-mono text-sm uppercase tracking-[0.15em] text-aether-red">TARGET: STATIC INFRASTRUCTURE</h3>
                <div className="space-y-4 font-mono text-xs leading-relaxed text-aether-dim">
                  <div className="flex gap-3"><span className="shrink-0 text-aether-red">00:00</span><span>Attacker initiates port scan on target IP</span></div>
                  <div className="flex gap-3"><span className="shrink-0 text-aether-red">00:03</span><span>Open ports identified: 22, 80, 443, 8080</span></div>
                  <div className="flex gap-3"><span className="shrink-0 text-aether-red">00:08</span><span>Service fingerprinting: nginx/1.24, OpenSSH 9.1</span></div>
                  <div className="flex gap-3"><span className="shrink-0 text-aether-red">00:15</span><span>CVE database cross-reference complete</span></div>
                  <div className="flex gap-3"><span className="shrink-0 text-aether-red">00:22</span><span>Exploit chain assembled and staged</span></div>
                  <div className="flex gap-3"><span className="shrink-0 text-aether-red">00:30</span><span className="text-aether-red font-semibold">Initial access achieved. Game over.</span></div>
                </div>
              </Card>
            </motion.div>

            {/* Aether column */}
            <motion.div variants={fadeUp} custom={3}>
              <Card glow>
                <h3 className="mb-6 font-mono text-sm uppercase tracking-[0.15em] text-aether-cyan">TARGET: AETHER ENHANCED</h3>
                <div className="space-y-4 font-mono text-xs leading-relaxed text-aether-dim">
                  <div className="flex gap-3"><span className="shrink-0 text-aether-cyan">00:00</span><span>Attacker initiates port scan on target IP</span></div>
                  <div className="flex gap-3"><span className="shrink-0 text-aether-cyan">00:03</span><span>Scan hits Cloudflare edge — origin masked</span></div>
                  <div className="flex gap-3"><span className="shrink-0 text-aether-cyan">00:18</span><span>Ghost Protocol rotates proxy endpoint</span></div>
                  <div className="flex gap-3"><span className="shrink-0 text-aether-cyan">00:31</span><span>Previous IP now resolves to quantum tarpit</span></div>
                  <div className="flex gap-3"><span className="shrink-0 text-aether-cyan">00:47</span><span>Tarpit drains scanner resources, feeds garbage</span></div>
                  <div className="flex gap-3"><span className="shrink-0 text-aether-cyan">00:58</span><span className="text-aether-green font-semibold">Botnet exhausted. Attacker IP logged. Origin untouched.</span></div>
                </div>
              </Card>
            </motion.div>
          </div>
        </div>
      </Section>

      {/* ─────────────── 3 · GHOST PROTOCOL v2.1 ─────────────── */}
      <Section className="border-b border-aether-border px-[5%] py-20 lg:px-10">
        <div className="mx-auto max-w-[1400px]">
          <SectionHeading
            eyebrow="GHOST PROTOCOL v2.1"
            title="A Three-Node Quantum Moving Target Defense System"
          />
          <motion.div variants={fadeUp} custom={1} className="mb-8">
            <Badge variant="cyan">CLOUDFLARE EDGE</Badge>
          </motion.div>

          <div className="grid gap-6 md:grid-cols-3">
            {/* VPS-1 */}
            <motion.div variants={fadeUp} custom={2}>
              <Card>
                <h4 className="mb-1 font-mono text-sm font-semibold uppercase tracking-wider text-aether-cyan">VPS-1 GHOST PROXY</h4>
                <div className="mt-4 space-y-0">
                  <StatRow label="Role" value="Moving target router" />
                  <StatRow label="Jump cycle" value="47-391s" />
                  <StatRow label="Upstreams" value="Rotational" />
                  <StatRow label="Fingerprint" value="Dynamic" />
                </div>
              </Card>
            </motion.div>
            {/* VPS-2 */}
            <motion.div variants={fadeUp} custom={3}>
              <Card>
                <h4 className="mb-1 font-mono text-sm font-semibold uppercase tracking-wider text-aether-cyan">VPS-2 PRIMARY BACKEND</h4>
                <div className="mt-4 space-y-0">
                  <StatRow label="Role" value="Aether Terminal" />
                  <StatRow label="Traffic" value="Legit Only" />
                  <StatRow label="Quantum" value="30-qubit" />
                  <StatRow label="Services" value="Platform Edge" />
                </div>
              </Card>
            </motion.div>
            {/* VPS-3 */}
            <motion.div variants={fadeUp} custom={4}>
              <Card>
                <h4 className="mb-1 font-mono text-sm font-semibold uppercase tracking-wider text-aether-red">VPS-3 DARK NODE</h4>
                <div className="mt-4 space-y-0">
                  <StatRow label="Role" value="Quantum tarpit" />
                  <StatRow label="Shodan" value="NOT INDEXED" />
                  <StatRow label="Exhaustion" value="<60s" />
                  <StatRow label="IP" value="[REDACTED]" />
                </div>
              </Card>
            </motion.div>
          </div>
        </div>
      </Section>

      {/* ─────────────── 4 · IBM QUANTUM HARDWARE ─────────────── */}
      <Section className="border-b border-aether-border px-[5%] py-20 lg:px-10">
        <div className="mx-auto max-w-[1400px]">
          <motion.div variants={fadeUp} custom={0}>
            <Card glow className="mx-auto max-w-2xl text-center">
              <Badge variant="gold">IBM QUANTUM HARDWARE</Badge>
              <div className="mt-6 grid grid-cols-2 gap-4 sm:grid-cols-4">
                <div>
                  <div className="font-mono text-[11px] uppercase tracking-wider text-aether-muted">Job ID</div>
                  <div className="mt-1 font-mono text-xs text-aether-text break-all">d6sonabbjfas73fonq3g</div>
                </div>
                <div>
                  <div className="font-mono text-[11px] uppercase tracking-wider text-aether-muted">States</div>
                  <div className="mt-1 font-mono text-xs text-aether-cyan">3,000,000+</div>
                </div>
                <div>
                  <div className="font-mono text-[11px] uppercase tracking-wider text-aether-muted">Hardware</div>
                  <div className="mt-1 font-mono text-xs text-aether-text">IBM Fez 30-qubit</div>
                </div>
                <div>
                  <div className="font-mono text-[11px] uppercase tracking-wider text-aether-muted">Dwell</div>
                  <div className="mt-1 font-mono text-xs text-aether-text">47-404s</div>
                </div>
              </div>
              <p className="mt-6 font-mono text-[11px] leading-relaxed text-aether-dim">
                This is real hardware. This job ID is verifiable on IBM Quantum Network.
              </p>
            </Card>
          </motion.div>
        </div>
      </Section>

      {/* ─────────────── 5 · DEFENSE STACK ─────────────── */}
      <Section id="defense-stack" className="border-b border-aether-border px-[5%] py-20 lg:px-10">
        <div className="mx-auto max-w-[1400px]">
          <SectionHeading
            eyebrow="THE DEFENSE STACK"
            title="Three Integrated Systems. One Quantum Foundation."
          />

          <div className="grid gap-6 lg:grid-cols-3">
            {/* SCRAMBLER */}
            <motion.div variants={fadeUp} custom={2}>
              <Card className="flex h-full flex-col">
                <div className="mb-4 flex flex-wrap items-center gap-2">
                  <Badge variant="cyan">COMMERCIAL READY</Badge>
                  <Badge variant="green">PRIMARY PRODUCT</Badge>
                </div>
                <h3 className="font-mono text-lg font-bold uppercase tracking-wider text-aether-text">AETHER-SCRAMBLER</h3>
                <p className="mt-1 font-mono text-xs uppercase tracking-wider text-aether-dim">Ghost Protocol v2.1 &middot; MTD</p>
                <div className="mt-6 flex-1 space-y-0">
                  <StatRow label="Tests" value="257" />
                  <StatRow label="States" value="3M+" />
                  <StatRow label="Exhaustion" value="<60s" />
                  <StatRow label="Rotation" value="3-node" />
                </div>
              </Card>
            </motion.div>

            {/* PROTOCOL */}
            <motion.div variants={fadeUp} custom={3}>
              <Card className="flex h-full flex-col">
                <div className="mb-4 flex flex-wrap items-center gap-2">
                  <Badge variant="gold">SEALED</Badge>
                </div>
                <h3 className="font-mono text-lg font-bold uppercase tracking-wider text-aether-text">AETHER PROTOCOL</h3>
                <p className="mt-1 font-mono text-xs uppercase tracking-wider text-aether-dim">Cryptographic Commitment Layer</p>
                <div className="mt-4 space-y-0">
                  <StatRow label="Integrity" value="Tamper-evident" />
                  <StatRow label="Timestamp" value="RFC 3161" />
                  <StatRow label="Hash" value="SHA-256" />
                  <StatRow label="Keys" value="Ephemeral" />
                  <StatRow label="Output" value="Dispute proofs" />
                </div>
                <div className="mt-4 flex gap-2">
                  {["L", "C", "T"].map((v) => (
                    <button
                      key={v}
                      onClick={() => setProtocolVariant(v)}
                      className={`rounded border px-3 py-1 font-mono text-[10px] uppercase tracking-widest transition-colors ${
                        protocolVariant === v
                          ? "border-aether-cyan bg-aether-cyan/15 text-aether-cyan"
                          : "border-aether-border text-aether-muted hover:border-aether-cyan/40"
                      }`}
                    >
                      Protocol-{v}
                    </button>
                  ))}
                </div>
                <p className="mt-2 font-mono text-[10px] text-aether-dim">
                  {protocolVariant === "L" && "Quantum — IBM hardware entropy"}
                  {protocolVariant === "C" && "CSPRNG — Cryptographically secure fallback"}
                  {protocolVariant === "T" && "TEE — Trusted execution environment"}
                </p>
              </Card>
            </motion.div>

            {/* PREDATOR */}
            <motion.div variants={fadeUp} custom={4}>
              <Card className="flex h-full flex-col">
                <div className="mb-4 flex flex-wrap items-center gap-2">
                  <Badge variant="red">ACTIVE</Badge>
                  <Badge variant="muted">INCLUDED IN ENTERPRISE</Badge>
                </div>
                <h3 className="font-mono text-lg font-bold uppercase tracking-wider text-aether-text">AETHER-PREDATOR</h3>
                <p className="mt-1 font-mono text-xs uppercase tracking-wider text-aether-dim">Quantum Red Team Engine</p>
                <div className="mt-6 flex-1 space-y-0">
                  <StatRow label="Tests" value="329" />
                  <StatRow label="MITRE ATT&CK" value="350 chains" />
                  <StatRow label="States" value="1B+" />
                  <StatRow label="Loop" value="Q→C→Q patented" />
                  <StatRow label="Circuit" value="40-qubit ZZFeatureMap" />
                </div>
              </Card>
            </motion.div>
          </div>

          <motion.div variants={fadeUp} custom={5}>
            <p className="mt-8 text-center font-mono text-[11px] uppercase tracking-[0.15em] text-aether-muted">
              ALL THREE SHARE ONE IBM QUANTUM SESSION — Job ID: <span className="text-aether-cyan">d6sonabbjfas73fonq3g</span>
            </p>
          </motion.div>
        </div>
      </Section>

      {/* ─────────────── 6 · THREAT COVERAGE MATRIX ─────────────── */}
      <Section className="border-b border-aether-border px-[5%] py-20 lg:px-10">
        <div className="mx-auto max-w-[1400px]">
          <SectionHeading eyebrow="THREAT MATRIX" title="What We Defend Against" />

          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {[
              { threat: "VOLUMETRIC DDOS", desc: "High-bandwidth flood attacks", defense: "Cloudflare Edge", stat: "1.2 Tbps" },
              { threat: "IP FINGERPRINTING", desc: "Scanner-based reconnaissance", defense: "Ghost Protocol", stat: "<40s scan window" },
              { threat: "TIMING CORRELATION", desc: "Traffic analysis & pattern matching", defense: "Quantum Entropy", stat: "0.999 Entropy" },
              { threat: "BOTNET EXHAUSTION", desc: "Distributed brute-force attacks", defense: "Quantum Tarpit", stat: "<60s dump" },
              { threat: "CREDENTIAL STUFFING", desc: "Automated credential replay", defense: "Quantum Rate Limiter", stat: "100% block" },
              { threat: "SESSION HIJACKING", desc: "Token theft & replay", defense: "Protocol-L", stat: "Tamper-evident" },
            ].map((t, i) => (
              <motion.div key={t.threat} variants={fadeUp} custom={i + 1}>
                <Card className="h-full">
                  <h4 className="font-mono text-sm font-bold uppercase tracking-wider text-aether-text">{t.threat}</h4>
                  <p className="mt-1 text-xs text-aether-dim">{t.desc}</p>
                  <div className="mt-4 flex items-baseline justify-between border-t border-aether-border/40 pt-3 font-mono text-xs">
                    <span className="uppercase tracking-wider text-aether-cyan">{t.defense}</span>
                    <span className="font-semibold text-aether-text">{t.stat}</span>
                  </div>
                </Card>
              </motion.div>
            ))}
          </div>
        </div>
      </Section>

      {/* ─────────────── 7 · DEFENSE PRICING ─────────────── */}
      <Section className="border-b border-aether-border px-[5%] py-20 lg:px-10">
        <div className="mx-auto max-w-[1400px]">
          <SectionHeading eyebrow="DEFENSE PRICING" title="Choose Your Defense Posture" />

          {/* Toggle */}
          <motion.div variants={fadeUp} custom={1} className="mb-10 flex items-center gap-4">
            <span className={`font-mono text-xs uppercase tracking-wider ${!annual ? "text-aether-cyan" : "text-aether-muted"}`}>Monthly</span>
            <button
              onClick={() => setAnnual(!annual)}
              className={`relative h-6 w-11 rounded-full border transition-colors ${annual ? "border-aether-cyan bg-aether-cyan/20" : "border-aether-border bg-aether-raised"}`}
            >
              <span className={`absolute top-0.5 h-5 w-5 rounded-full bg-aether-text transition-transform ${annual ? "left-[22px]" : "left-0.5"}`} />
            </button>
            <span className={`font-mono text-xs uppercase tracking-wider ${annual ? "text-aether-cyan" : "text-aether-muted"}`}>Annual <span className="text-aether-green">(saves 17%)</span></span>
          </motion.div>

          <div className="grid gap-6 lg:grid-cols-3">
            {/* Shield */}
            <motion.div variants={fadeUp} custom={2}>
              <Card className="flex h-full flex-col">
                <h3 className="font-mono text-lg font-bold uppercase tracking-wider text-aether-text">AETHER SHIELD</h3>
                <div className="mt-2 flex items-baseline gap-1">
                  <span className="font-display text-3xl font-bold text-aether-cyan">${annual ? "249" : "299"}</span>
                  <span className="font-mono text-xs text-aether-muted">/mo</span>
                </div>
                <ul className="mt-6 flex-1 space-y-3 text-sm text-aether-dim">
                  <li className="flex gap-2"><span className="text-aether-cyan">&#10003;</span> Ghost Protocol MTD</li>
                  <li className="flex gap-2"><span className="text-aether-cyan">&#10003;</span> 3M+ surface states</li>
                  <li className="flex gap-2"><span className="text-aether-cyan">&#10003;</span> Shared 3-VPS rotation</li>
                  <li className="flex gap-2"><span className="text-aether-cyan">&#10003;</span> Quantum tarpit</li>
                  <li className="flex gap-2"><span className="text-aether-cyan">&#10003;</span> Pooled IBM session</li>
                </ul>
                <p className="mt-4 font-mono text-[10px] uppercase tracking-wider text-aether-muted">SLA: Best effort</p>
              </Card>
            </motion.div>

            {/* Fortress */}
            <motion.div variants={fadeUp} custom={3}>
              <Card glow className="relative flex h-full flex-col">
                <div className="absolute -top-3 right-4"><Badge variant="cyan">RECOMMENDED</Badge></div>
                <h3 className="font-mono text-lg font-bold uppercase tracking-wider text-aether-text">AETHER FORTRESS</h3>
                <div className="mt-2 flex items-baseline gap-1">
                  <span className="font-display text-3xl font-bold text-aether-cyan">${annual ? "2,075" : "2,500"}</span>
                  <span className="font-mono text-xs text-aether-muted">/mo</span>
                </div>
                <ul className="mt-6 flex-1 space-y-3 text-sm text-aether-dim">
                  <li className="flex gap-2"><span className="text-aether-cyan">&#10003;</span> Everything in Shield</li>
                  <li className="flex gap-2"><span className="text-aether-cyan">&#10003;</span> Dedicated VPS cluster</li>
                  <li className="flex gap-2"><span className="text-aether-cyan">&#10003;</span> Dedicated IBM session</li>
                  <li className="flex gap-2"><span className="text-aether-cyan">&#10003;</span> 99.9% SLA</li>
                  <li className="flex gap-2"><span className="text-aether-cyan">&#10003;</span> Monthly security review</li>
                </ul>
                <p className="mt-4 font-mono text-[10px] uppercase tracking-wider text-aether-muted">SLA: 99.9% uptime</p>
              </Card>
            </motion.div>

            {/* Enterprise */}
            <motion.div variants={fadeUp} custom={4}>
              <Card className="flex h-full flex-col">
                <h3 className="font-mono text-lg font-bold uppercase tracking-wider text-aether-text">AETHER ENTERPRISE</h3>
                <div className="mt-2 flex items-baseline gap-1">
                  <span className="font-display text-3xl font-bold text-aether-cyan">$35k+</span>
                  <span className="font-mono text-xs text-aether-muted">one-time</span>
                </div>
                <ul className="mt-6 flex-1 space-y-3 text-sm text-aether-dim">
                  <li className="flex gap-2"><span className="text-aether-cyan">&#10003;</span> Full source license</li>
                  <li className="flex gap-2"><span className="text-aether-cyan">&#10003;</span> Protocol source (C/L/T)</li>
                  <li className="flex gap-2"><span className="text-aether-cyan">&#10003;</span> Scrambler source</li>
                  <li className="flex gap-2"><span className="text-aether-cyan">&#10003;</span> On-prem deployment</li>
                  <li className="flex gap-2"><span className="text-aether-cyan">&#10003;</span> Dedicated account manager</li>
                  <li className="flex gap-2"><span className="text-aether-cyan">&#10003;</span> White-label rights</li>
                </ul>
              </Card>
            </motion.div>
          </div>

          <motion.p variants={fadeUp} custom={5} className="mt-6 text-center font-mono text-[11px] text-aether-dim">
            First Fortress client: 3 months at $500/mo with case study agreement
          </motion.p>
        </div>
      </Section>

      {/* ─────────────── 8 · OFFENSE PRICING (PREDATOR) ─────────────── */}
      <Section className="border-b border-aether-border px-[5%] py-20 lg:px-10">
        <div className="mx-auto max-w-[1400px]">
          <SectionHeading
            eyebrow="OFFENSE // PREDATOR"
            title="Choose Your Offense Posture"
            sub="Predator uses a 40-qubit ZZFeatureMap quantum circuit to model adversarial behavior no classical fuzzer can replicate."
          />

          <div className="grid gap-6 lg:grid-cols-3">
            {/* Single */}
            <motion.div variants={fadeUp} custom={2}>
              <Card className="flex h-full flex-col">
                <h3 className="font-mono text-lg font-bold uppercase tracking-wider text-aether-text">SINGLE ENGAGEMENT</h3>
                <div className="mt-2 flex items-baseline gap-1">
                  <span className="font-display text-3xl font-bold text-aether-cyan">$4,500</span>
                </div>
                <ul className="mt-6 flex-1 space-y-3 text-sm text-aether-dim">
                  <li className="flex gap-2"><span className="text-aether-red">&#9670;</span> One Predator pentest</li>
                  <li className="flex gap-2"><span className="text-aether-red">&#9670;</span> 350 MITRE ATT&CK chains</li>
                  <li className="flex gap-2"><span className="text-aether-red">&#9670;</span> 40-qubit ZZFeatureMap</li>
                  <li className="flex gap-2"><span className="text-aether-red">&#9670;</span> Q&#8594;C&#8594;Q report</li>
                  <li className="flex gap-2"><span className="text-aether-red">&#9670;</span> 1B+ states explored</li>
                </ul>
              </Card>
            </motion.div>

            {/* Retainer */}
            <motion.div variants={fadeUp} custom={3}>
              <Card glow className="relative flex h-full flex-col">
                <div className="absolute -top-3 right-4"><Badge variant="cyan">RECOMMENDED</Badge></div>
                <h3 className="font-mono text-lg font-bold uppercase tracking-wider text-aether-text">MONTHLY RETAINER</h3>
                <div className="mt-2 flex items-baseline gap-1">
                  <span className="font-display text-3xl font-bold text-aether-cyan">$8,500</span>
                  <span className="font-mono text-xs text-aether-muted">/mo</span>
                </div>
                <ul className="mt-6 flex-1 space-y-3 text-sm text-aether-dim">
                  <li className="flex gap-2"><span className="text-aether-red">&#9670;</span> Up to 4 engagements/mo</li>
                  <li className="flex gap-2"><span className="text-aether-red">&#9670;</span> Priority IBM quantum access</li>
                  <li className="flex gap-2"><span className="text-aether-red">&#9670;</span> Monthly threat surface report</li>
                  <li className="flex gap-2"><span className="text-aether-red">&#9670;</span> Dedicated quantum session</li>
                </ul>
              </Card>
            </motion.div>

            {/* Enterprise SOW */}
            <motion.div variants={fadeUp} custom={4}>
              <Card className="flex h-full flex-col">
                <h3 className="font-mono text-lg font-bold uppercase tracking-wider text-aether-text">ENTERPRISE SOW</h3>
                <div className="mt-2 flex items-baseline gap-1">
                  <span className="font-display text-3xl font-bold text-aether-cyan">Custom</span>
                </div>
                <ul className="mt-6 flex-1 space-y-3 text-sm text-aether-dim">
                  <li className="flex gap-2"><span className="text-aether-red">&#9670;</span> Embedded red team</li>
                  <li className="flex gap-2"><span className="text-aether-red">&#9670;</span> Custom MITRE chains</li>
                  <li className="flex gap-2"><span className="text-aether-red">&#9670;</span> White-label reports</li>
                  <li className="flex gap-2"><span className="text-aether-red">&#9670;</span> On-prem deployment</li>
                </ul>
              </Card>
            </motion.div>
          </div>
        </div>
      </Section>

      {/* ─────────────── 9 · IBM QUANTUM VERIFICATION ─────────────── */}
      <Section className="border-b border-aether-border px-[5%] py-20 lg:px-10">
        <div className="mx-auto max-w-[1400px]">
          <SectionHeading eyebrow="VERIFICATION" title="IBM Quantum Session Proof" />

          <motion.div variants={fadeUp} custom={2}>
            <Card className="overflow-x-auto">
              <table className="w-full font-mono text-xs">
                <tbody className="divide-y divide-aether-border/40">
                  {[
                    ["Backend", "IBM Fez (127-qubit)"],
                    ["Job ID", "d6sonabbjfas73fonq3g"],
                    ["Session", "c7071827"],
                    ["P (Measured)", "58.47"],
                    ["U (Expected)", "55.72"],
                    ["Delta", "-2.75"],
                    ["Ghost Jumps", "13"],
                    ["Breach", "NO"],
                  ].map(([k, v]) => (
                    <tr key={k}>
                      <td className="py-2 pr-6 uppercase tracking-wider text-aether-muted">{k}</td>
                      <td className={`py-2 ${v === "NO" ? "text-aether-green font-bold" : "text-aether-text"}`}>{v}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Card>
          </motion.div>

          <motion.p variants={fadeUp} custom={3} className="mt-6 max-w-xl font-mono text-[11px] leading-relaxed text-aether-dim">
            This job ID is publicly verifiable on IBM Quantum Network. We do not simulate results. Every rotation, every state, every timestamp is hardware-attested.
          </motion.p>
        </div>
      </Section>

      {/* ─────────────── 10 · LIVE DASHBOARD PREVIEW ─────────────── */}
      <Section className="border-b border-aether-border px-[5%] py-20 lg:px-10">
        <div className="mx-auto max-w-[1400px]">
          <SectionHeading eyebrow="LIVE PREVIEW" title="Real-Time Defense Dashboard" />

          <motion.div variants={fadeUp} custom={2}>
            <Card className="relative overflow-hidden">
              {/* Simulated dashboard */}
              <div className="grid gap-4 sm:grid-cols-3">
                {/* VPS Topology */}
                <div className="rounded border border-aether-border/60 bg-aether-bg p-4">
                  <p className="mb-3 font-mono text-[10px] uppercase tracking-widest text-aether-muted">3-NODE VPS TOPOLOGY</p>
                  <div className="flex items-center justify-around py-6">
                    {["GHOST", "PRIMARY", "DARK"].map((n, i) => (
                      <div key={n} className="text-center">
                        <div className={`mx-auto mb-2 h-4 w-4 rounded-full ${i === 2 ? "bg-aether-red" : "bg-aether-cyan"}`} style={{ boxShadow: `0 0 12px ${i === 2 ? "rgba(232,64,64,0.6)" : "rgba(0,212,255,0.6)"}` }} />
                        <span className="font-mono text-[9px] uppercase tracking-wider text-aether-dim">{n}</span>
                      </div>
                    ))}
                  </div>
                </div>
                {/* Jump Counter */}
                <div className="rounded border border-aether-border/60 bg-aether-bg p-4">
                  <p className="mb-3 font-mono text-[10px] uppercase tracking-widest text-aether-muted">JUMP COUNTER</p>
                  <div className="flex flex-col items-center justify-center py-4">
                    <span className="font-display text-4xl font-bold text-aether-cyan">13</span>
                    <span className="mt-1 font-mono text-[10px] uppercase tracking-wider text-aether-muted">ghost jumps this session</span>
                  </div>
                </div>
                {/* Threat Feed + IBM */}
                <div className="rounded border border-aether-border/60 bg-aether-bg p-4">
                  <p className="mb-3 font-mono text-[10px] uppercase tracking-widest text-aether-muted">THREAT FEED</p>
                  <div className="space-y-2 font-mono text-[10px] text-aether-dim">
                    <div className="flex gap-2"><span className="text-aether-red">&#9679;</span> Scan blocked — 194.x.x.x</div>
                    <div className="flex gap-2"><span className="text-aether-red">&#9679;</span> Tarpit engaged — 45.x.x.x</div>
                    <div className="flex gap-2"><span className="text-aether-green">&#9679;</span> Ghost jump complete</div>
                  </div>
                  <div className="mt-4 border-t border-aether-border/40 pt-3">
                    <p className="font-mono text-[10px] uppercase tracking-widest text-aether-muted">IBM SESSION</p>
                    <p className="mt-1 font-mono text-[10px] text-aether-green">&#9679; ACTIVE — c7071827</p>
                  </div>
                </div>
              </div>
            </Card>
          </motion.div>
        </div>
      </Section>

      {/* ─────────────── 11 · FAQ ─────────────── */}
      <Section className="border-b border-aether-border px-[5%] py-20 lg:px-10">
        <div className="mx-auto max-w-[1400px]">
          <SectionHeading eyebrow="FAQ" title="Frequently Asked Questions" />

          <motion.div variants={fadeUp} custom={2} className="max-w-3xl space-y-0 divide-y divide-aether-border/40">
            {[
              {
                q: "Do I need to change my DNS or leave Cloudflare?",
                a: "No. Aether deploys behind Cloudflare. Your existing DNS, WAF rules, and caching stay intact. We add moving-target defense at the origin layer — Cloudflare never sees a change.",
              },
              {
                q: "What part of this is actually quantum?",
                a: "The entropy source. Every Ghost Protocol jump uses dwell-time measurements from IBM quantum hardware (currently IBM Fez, 30-qubit). This makes rotation intervals genuinely unpredictable — not PRNG-seeded unpredictable, but physics-level unpredictable.",
              },
              {
                q: "What happens if IBM Quantum is unavailable?",
                a: "Protocol-C (CSPRNG) takes over automatically. You lose hardware attestation but keep cryptographic randomness. When IBM comes back, we re-anchor to hardware entropy. No downtime, no manual intervention.",
              },
              {
                q: "Is the shared infrastructure on Shield actually secure?",
                a: "Yes. Each tenant gets isolated VPS instances with dedicated firewall rules. 'Shared' refers to the IBM quantum session (pooled job queue) and VPS pool — not the network path or attack surface. Your traffic never touches another tenant's stack.",
              },
              {
                q: "What is the patent status?",
                a: "Patent pending. The Q→C→Q loop (quantum-to-classical-to-quantum adversarial modeling) is novel and under active prosecution. Enterprise licensees receive full IP indemnification.",
              },
              {
                q: "What is the relationship between Protocol-L and Predator?",
                a: "Protocol-L is the commitment layer — it creates tamper-evident records of every rotation, session, and state change. Predator is the red team engine — it uses quantum circuits to find what Protocol-L should be protecting. They share the same IBM quantum session.",
              },
              {
                q: "Can this defend against nation-state actors?",
                a: "We raise the cost of attack significantly. A moving target with quantum-seeded rotation means an attacker must re-enumerate on every jump cycle (47-391s). Combined with the quantum tarpit, even well-resourced adversaries face resource exhaustion. We don't claim invincibility — we claim measurable, hardware-verified defense.",
              },
            ].map((faq, i) => (
              <FaqItem key={i} q={faq.q} a={faq.a} />
            ))}
          </motion.div>
        </div>
      </Section>

      {/* ─────────────── 12 · ENTERPRISE CTA ─────────────── */}
      <Section className="border-b border-aether-border px-[5%] py-20 lg:px-10">
        <div className="mx-auto max-w-[1400px] text-center">
          <motion.div variants={fadeUp} custom={0}>
            <Badge variant="gold">ENTERPRISE</Badge>
          </motion.div>
          <motion.p variants={fadeUp} custom={1} className="mx-auto mt-6 max-w-2xl font-sans text-lg leading-relaxed text-aether-dim md:text-xl">
            For AI platforms, infrastructure providers, and regulated institutions evaluating Protocol-L as a native trust layer.
          </motion.p>
          <motion.div variants={fadeUp} custom={2} className="mt-8">
            <Link
              to={contactLink({ intent: 'sales', product: 'aether_security', cta: 'home_enterprise_cta' })}
              className="inline-flex items-center gap-3 border border-aether-gold bg-aether-gold/10 px-7 py-4 font-mono text-xs uppercase tracking-[0.2em] text-aether-text transition-all duration-200 hover:bg-aether-gold hover:text-aether-bg"
            >
              CONTACT ENTERPRISE <span>→</span>
            </Link>
          </motion.div>
        </div>
      </Section>

      {/* ─────────────── 13 · FINAL CTA ─────────────── */}
      <Section className="border-b border-aether-border px-[5%] py-24 lg:px-10">
        <div className="mx-auto max-w-[1400px] text-center">
          <motion.h2 variants={fadeUp} custom={0} className="mx-auto max-w-4xl font-display text-[clamp(1.6rem,4vw,3rem)] font-semibold uppercase leading-[1.05] tracking-tight text-aether-text">
            YOUR ENDPOINT IS STATIC.{" "}
            <span className="text-aether-dim">ATTACKERS ARE PATIENT.</span>{" "}
            <span className="text-aether-cyan">QUANTUM PHYSICS IS NOT.</span>
          </motion.h2>
          <motion.div variants={fadeUp} custom={1} className="mt-10 flex flex-wrap items-center justify-center gap-4">
            <Link
              to={contactLink({ intent: 'sales', product: 'aether_security', cta: 'home_final_live_demo' })}
              className="group relative inline-flex items-center gap-3 border border-aether-cyan bg-aether-cyan/10 px-7 py-4 font-mono text-xs uppercase tracking-[0.2em] text-aether-text transition-all duration-200 hover:bg-aether-cyan hover:text-aether-bg"
              style={{ boxShadow: "0 0 32px rgba(0,212,255,0.25)" }}
            >
              LIVE DEMO <span>→</span>
            </Link>
            <a
              href="#defense-stack"
              className="inline-flex items-center gap-3 border border-aether-border px-7 py-4 font-mono text-xs uppercase tracking-[0.2em] text-aether-text transition-colors duration-200 hover:border-aether-cyan/60 hover:text-aether-cyan"
            >
              START WITH SHIELD <span>↗</span>
            </a>
          </motion.div>
        </div>
      </Section>

      {/* ─────────────── 14 · FOOTER NOTE ─────────────── */}
      <section className="px-[5%] py-12 lg:px-10">
        <div className="mx-auto max-w-[1400px] text-center">
          <p className="font-mono text-[11px] uppercase tracking-[0.15em] text-aether-muted">
            Aether AI &middot; Florida &middot; 4 Products &middot; Patent Pending
          </p>
          <p className="mt-3 font-mono text-[10px] text-aether-dim">
            First Fortress client: 3 months at $500/mo with case study agreement &middot;{" "}
            <Link to={contactLink({ intent: 'general', product: 'aether_security', cta: 'home_footer_email' })} className="text-aether-cyan hover:underline">contact@aethersecurity.io</Link>
          </p>
        </div>
      </section>
    </div>
  );
}

/* ─────────────── FAQ Accordion Item ─────────────── */
function FaqItem({ q, a }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="py-5">
      <button
        onClick={() => setOpen(!open)}
        className="flex w-full items-start justify-between gap-4 text-left"
      >
        <span className="font-sans text-base font-medium text-aether-text md:text-lg">{q}</span>
        <span className="mt-1 shrink-0 font-mono text-lg text-aether-cyan">{open ? "−" : "+"}</span>
      </button>
      {open && (
        <motion.div
          initial={{ opacity: 0, height: 0 }}
          animate={{ opacity: 1, height: "auto" }}
          transition={{ duration: 0.25 }}
          className="mt-3 text-sm leading-relaxed text-aether-dim"
        >
          {a}
        </motion.div>
      )}
    </div>
  );
}
