import React, { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { gsap } from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";
import { DOWNLOAD_URL, UPGRADE_URL, TIER_CHECKOUT_LINKS } from "../../lib/config.js";
import "./aethercloud.css";

gsap.registerPlugin(ScrollTrigger);

/* ═══════════════════════════════════════════════════
   CONFIG — CTA destinations are imported from lib/config.js so deploys
   can override via VITE_CHECKOUT_API_URL / VITE_DOWNLOAD_URL env vars
   without a code change. `UPGRADE_URL` is the internal hash anchor for
   "See pricing →"; the paid tier buttons below call startCheckout()
   directly and bypass that URL.
   ═══════════════════════════════════════════════════ */
const DOCS_URL     = "/documentation";
const PROTOCOL_URL = "/protocol-family";

/* ═══════════════════════════════════════════════════
   Smooth-scroll helper (respects reduced-motion)
   ═══════════════════════════════════════════════════ */
function smoothScrollTo(id) {
  const el = document.getElementById(id);
  if (!el) return;
  const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  el.scrollIntoView({ behavior: reduced ? "auto" : "smooth", block: "start" });
}

/* ═══════════════════════════════════════════════════
   HERO — scroll-scrubbed pool ball video
   ═══════════════════════════════════════════════════ */
function Hero() {
  const videoRef = useRef(null);
  const contentRef = useRef(null);
  const exitFadeRef = useRef(null);
  const progressRef = useRef(null);
  const scrollHintRef = useRef(null);
  const containerRef = useRef(null);

  useEffect(() => {
    const video = videoRef.current;
    const content = contentRef.current;
    const exitFade = exitFadeRef.current;
    const progress = progressRef.current;
    const scrollHint = scrollHintRef.current;
    const container = containerRef.current;
    if (!video || !container) return;

    // Respect reduced motion — no scroll-scrubbed video
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    video.pause();
    video.currentTime = 0;

    const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
    const norm = (v, lo, hi) => clamp((v - lo) / (hi - lo), 0, 1);

    let st1;

    const ready = () => {
      const dur = video.duration || 3.042;

      st1 = ScrollTrigger.create({
        trigger: container,
        start: "top top",
        end: "bottom bottom",
        scrub: reduced ? 0.6 : 0.15,
        onUpdate(self) {
          const raw = self.progress;
          if (progress) progress.style.transform = `scaleX(${raw})`;
          // Effective clip range: first 2.04s of the 3.04s video (trim the tail).
          // This ends the scrub ~1s earlier so the hero releases into TrustStrip
          // before the "cue almost strikes" frames that feel like dead air.
          const effectiveDur = Math.min(dur, 2.04);
          video.currentTime = clamp(raw * effectiveDur, 0, effectiveDur);
          // Headline fades during the compressed levitation beat
          if (content)  content.style.opacity  = clamp(1 - norm(raw, 0.25, 0.45), 0, 1);
          // Dark overlay ramps earlier so TrustStrip reveals sooner
          if (exitFade) exitFade.style.opacity = clamp(norm(raw, 0.60, 1.00), 0, 1);
        },
      });
    };

    if (reduced) {
      // Static poster only — no scrubbing timeline
      video.removeAttribute("autoplay");
      if (progress) progress.style.transform = "scaleX(0)";
    } else if (video.readyState >= 1) {
      ready();
    } else {
      video.addEventListener("loadedmetadata", ready, { once: true });
    }

    const st2 = ScrollTrigger.create({
      trigger: container,
      start: "top+=5% top",
      onEnter() { if (scrollHint) scrollHint.classList.add("ac-hidden"); },
    });

    return () => { if (st1) st1.kill(); st2.kill(); };
  }, []);

  const handleSeeHow = (e) => {
    e.preventDefault();
    smoothScrollTo("ac-how-it-works");
  };

  return (
    <>
      <div ref={progressRef} id="ac-progress-bar" />
      <div className="ac-scan-line" />
      <div className="ac-pcb-overlay" />

      <div ref={containerRef} id="ac-scroll-container">
        <div id="ac-sticky-wrap">
          <video
            ref={videoRef}
            id="ac-hero-video"
            muted
            playsInline
            preload="auto"
            poster="/aether-cloud/rack_poster_4k.webp"
          >
            <source src="/aether-cloud/rack_liftoff_4k.mp4" type="video/mp4" />
          </video>
          <div id="ac-hero-video-overlay" />
          <div ref={exitFadeRef} id="ac-hero-exit-fade" />

          <div ref={contentRef} id="ac-home-content">
            <div style={{ maxWidth: 620 }}>
              <div className="ac-eyebrow">
                <span className="ac-eyebrow-line" />
                <span className="ac-eyebrow-dot" />
                Desktop AI Agent — Vaulted &amp; Signed
              </div>
              <h1 className="ac-text-hero" style={{ marginBottom: "1.25rem" }}>
                <span style={{ display: "block", color: "var(--ac-text)" }}>Put your client</span>
                <span className="ac-grad-text" style={{ display: "block" }}>files into an AI</span>
              </h1>
              {/* Tightened hero subtext — 12 words, per audit P2.4 */}
              <p className="ac-text-body-lg" style={{ marginBottom: "2rem", maxWidth: 500 }}>
                Your files in a vault. Every answer signed. Proof when it matters.
              </p>
              <div className="ac-btn-row">
                <a href={DOWNLOAD_URL} className="ac-btn-primary">
                  <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                    <path d="M12 3v13m0 0l-5-5m5 5l5-5M5 21h14" strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                  Download free
                </a>
                <a href="#ac-how-it-works" onClick={handleSeeHow} className="ac-btn-ghost">
                  See how it works
                </a>
              </div>
              <div className="ac-stat-strip">
                <div className="ac-stat-item"><span className="ac-stat-num">656</span><span className="ac-stat-lbl">Security tests</span></div>
                <div className="ac-stat-item"><span className="ac-stat-num">40+</span><span className="ac-stat-lbl">Injection blocks</span></div>
                <div className="ac-stat-item"><span className="ac-stat-num">15-min</span><span className="ac-stat-lbl">Token rotation</span></div>
                <div className="ac-stat-item"><span className="ac-stat-num">0 leaks</span><span className="ac-stat-lbl">Vault breaches</span></div>
              </div>
            </div>
          </div>

          <div ref={scrollHintRef} id="ac-scroll-hint">
            <div className="ac-scroll-mouse" />
            <span>Scroll to explore</span>
          </div>
        </div>
      </div>
    </>
  );
}

/* ═══════════════════════════════════════════════════
   TRUST STRIP — "Built on" — P2.1
   Text + inline SVG icons. Swap for real logos after
   Anthropic / Tailscale brand-use clearance.
   ═══════════════════════════════════════════════════ */
function TrustStrip() {
  return (
    <section className="ac-trust-strip" aria-label="Technology and compliance">
      <div className="ac-container">
        <div className="ac-trust-row">
          <span className="ac-trust-label">Built on</span>

          <div className="ac-trust-item">
            {/* Anthropic placeholder mark — replace with licensed SVG */}
            <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="1.6">
              <path d="M7 4l5 12 5-12M9 14h6" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
            <span>Claude · Anthropic</span>
          </div>

          <div className="ac-trust-item">
            {/* Tailscale placeholder mark */}
            <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="1.6">
              <circle cx="6" cy="6" r="1.4" /><circle cx="12" cy="6" r="1.4" /><circle cx="18" cy="6" r="1.4" />
              <circle cx="6" cy="12" r="1.4" /><circle cx="12" cy="12" r="1.4" fill="currentColor" /><circle cx="18" cy="12" r="1.4" />
              <circle cx="6" cy="18" r="1.4" /><circle cx="12" cy="18" r="1.4" /><circle cx="18" cy="18" r="1.4" />
            </svg>
            <span>Tailscale mesh</span>
          </div>

          <div className="ac-trust-item">
            <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="1.6">
              <rect x="4" y="10" width="16" height="10" rx="1.5" />
              <path d="M8 10V7a4 4 0 018 0v3" strokeLinecap="round" />
            </svg>
            <span>SHA-256 signed</span>
          </div>

          <div className="ac-trust-item">
            <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="1.6">
              <path d="M12 3l8 4v5c0 5-3.5 8-8 9-4.5-1-8-4-8-9V7l8-4z" strokeLinejoin="round" />
              <path d="M9 12l2 2 4-4" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
            <span>SOC 2 Type I · in progress</span>
          </div>
        </div>
      </div>
    </section>
  );
}

/* ═══════════════════════════════════════════════════
   COMPARISON TABLE — now section #2 (P2.2)
   ═══════════════════════════════════════════════════ */
function Comparison() {
  const rows = [
    { task: "Reads every file in your project",      chatgpt: "cross", cursor: "partial", ac: "check" },
    { task: "Files stay in a vault only you open",   chatgpt: "cross", cursor: "cross",   ac: "check" },
    { task: "Every answer cryptographically signed", chatgpt: "cross", cursor: "cross",   ac: "check" },
    { task: "Exportable audit chain for compliance", chatgpt: "cross", cursor: "cross",   ac: "check" },
    { task: "Your IP never reaches vendor servers",  chatgpt: "cross", cursor: "cross",   ac: "check" },
  ];

  const renderCell = (type) => {
    if (type === "check")   return <span className="ac-check" aria-label="Yes">✓</span>;
    if (type === "partial") return <span className="ac-partial">Partial</span>;
    return <span className="ac-cross" aria-label="No">✕</span>;
  };

  return (
    <section className="ac-section ac-zone-violet">
      <div className="ac-container">
        <div className="ac-section-header">
          <span className="ac-text-label">The honest comparison</span>
          <h2 className="ac-text-display" style={{ marginBottom: "0.75rem" }}>
            What you actually get for $19
          </h2>
          <p className="ac-text-body">We get asked this daily. Here's the honest version.</p>
        </div>
        <table className="ac-comparison-table">
          <thead>
            <tr>
              <th></th>
              <th>ChatGPT / Claude Pro</th>
              <th>Cursor / Copilot</th>
              <th style={{ color: "var(--ac-violet-soft)" }}>AetherCloud</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row, i) => (
              <tr key={i}>
                <td>{row.task}</td>
                <td>{renderCell(row.chatgpt)}</td>
                <td>{renderCell(row.cursor)}</td>
                <td>{renderCell(row.ac)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <div className="ac-btn-row" style={{ justifyContent: "center", marginTop: "2.5rem" }}>
          <a href={DOWNLOAD_URL} className="ac-btn-primary">Download free</a>
          <Link to={UPGRADE_URL} className="ac-link-arrow">See pricing →</Link>
        </div>
      </div>
    </section>
  );
}

/* ═══════════════════════════════════════════════════
   STATS (now after comparison, same violet zone family
   but uses iris zone to mark transition)
   ═══════════════════════════════════════════════════ */
function Stats() {
  return (
    <section className="ac-section ac-zone-iris">
      <div className="ac-container">
        <div className="ac-grid-2">
          <div>
            <span className="ac-text-label">AetherCloud · Desktop AI, vaulted</span>
            <h2 className="ac-text-display" style={{ marginBottom: "1rem" }}>
              Built for work where a leak costs you a client
            </h2>
            <p className="ac-text-body-lg" style={{ marginBottom: "1.75rem" }}>
              Desktop app, not a browser tab. 15-minute trial. No credit card, no sales call.
            </p>
            <div className="ac-btn-row">
              <a href={DOWNLOAD_URL} className="ac-btn-primary">Download free</a>
              <Link to={UPGRADE_URL} className="ac-link-arrow">See pricing →</Link>
            </div>
          </div>
          <div className="ac-stats-grid">
            <div className="ac-stat-block">
              <div className="ac-stat-block-num">656</div>
              <div className="ac-stat-block-label">Security tests in last build</div>
            </div>
            <div className="ac-stat-block">
              <div className="ac-stat-block-num">40+</div>
              <div className="ac-stat-block-label">Prompt-injection patterns blocked</div>
            </div>
            <div className="ac-stat-block">
              <div className="ac-stat-block-num" style={{ fontSize: "clamp(1.4rem, 2.2vw, 1.8rem)" }}>Per-client</div>
              <div className="ac-stat-block-label">Isolated encrypted vaults</div>
            </div>
            <div className="ac-stat-block">
              <div className="ac-stat-block-num" style={{ fontSize: "clamp(1.4rem, 2.2vw, 1.8rem)" }}>15-min</div>
              <div className="ac-stat-block-label">Rotating session tokens</div>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}

/* ═══════════════════════════════════════════════════
   PRODUCT-FACT CARD — P2.3 testimonial slot
   Swap copy + attribution once beta quote is approved.
   ═══════════════════════════════════════════════════ */
function ProductFact() {
  return (
    <section className="ac-section ac-zone-neutral ac-section-compact">
      <div className="ac-container">
        <figure className="ac-fact-card">
          <svg className="ac-fact-mark" viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" strokeWidth="1.5">
            <path d="M7 8h4v4c0 3-2 5-4 6M15 8h4v4c0 3-2 5-4 6" />
          </svg>
          <blockquote className="ac-fact-quote">
            Every answer is signed with a SHA-256 hash the moment it's generated — verifiable years later with no network call, exportable as PDF or JSON.
          </blockquote>
          <figcaption className="ac-fact-attribution">
            <span className="ac-fact-role">How AetherCloud proves its work</span>
            <span className="ac-fact-divider" />
            <span className="ac-fact-meta">Cryptographic audit chain · in every tier</span>
          </figcaption>
        </figure>
      </div>
    </section>
  );
}

/* ═══════════════════════════════════════════════════
   AUDIENCE + PILLARS — P1.2 real visuals, P3.1 bridge
   ═══════════════════════════════════════════════════ */

/* — Inline SVG pillar illustrations. Replace with real
     app screenshots (<img>) once available. — */

function VaultIllustration() {
  return (
    <svg className="ac-pillar-visual" viewBox="0 0 320 180" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
      <defs>
        <linearGradient id="vault-bg" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" stopColor="#140b24" />
          <stop offset="100%" stopColor="#0a0714" />
        </linearGradient>
        <linearGradient id="vault-door" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#8b5cf6" stopOpacity="0.28" />
          <stop offset="100%" stopColor="#6d28d9" stopOpacity="0.14" />
        </linearGradient>
      </defs>
      <rect width="320" height="180" fill="url(#vault-bg)" />
      {/* grid */}
      <g stroke="rgba(167,139,250,0.10)" strokeWidth="1">
        {[...Array(9)].map((_, i) => (
          <line key={`v-${i}`} x1={i * 40} y1="0" x2={i * 40} y2="180" />
        ))}
        {[...Array(5)].map((_, i) => (
          <line key={`h-${i}`} x1="0" y1={i * 40} x2="320" y2={i * 40} />
        ))}
      </g>
      {/* vault door */}
      <rect x="95" y="32" width="130" height="116" rx="8" fill="url(#vault-door)" stroke="#a78bfa" strokeWidth="1.2" />
      <circle cx="160" cy="90" r="30" fill="none" stroke="#a78bfa" strokeWidth="1.2" />
      <circle cx="160" cy="90" r="16" fill="none" stroke="#a78bfa" strokeWidth="1" opacity="0.7" />
      {/* spokes */}
      {[0, 60, 120, 180, 240, 300].map((a) => (
        <line
          key={a}
          x1={160 + Math.cos((a * Math.PI) / 180) * 30}
          y1={90 + Math.sin((a * Math.PI) / 180) * 30}
          x2={160 + Math.cos((a * Math.PI) / 180) * 40}
          y2={90 + Math.sin((a * Math.PI) / 180) * 40}
          stroke="#a78bfa" strokeWidth="1.2"
        />
      ))}
      <circle cx="160" cy="90" r="4" fill="#a78bfa" />
      {/* bolts */}
      {[[110, 44], [210, 44], [110, 136], [210, 136]].map(([x, y], i) => (
        <circle key={i} cx={x} cy={y} r="2.5" fill="#a78bfa" opacity="0.7" />
      ))}
      {/* file indicators below */}
      <g fontFamily="IBM Plex Mono, monospace" fontSize="7" fill="#a78bfa" opacity="0.7">
        <text x="20" y="165">client-a.enc</text>
        <text x="85" y="165">case-2026.enc</text>
        <text x="175" y="165">nda-draft.enc</text>
        <text x="245" y="165">exhibits.enc</text>
      </g>
    </svg>
  );
}

function AuditIllustration() {
  return (
    <svg className="ac-pillar-visual" viewBox="0 0 320 180" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
      <defs>
        <linearGradient id="audit-bg" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" stopColor="#140b24" />
          <stop offset="100%" stopColor="#0a0714" />
        </linearGradient>
        <marker id="arr" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="5" markerHeight="5" orient="auto-start-reverse">
          <path d="M0,0 L10,5 L0,10 z" fill="#a78bfa" />
        </marker>
      </defs>
      <rect width="320" height="180" fill="url(#audit-bg)" />
      {/* chain of blocks */}
      {[0, 1, 2, 3].map((i) => {
        const x = 22 + i * 76;
        return (
          <g key={i}>
            <rect x={x} y="56" width="62" height="68" rx="3"
              fill="rgba(139,92,246,0.08)"
              stroke="#a78bfa" strokeWidth="1.1" />
            <text x={x + 31} y="76" textAnchor="middle" fontFamily="IBM Plex Mono, monospace" fontSize="8" fill="#c4b5fd">
              #{1024 + i}
            </text>
            <line x1={x + 8} y1="86" x2={x + 54} y2="86" stroke="#a78bfa" strokeOpacity="0.3" />
            <text x={x + 31} y="100" textAnchor="middle" fontFamily="IBM Plex Mono, monospace" fontSize="6.2" fill="#a78bfa" opacity="0.85">
              sha256
            </text>
            <text x={x + 31} y="112" textAnchor="middle" fontFamily="IBM Plex Mono, monospace" fontSize="6" fill="#f4f1ea" opacity="0.55">
              {["a3f9…c7", "b1e4…9d", "d8c2…42", "e0f5…88"][i]}
            </text>
            {i < 3 && (
              <path d={`M${x + 62} 90 L${x + 76} 90`} stroke="#a78bfa" strokeWidth="1" markerEnd="url(#arr)" />
            )}
          </g>
        );
      })}
      {/* timestamp rail */}
      <g fontFamily="IBM Plex Mono, monospace" fontSize="7" fill="#a78bfa" opacity="0.65">
        <text x="24" y="146">14:02:07</text>
        <text x="100" y="146">14:02:31</text>
        <text x="176" y="146">14:03:04</text>
        <text x="252" y="146">14:03:42</text>
      </g>
      <line x1="20" y1="152" x2="300" y2="152" stroke="#a78bfa" strokeOpacity="0.25" />
      <text x="20" y="168" fontFamily="IBM Plex Mono, monospace" fontSize="7" fill="#f4f1ea" opacity="0.5">
        Signed chain · exportable PDF / JSON
      </text>
    </svg>
  );
}

function GhostProxyIllustration() {
  return (
    <svg className="ac-pillar-visual" viewBox="0 0 320 180" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
      <defs>
        <linearGradient id="gp-bg" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" stopColor="#140b24" />
          <stop offset="100%" stopColor="#0a0714" />
        </linearGradient>
        <radialGradient id="gp-glow" cx="50%" cy="50%" r="50%">
          <stop offset="0%" stopColor="#a78bfa" stopOpacity="0.35" />
          <stop offset="100%" stopColor="#a78bfa" stopOpacity="0" />
        </radialGradient>
      </defs>
      <rect width="320" height="180" fill="url(#gp-bg)" />
      {/* three concentric orbits (token rotation) */}
      <g fill="none" stroke="#a78bfa" strokeWidth="1">
        <ellipse cx="160" cy="90" rx="120" ry="42" opacity="0.25" />
        <ellipse cx="160" cy="90" rx="88"  ry="30" opacity="0.4" />
        <ellipse cx="160" cy="90" rx="56"  ry="19" opacity="0.6" />
      </g>
      {/* your machine */}
      <g transform="translate(26 72)">
        <rect width="40" height="32" rx="3" fill="rgba(139,92,246,0.18)" stroke="#a78bfa" strokeWidth="1.1" />
        <rect x="6" y="6" width="28" height="18" rx="1" fill="none" stroke="#a78bfa" strokeWidth="0.8" />
        <text x="20" y="44" textAnchor="middle" fontFamily="IBM Plex Mono, monospace" fontSize="7" fill="#a78bfa">you</text>
      </g>
      {/* ghost node (middle) */}
      <circle cx="160" cy="90" r="30" fill="url(#gp-glow)" />
      <circle cx="160" cy="90" r="14" fill="none" stroke="#a78bfa" strokeWidth="1.1" />
      <circle cx="160" cy="90" r="3" fill="#a78bfa" />
      <text x="160" y="140" textAnchor="middle" fontFamily="IBM Plex Mono, monospace" fontSize="7" fill="#a78bfa" opacity="0.85">
        ghost proxy · token rotates 15m
      </text>
      {/* vendor */}
      <g transform="translate(254 72)">
        <rect width="40" height="32" rx="3" fill="rgba(139,92,246,0.10)" stroke="#a78bfa" strokeWidth="1.1" strokeDasharray="3 2" />
        <text x="20" y="20" textAnchor="middle" fontFamily="IBM Plex Mono, monospace" fontSize="6.5" fill="#a78bfa" opacity="0.7">api</text>
        <text x="20" y="44" textAnchor="middle" fontFamily="IBM Plex Mono, monospace" fontSize="7" fill="#a78bfa">vendor</text>
      </g>
      {/* dotted connection lines */}
      <path d="M66 88 L130 90" stroke="#a78bfa" strokeDasharray="2 3" strokeWidth="1" />
      <path d="M190 90 L254 88" stroke="#a78bfa" strokeDasharray="2 3" strokeWidth="1" />
      {/* rotating token tick marks */}
      {[...Array(8)].map((_, i) => {
        const a = (i * 45 * Math.PI) / 180;
        return (
          <circle key={i} cx={160 + Math.cos(a) * 30} cy={90 + Math.sin(a) * 30} r="1.5" fill="#c4b5fd" />
        );
      })}
    </svg>
  );
}

function AudienceAndPillars() {
  const personas = [
    {
      icon: <svg viewBox="0 0 24 24"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" /><circle cx="12" cy="7" r="4" /></svg>,
      title: "Solo lawyer",
      desc: "You draft motions at 11 pm and you're done pasting client exhibits into ChatGPT.",
    },
    {
      icon: <svg viewBox="0 0 24 24"><path d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" /></svg>,
      title: "Compliance consultant",
      desc: "Clients pay you to read their contracts. You need to show which clauses the AI flagged and why.",
    },
    {
      icon: <svg viewBox="0 0 24 24"><circle cx="11" cy="11" r="8" /><path d="m21 21-4.35-4.35" /></svg>,
      title: "Indie researcher",
      desc: "Your source material must never train someone else's model.",
    },
  ];

  return (
    <section className="ac-section ac-zone-iris">
      <div className="ac-container">
        {/* Audience */}
        <div className="ac-grid-header-2">
          <div>
            <span className="ac-text-label">Built for</span>
            <h2 className="ac-text-display">The work where a leak costs you a client</h2>
          </div>
          <div style={{ display: "flex", alignItems: "center" }}>
            <p className="ac-text-body-lg">
              You know the files that matter — the ones where exposure ends a relationship or breaks a regulation. AetherCloud is built for that work.
            </p>
          </div>
        </div>
        <div className="ac-grid-3" style={{ marginBottom: "5rem" }}>
          {personas.map((p) => (
            <div key={p.title} className="ac-glass-card">
              <div className="ac-feat-icon">{p.icon}</div>
              <h3 className="ac-text-h3" style={{ marginBottom: ".6rem" }}>{p.title}</h3>
              <p className="ac-text-body">{p.desc}</p>
            </div>
          ))}
        </div>

        {/* Pillars */}
        <div className="ac-grid-header-2">
          <div>
            <span className="ac-text-label">Provable</span>
            <h2 className="ac-text-display">Three things no chatbot gives you</h2>
          </div>
          <div style={{ display: "flex", alignItems: "center" }}>
            <p className="ac-text-body-lg">
              Your files stay locked in your vault. Every answer comes back signed. Your traffic never touches our servers. That's the difference between a chatbot and proof.
            </p>
          </div>
        </div>

        <div className="ac-grid-3">
          <div className="ac-glass-card ac-pillar-card">
            <VaultIllustration />
            <h3 className="ac-text-h3" style={{ marginBottom: ".6rem" }}>Vault</h3>
            <p className="ac-text-body">
              Files live in your vault, not ours — isolated, encrypted, indexed in place, never pooled with anyone else's data.
            </p>
          </div>
          <div className="ac-glass-card ac-pillar-card">
            <AuditIllustration />
            <h3 className="ac-text-h3" style={{ marginBottom: ".6rem" }}>Audit chain</h3>
            <p className="ac-text-body">
              Every answer signed with SHA-256, timestamped forever, exportable as PDF or JSON for regulators and clients.
            </p>
          </div>
          <div className="ac-glass-card ac-pillar-card">
            <GhostProxyIllustration />
            <h3 className="ac-text-h3" style={{ marginBottom: ".6rem" }}>Ghost proxy</h3>
            {/* P3.1 bridge sentence to Aether Protocol */}
            <p className="ac-text-body">
              Your IP never reaches our servers — 15-minute rotating tokens, zero-trust routing, 40-pattern injection screen.
            </p>
            <p className="ac-text-body" style={{ marginTop: ".8rem", fontSize: "0.8125rem" }}>
              Same moving-target technology that powers Aether's enterprise defense stack.{" "}
              <Link to={PROTOCOL_URL} className="ac-link-arrow ac-link-inline">
                Learn about Aether Protocol →
              </Link>
            </p>
          </div>
        </div>
      </div>
    </section>
  );
}

/* ═══════════════════════════════════════════════════
   PRICING CARD
   Free tier downloads the installer directly.
   Paid tiers link to app.aethersystems.net (the /site/ Next.js app that
   owns the Subscribe → Stripe flow). The deep-link #tier-<slug> lets
   that page auto-scroll + highlight the matching tier card.
   ═══════════════════════════════════════════════════ */
function PricingCard({ tier }) {
  const checkoutHref = TIER_CHECKOUT_LINKS[tier.name];
  const isFree       = !checkoutHref;
  const btnClass     = tier.featured ? "ac-btn-primary" : "ac-btn-ghost";
  const btnStyle     = { textAlign: "center", justifyContent: "center", marginBottom: 0 };
  // Free tier: in-site link to DOWNLOAD_URL. Paid: cross-origin link to
  // the checkout app; open in same tab so the user doesn't lose context.
  const href = isFree ? tier.href : checkoutHref;

  return (
    <div className={`ac-pricing-card ${tier.featured ? "ac-featured" : ""}`}>
      <p className="ac-pricing-name">{tier.name}</p>
      <p className="ac-pricing-desc">{tier.desc}</p>
      <div className="ac-pricing-divider" />
      <div className="ac-pricing-price">{tier.price}</div>
      <p className="ac-pricing-period">{tier.period}</p>
      <a href={href} className={btnClass} style={btnStyle}>
        {tier.cta}
      </a>
      <div className="ac-pricing-divider" />
      <div className="ac-pricing-features">
        {tier.features.map((f) => (
          <div key={f} className="ac-pricing-feature">
            <svg viewBox="0 0 16 16"><path d="M3 8l3.5 3.5 6.5-7" strokeLinecap="round" /></svg>
            {f}
          </div>
        ))}
      </div>
    </div>
  );
}

/* ═══════════════════════════════════════════════════
   HOW IT WORKS + PRICING
   ═══════════════════════════════════════════════════ */
function HowAndPricing() {
  const [tab, setTab] = useState("monthly");

  const monthly = [
    { name: "Free",         desc: "Try it on real work", price: "$0",  period: "/ forever · Limited tokens", featured: false, cta: "Download free",       href: DOWNLOAD_URL, features: ["2GB encrypted vault", "Signed audit chain", "Capped monthly tokens"] },
    { name: "Solo",         desc: "For individuals",     price: "$19.99", period: "/ month",                 featured: false, cta: "Start solo",          href: UPGRADE_URL,  features: ["10GB encrypted vault", "Signed audit chain", "Injection protection"] },
    { name: "Professional", desc: "For consultants",     price: "$49", period: "/ month",                    featured: true,  cta: "Start professional",  href: UPGRADE_URL,  features: ["50GB encrypted vault", "MCP tool integration", "Priority routing", "One teammate seat"] },
    { name: "Team",         desc: "For small teams",     price: "$89", period: "/ month",                    featured: false, cta: "Start team",          href: UPGRADE_URL,  features: ["200GB encrypted vault", "Five team seats", "Compliance exports", "Dedicated support", "Custom integrations"] },
  ];
  const yearly = [
    { name: "Free",         desc: "Try it on real work", price: "$0",   period: "/ forever · Limited tokens", featured: false, cta: "Download free",      href: DOWNLOAD_URL, features: ["2GB encrypted vault", "Signed audit chain", "Capped monthly tokens"] },
    { name: "Solo",         desc: "For individuals",     price: "$189", period: "/ year · Save 21%",          featured: false, cta: "Start solo",         href: UPGRADE_URL,  features: ["10GB encrypted vault", "Signed audit chain", "Injection protection"] },
    { name: "Professional", desc: "For consultants",     price: "$588", period: "/ year · Save 20%",          featured: true,  cta: "Start professional", href: UPGRADE_URL,  features: ["50GB encrypted vault", "MCP tool integration", "Priority routing", "One teammate seat"] },
    { name: "Team",         desc: "For small teams",     price: "$960", period: "/ year · Save 20%",          featured: false, cta: "Start team",         href: UPGRADE_URL,  features: ["200GB encrypted vault", "Five team seats", "Compliance exports", "Dedicated support", "Custom integrations"] },
  ];
  const tiers = tab === "monthly" ? monthly : yearly;

  return (
    <section id="ac-how-it-works" className="ac-section ac-zone-neutral">
      <div className="ac-container">
        {/* How it works */}
        <div className="ac-section-header">
          <span className="ac-text-label">Simple</span>
          <h2 className="ac-text-display" style={{ marginBottom: "0.75rem" }}>
            Install, drop files in, ask
          </h2>
          <p className="ac-text-body">Two minutes to running. No setup, no sales call, no waiting for enterprise approval.</p>
        </div>
        <div className="ac-steps-grid" style={{ marginBottom: "6rem" }}>
          <div>
            <div className="ac-step-num">1</div>
            <h3 className="ac-text-h3" style={{ marginBottom: ".6rem" }}>Install the desktop app</h3>
            <p className="ac-text-body">One click, two minutes, you're done.</p>
          </div>
          <div>
            <div className="ac-step-num">2</div>
            <h3 className="ac-text-h3" style={{ marginBottom: ".6rem" }}>Drop your project into the vault</h3>
            <p className="ac-text-body">It encrypts and indexes in place, ready to search.</p>
          </div>
          <div>
            <div className="ac-step-num">3</div>
            <h3 className="ac-text-h3" style={{ marginBottom: ".6rem" }}>Ask your agent anything</h3>
            <p className="ac-text-body">Every answer comes back with a verifiable signature.</p>
          </div>
        </div>

        {/* Pricing */}
        <div className="ac-section-header">
          <span className="ac-text-label">Pricing</span>
          <h2 className="ac-text-display" style={{ marginBottom: "0.75rem" }}>Simple plans</h2>
          <p className="ac-text-body">Start free. Upgrade when you need more.</p>
        </div>
        <div className="ac-pricing-tabs">
          <button className={`ac-pricing-tab ${tab === "monthly" ? "ac-active" : ""}`} onClick={() => setTab("monthly")}>Monthly</button>
          <button className={`ac-pricing-tab ${tab === "yearly"  ? "ac-active" : ""}`} onClick={() => setTab("yearly")}>Yearly</button>
        </div>
        <div className="ac-pricing-grid ac-pricing-grid-4">
          {tiers.map((tier) => (
            <PricingCard key={tier.name + tab} tier={tier} />
          ))}
        </div>
      </div>
    </section>
  );
}

/* ═══════════════════════════════════════════════════
   CTA — P1.3 single block, no more duplicate
   ═══════════════════════════════════════════════════ */
function CTA() {
  return (
    <section className="ac-section ac-zone-amber" style={{ position: "relative", overflow: "hidden" }}>
      <div style={{
        position: "absolute", inset: 0, zIndex: 0, pointerEvents: "none",
        backgroundImage: "url('/aether-cloud/bg_p6.webp')",
        backgroundSize: "cover", backgroundPosition: "center", backgroundRepeat: "no-repeat",
      }} />
      <div style={{
        position: "absolute", inset: 0, zIndex: 1, pointerEvents: "none",
        background: "linear-gradient(135deg, rgba(12,10,20,0.82) 0%, rgba(12,10,20,0.55) 50%, rgba(12,10,20,0.82) 100%)",
      }} />
      <div className="ac-container" style={{ position: "relative", zIndex: 2 }}>
        <div className="ac-cta-single">
          <div className="ac-cta-icon">
            <svg viewBox="0 0 48 48" fill="none">
              <rect width="48" height="48" rx="10" fill="rgba(139,92,246,0.14)" />
              <circle cx="24" cy="24" r="11" stroke="#a78bfa" strokeWidth="1.5" />
              <path d="M24 14L29 22H19L24 14Z" stroke="#a78bfa" strokeWidth="1.2" fill="none" />
              <circle cx="24" cy="24" r="3" fill="#a78bfa" />
            </svg>
          </div>
          <h2 className="ac-text-display" style={{ marginBottom: "0.75rem" }}>Stop pasting files</h2>
          <p className="ac-text-body-lg" style={{ marginBottom: "2rem", maxWidth: 560, margin: "0 auto 2rem" }}>
            Install AetherCloud. Drop your files in. Ask. Every answer comes back signed.
          </p>
          <div style={{ display: "flex", justifyContent: "center", gap: "1rem", flexWrap: "wrap" }}>
            <a href={DOWNLOAD_URL} className="ac-btn-primary">Download free</a>
            <Link to={DOCS_URL} className="ac-btn-ghost">See docs</Link>
          </div>
        </div>
      </div>
    </section>
  );
}

/* ═══════════════════════════════════════════════════
   FRAME 2 — scroll-activated popup reveal
   Rises from below with an OPPOSING dark wipe that
   peels upward, meeting Hero's closing fade in the
   middle. Placeholder content; swap the inner panel
   for a real <video> once the asset is ready.
   ═══════════════════════════════════════════════════ */
function Frame2() {
  const containerRef = useRef(null);
  const panelRef = useRef(null);
  const wipeRef = useRef(null);
  const contentRef = useRef(null);

  useEffect(() => {
    const container = containerRef.current;
    const panel = panelRef.current;
    const wipe = wipeRef.current;
    const content = contentRef.current;
    if (!container || !panel || !wipe) return;

    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
    const norm = (v, lo, hi) => clamp((v - lo) / (hi - lo), 0, 1);

    // Initial state — panel sits below the viewport, wipe fully covers it
    if (!reduced) {
      panel.style.transform = "translateY(60%) scale(0.92)";
      panel.style.opacity = "0";
      wipe.style.transform = "translateY(0%)";
      if (content) content.style.opacity = "0";
    }

    const st = ScrollTrigger.create({
      trigger: container,
      start: "top bottom",   // begin when section's top enters viewport bottom
      end: "center center",  // finish when section's center hits viewport center
      scrub: reduced ? 0.6 : 0.2,
      onUpdate(self) {
        const p = self.progress; // 0 → 1 across the reveal

        // Panel rises into place (0.60 offset-y → 0, scale 0.92 → 1)
        const ty = (1 - p) * 60;             // translateY % — starts at 60%, ends 0
        const sc = 0.92 + p * 0.08;          // scale 0.92 → 1.00
        panel.style.transform = `translateY(${ty}%) scale(${sc})`;
        panel.style.opacity = clamp(norm(p, 0.10, 0.50), 0, 1);

        // Wipe peels UPWARD (opposite direction from Hero's closing fade).
        // At p=0 the wipe covers the panel (translateY 0%).
        // At p=1 the wipe has slid up out of frame (translateY -100%).
        wipe.style.transform = `translateY(${-p * 100}%)`;

        // Content inside the panel fades in during the last third
        if (content) content.style.opacity = clamp(norm(p, 0.55, 0.95), 0, 1);
      },
    });

    return () => st.kill();
  }, []);

  return (
    <section
      ref={containerRef}
      id="ac-frame2"
      aria-label="AetherCloud — next frame"
    >
      <div ref={panelRef} className="ac-frame2-panel">
        {/* ── FRAME 2 CONTENT SLOT ──
            When the Frame 2 video is ready, replace the inner <div
            className="ac-frame2-placeholder"> with:
              <video
                className="ac-frame2-video"
                muted playsInline autoPlay loop
                poster="/aether-cloud/frame2_poster.webp"
              >
                <source src="/aether-cloud/frame2.mp4" type="video/mp4" />
              </video>
            …and delete the placeholder headline.                              */}
        <div className="ac-frame2-placeholder">
          <div ref={contentRef} className="ac-frame2-content">
            <span className="ac-eyebrow" style={{ justifyContent: "center" }}>
              <span className="ac-eyebrow-line" />
              <span className="ac-eyebrow-dot" />
              Frame 2 · placeholder
            </span>
            <h2 className="ac-text-display" style={{ textAlign: "center", marginTop: "1rem" }}>
              The vault opens
            </h2>
            <p className="ac-text-body-lg" style={{ textAlign: "center", maxWidth: 520, margin: "1rem auto 0" }}>
              Replace this panel with the Frame 2 video when the asset is ready.
            </p>
          </div>
        </div>
        {/* Opposing dark wipe — covers the panel, peels UPWARD on scroll */}
        <div ref={wipeRef} className="ac-frame2-wipe" aria-hidden="true" />
      </div>
    </section>
  );
}

/* ═══════════════════════════════════════════════════
   PAGE EXPORT — P2.2 order:
   Hero → TrustStrip → Comparison → Stats → Fact
   → Audience+Pillars → How+Pricing → CTA
   ═══════════════════════════════════════════════════ */
export default function AetherCloudPage() {
  return (
    <div className="ac-page">
      <Hero />
      <Frame2 />
      <TrustStrip />
      <Comparison />
      <Stats />
      <ProductFact />
      <AudienceAndPillars />
      <HowAndPricing />
      <CTA />
    </div>
  );
}
