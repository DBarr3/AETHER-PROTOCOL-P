import React, { useState, useEffect, useRef } from "react";
import { useSearchParams } from "react-router-dom";
import { motion } from "framer-motion";

const SUPABASE_FUNCTIONS_URL = import.meta.env.VITE_SUPABASE_FUNCTIONS_URL || "";

const fadeUp = {
  hidden: { opacity: 0, y: 18 },
  show: (i = 0) => ({
    opacity: 1, y: 0,
    transition: { duration: 0.6, delay: 0.1 + i * 0.08, ease: [0.2, 0.8, 0.2, 1] },
  }),
};

const INTENTS = [
  { value: "sales",    label: "Sales" },
  { value: "support",  label: "Support" },
  { value: "security", label: "Security" },
  { value: "press",    label: "Press" },
  { value: "beta",     label: "Beta access" },
  { value: "careers",  label: "Careers" },
  { value: "general",  label: "General" },
];

const inputCls =
  "w-full bg-black border border-[#222] px-4 py-3 text-sm text-aether-text placeholder-aether-muted font-mono focus:border-aether-cyan focus:outline-none transition-colors";
const labelCls = "block font-mono text-xs uppercase tracking-[0.12em] text-aether-dim mb-2";

export default function ContactPage() {
  const [searchParams] = useSearchParams();
  const formRef = useRef(null);

  const preIntent  = searchParams.get("intent") || "general";
  const preProduct = searchParams.get("product") || "site_wide";
  const preCta     = searchParams.get("cta") || "contact_page_direct";

  const [intent, setIntent]   = useState(preIntent);
  const [status, setStatus]   = useState("idle"); // idle | sending | success | rate_limited | error
  const [errField, setErrField] = useState(null);

  useEffect(() => {
    if (searchParams.get("intent")) setIntent(searchParams.get("intent"));
  }, [searchParams]);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setErrField(null);
    const fd = new FormData(e.target);

    // Honeypot check
    const honeypot = fd.get("website") || "";

    const name    = (fd.get("name") || "").trim();
    const email   = (fd.get("email") || "").trim();
    const message = (fd.get("message") || "").trim();
    const company = (fd.get("company") || "").trim();
    const role    = (fd.get("role") || "").trim();

    if (!name)    { setErrField("name"); return; }
    if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)) { setErrField("email"); return; }
    if (message.length < 10) { setErrField("message"); return; }

    setStatus("sending");

    const payload = {
      intent,
      product: preProduct,
      name, email, message,
      company: company || null,
      role: role || null,
      source_path: window.location.pathname,
      source_cta: preCta,
      utm: Object.fromEntries([...searchParams].filter(([k]) => k.startsWith("utm_"))),
      honeypot,
    };

    try {
      const url = SUPABASE_FUNCTIONS_URL
        ? `${SUPABASE_FUNCTIONS_URL}/contact-submit`
        : "/api/contact-submit";

      const res = await fetch(url, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(payload),
      });

      const data = await res.json().catch(() => ({}));

      if (res.status === 429) {
        setStatus("rate_limited");
      } else if (res.ok && data.ok) {
        setStatus("success");
      } else {
        console.error("Contact submit error:", data);
        setStatus("error");
      }
    } catch (err) {
      console.error("Contact submit error:", err);
      setStatus("error");
    }
  };

  const showCompany = intent === "sales";
  const showRole    = intent === "sales" || intent === "careers";

  return (
    <div className="relative min-h-screen">
      <div className="mx-auto max-w-[680px] px-5 pb-24 pt-32">
        <motion.div initial="hidden" animate="show" variants={{ show: { transition: { staggerChildren: 0.08 } } }}>
          <motion.div custom={0} variants={fadeUp}>
            <p className="font-mono text-[11px] uppercase tracking-[0.18em] text-aether-cyan mb-4">
              Contact
            </p>
            <h1 className="font-mono text-[clamp(1.8rem,4vw,2.8rem)] font-semibold uppercase leading-[1.08] tracking-tight text-aether-text mb-4">
              Get in touch
            </h1>
            <p className="font-sans text-[15px] leading-relaxed text-aether-dim mb-10 max-w-lg">
              Demos, pilots, red team briefings, beta access, press — pick your intent and we'll route it to the right person.
            </p>
          </motion.div>

          {status === "success" ? (
            <motion.div custom={1} variants={fadeUp} className="border border-aether-cyan/30 bg-aether-cyan/5 p-8 text-center">
              <p className="font-mono text-sm text-aether-cyan mb-2">Message received</p>
              <p className="font-sans text-sm text-aether-dim">We got it. Expect a reply within 1 business day.</p>
            </motion.div>
          ) : status === "rate_limited" ? (
            <motion.div custom={1} variants={fadeUp} className="border border-yellow-500/30 bg-yellow-500/5 p-8 text-center">
              <p className="font-mono text-sm text-yellow-400 mb-2">Too many submissions</p>
              <p className="font-sans text-sm text-aether-dim">
                You've sent several already today. Email us directly at{" "}
                <span className="text-aether-cyan">contact@aethersecurity.io</span>
              </p>
            </motion.div>
          ) : (
            <motion.form
              ref={formRef}
              custom={1}
              variants={fadeUp}
              onSubmit={handleSubmit}
              className="space-y-6"
            >
              {/* Honeypot — invisible to users */}
              <input
                type="text"
                name="website"
                tabIndex={-1}
                autoComplete="off"
                style={{ position: "absolute", left: "-9999px" }}
              />

              {/* Intent selector */}
              <div>
                <label className={labelCls}>What's this about?</label>
                <div className="flex flex-wrap gap-2">
                  {INTENTS.map((i) => (
                    <button
                      key={i.value}
                      type="button"
                      onClick={() => setIntent(i.value)}
                      className={`px-3 py-1.5 text-xs font-mono uppercase tracking-[0.1em] border transition-colors ${
                        intent === i.value
                          ? "border-aether-cyan bg-aether-cyan/10 text-aether-cyan"
                          : "border-[#222] text-aether-muted hover:border-aether-dim"
                      }`}
                    >
                      {i.label}
                    </button>
                  ))}
                </div>
              </div>

              {/* Security disclosure banner */}
              {intent === "security" && (
                <div className="border border-aether-cyan/20 bg-aether-cyan/5 px-4 py-3 text-xs font-sans text-aether-dim">
                  For responsible disclosure with PGP, email{" "}
                  <span className="text-aether-cyan">security@aethersecurity.io</span>
                </div>
              )}

              {/* Name + Email */}
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div>
                  <label htmlFor="ct-name" className={labelCls}>
                    Name <span className="text-aether-cyan">*</span>
                  </label>
                  <input
                    id="ct-name"
                    name="name"
                    type="text"
                    required
                    maxLength={120}
                    placeholder="Your name"
                    className={inputCls}
                    aria-invalid={errField === "name" || undefined}
                  />
                  {errField === "name" && <p className="text-xs text-red-400 mt-1">Name is required</p>}
                </div>
                <div>
                  <label htmlFor="ct-email" className={labelCls}>
                    Email <span className="text-aether-cyan">*</span>
                  </label>
                  <input
                    id="ct-email"
                    name="email"
                    type="email"
                    required
                    placeholder="you@company.com"
                    className={inputCls}
                    aria-invalid={errField === "email" || undefined}
                  />
                  {errField === "email" && <p className="text-xs text-red-400 mt-1">Valid email required</p>}
                </div>
              </div>

              {/* Conditional: Company + Role */}
              {(showCompany || showRole) && (
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                  {showCompany && (
                    <div>
                      <label htmlFor="ct-company" className={labelCls}>
                        Company {intent === "sales" && <span className="text-aether-cyan">*</span>}
                      </label>
                      <input
                        id="ct-company"
                        name="company"
                        type="text"
                        required={intent === "sales"}
                        maxLength={160}
                        placeholder="Company name"
                        className={inputCls}
                      />
                    </div>
                  )}
                  {showRole && (
                    <div>
                      <label htmlFor="ct-role" className={labelCls}>
                        {intent === "careers" ? "Role applied for" : "Your role"}
                      </label>
                      <input
                        id="ct-role"
                        name="role"
                        type="text"
                        maxLength={120}
                        placeholder={intent === "careers" ? "e.g. Security Engineer" : "e.g. CISO"}
                        className={inputCls}
                      />
                    </div>
                  )}
                </div>
              )}

              {/* Message */}
              <div>
                <label htmlFor="ct-message" className={labelCls}>
                  Message <span className="text-aether-cyan">*</span>
                </label>
                <textarea
                  id="ct-message"
                  name="message"
                  required
                  minLength={10}
                  maxLength={4000}
                  rows={5}
                  placeholder="Tell us what you need..."
                  className={`${inputCls} resize-y`}
                  aria-invalid={errField === "message" || undefined}
                />
                {errField === "message" && <p className="text-xs text-red-400 mt-1">Message must be at least 10 characters</p>}
              </div>

              {/* Submit */}
              <button
                type="submit"
                disabled={status === "sending"}
                className="w-full sm:w-auto px-8 py-3 font-mono text-xs uppercase tracking-[0.16em] border border-aether-cyan bg-aether-cyan/10 text-aether-cyan transition-all hover:bg-aether-cyan hover:text-aether-bg disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {status === "sending" ? "Sending..." : "Send message"}
              </button>

              {status === "error" && (
                <p className="text-xs text-red-400">
                  Something went wrong. Email us at{" "}
                  <span className="text-aether-cyan">contact@aethersecurity.io</span>
                </p>
              )}
            </motion.form>
          )}
        </motion.div>
      </div>
    </div>
  );
}
