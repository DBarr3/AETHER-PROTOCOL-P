"use client";

import { useMediaQuery } from "@relume_io/relume-ui";
import { motion } from "framer-motion";
import React, { useState } from "react";
import { Link, NavLink } from "react-router-dom";
import { contactLink } from "../lib/contactLink.js";

const defenseItems = [
  {
    label: "AETHER-PREDATOR",
    sub: "Quantum Red Team Engine",
    to: "/#defense-stack",
    color: "#ef4444",
  },
  {
    label: "AETHER-SCRAMBLER",
    sub: "Ghost Protocol MTD",
    to: "/#defense-stack",
    color: "#06b6d4",
  },
];

const protocolItems = [
  {
    label: "AETHER PROTOCOL-L",
    sub: "Quantum Commitment Layer",
    to: "/protocol-family#protocol-l",
    color: "#06b6d4",
  },
  {
    label: "AETHER PROTOCOL-C",
    sub: "CSPRNG Commitment Layer",
    to: "/protocol-family#protocol-c",
    color: "#10b981",
  },
  {
    label: "AETHER PROTOCOL-T",
    sub: "TEE Attestation Layer",
    to: "/protocol-family#protocol-t",
    color: "#a78bfa",
  },
];

const useRelume = () => {
  const [isMobileMenuOpen, setIsMobileMenuOpen] = useState(false);
  const isMobile = useMediaQuery("(max-width: 991px)");
  const toggleMobileMenu = () => setIsMobileMenuOpen((prev) => !prev);
  const closeMobileMenu = () => setIsMobileMenuOpen(false);
  const animateMobileMenu = isMobileMenuOpen ? "open" : "close";
  const animateMobileMenuButtonSpan = isMobileMenuOpen
    ? ["open", "rotatePhase"]
    : "closed";
  return {
    isMobile,
    toggleMobileMenu,
    closeMobileMenu,
    animateMobileMenu,
    animateMobileMenuButtonSpan,
  };
};

function DropdownNav({ label, items, closeMobile }) {
  return (
    <div className="group relative">
      <button className="flex items-center gap-1.5 py-3 text-[11px] font-mono uppercase tracking-[0.18em] text-aether-dim transition-colors duration-200 hover:text-aether-text lg:px-4 lg:py-2">
        {label}
        <span className="text-[9px] opacity-70">▾</span>
      </button>
      <div className="invisible absolute left-0 top-full z-50 min-w-[240px] border border-aether-border bg-[#080e14] opacity-0 transition-all duration-150 group-hover:visible group-hover:opacity-100">
        {items.map((item) => (
          <Link
            key={item.label}
            to={item.to}
            onClick={closeMobile}
            className="block border-b border-[#0d2a35] px-4 py-2.5 font-mono text-[11px] uppercase tracking-[0.14em] transition-colors duration-150 last:border-b-0 hover:bg-[#0d2a35]"
            style={{ color: item.color }}
          >
            {item.label}
            <span className="mt-0.5 block text-[9px] normal-case tracking-[0.06em] text-aether-muted">
              {item.sub}
            </span>
          </Link>
        ))}
      </div>
    </div>
  );
}

export default function SiteNavbar() {
  const ui = useRelume();

  return (
    <header className="sticky top-0 z-50 w-full border-b border-aether-border bg-[rgba(4,5,7,0.78)] backdrop-blur-lg">
      <div className="mx-auto flex w-full max-w-[1400px] items-center justify-between px-[5%] lg:min-h-[52px] lg:px-8">
        <Link
          to="/"
          className="flex items-center gap-3 py-3"
          onClick={ui.closeMobileMenu}
        >
          <span className="border border-aether-border px-3 py-1.5 font-mono text-[11px] uppercase tracking-[0.22em] text-aether-text">
            AETHER AI
          </span>
        </Link>

        <nav className="hidden items-center gap-1 lg:flex">
          <DropdownNav
            label="Defense Stack"
            items={defenseItems}
            closeMobile={ui.closeMobileMenu}
          />
          <DropdownNav
            label="Protocol Family"
            items={protocolItems}
            closeMobile={ui.closeMobileMenu}
          />
          <NavLink
            to="/aether-cloud"
            className={({ isActive }) =>
              `py-3 text-[11px] font-mono uppercase tracking-[0.18em] transition-colors duration-200 hover:text-aether-text lg:px-4 lg:py-2 ${
                isActive ? "text-aether-text" : "text-aether-dim"
              }`
            }
          >
            Aether Cloud
          </NavLink>
        </nav>

        <Link
          to={contactLink({ intent: 'general', product: 'site_wide', cta: 'navbar_contact' })}
          className="hidden bg-aether-cyan-soft px-5 py-1.5 font-mono text-[11px] uppercase tracking-[0.22em] text-[#050a0f] transition-colors duration-200 hover:bg-[#22d3ee] lg:block"
        >
          Contact
        </Link>

        <button
          className="-mr-2 flex size-12 flex-col items-center justify-center lg:hidden"
          onClick={ui.toggleMobileMenu}
          aria-label="Toggle menu"
        >
          <motion.span
            className="my-[3px] h-0.5 w-6 bg-aether-text"
            animate={ui.animateMobileMenuButtonSpan}
            variants={{
              open: { translateY: 8, transition: { delay: 0.1 } },
              rotatePhase: { rotate: -45, transition: { delay: 0.2 } },
              closed: {
                translateY: 0,
                rotate: 0,
                transition: { duration: 0.2 },
              },
            }}
          />
          <motion.span
            className="my-[3px] h-0.5 w-6 bg-aether-text"
            animate={ui.animateMobileMenu}
            variants={{
              open: { width: 0, transition: { duration: 0.1 } },
              closed: {
                width: "1.5rem",
                transition: { delay: 0.3, duration: 0.2 },
              },
            }}
          />
          <motion.span
            className="my-[3px] h-0.5 w-6 bg-aether-text"
            animate={ui.animateMobileMenuButtonSpan}
            variants={{
              open: { translateY: -8, transition: { delay: 0.1 } },
              rotatePhase: { rotate: 45, transition: { delay: 0.2 } },
              closed: {
                translateY: 0,
                rotate: 0,
                transition: { duration: 0.2 },
              },
            }}
          />
        </button>
      </div>

      <motion.div
        variants={{
          open: { height: "var(--height-open, auto)", opacity: 1 },
          close: { height: 0, opacity: 0 },
        }}
        initial="close"
        animate={ui.animateMobileMenu}
        transition={{ duration: 0.3 }}
        className="overflow-hidden border-t border-aether-border bg-aether-bg lg:hidden"
      >
        <div className="px-[5%] py-6">
          <p className="mb-2 font-mono text-[9px] uppercase tracking-[0.2em] text-aether-muted">
            Defense Stack
          </p>
          {defenseItems.map((item) => (
            <Link
              key={item.label}
              to={item.to}
              onClick={ui.closeMobileMenu}
              className="block py-2 font-mono text-xs uppercase tracking-[0.14em]"
              style={{ color: item.color }}
            >
              {item.label}
            </Link>
          ))}
          <p className="mb-2 mt-4 font-mono text-[9px] uppercase tracking-[0.2em] text-aether-muted">
            Protocol Family
          </p>
          {protocolItems.map((item) => (
            <Link
              key={item.label}
              to={item.to}
              onClick={ui.closeMobileMenu}
              className="block py-2 font-mono text-xs uppercase tracking-[0.14em]"
              style={{ color: item.color }}
            >
              {item.label}
            </Link>
          ))}
          <Link
            to="/aether-cloud"
            onClick={ui.closeMobileMenu}
            className="mt-4 block py-2 font-mono text-xs uppercase tracking-[0.14em] text-aether-text"
          >
            Aether Cloud
          </Link>
          <Link
            to={contactLink({ intent: 'general', product: 'site_wide', cta: 'navbar_mobile_contact' })}
            onClick={ui.closeMobileMenu}
            className="mt-4 block w-full bg-aether-cyan-soft py-3 text-center font-mono text-xs uppercase tracking-[0.2em] text-[#050a0f]"
          >
            Contact
          </Link>
        </div>
      </motion.div>
    </header>
  );
}
