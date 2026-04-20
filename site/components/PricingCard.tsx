"use client";

import { useEffect, useRef, useState } from "react";
import { track } from "@/lib/track";
import type { Tier } from "@/lib/tiers";
import { FreeSignupForm } from "./FreeSignupForm";

export function PricingCard({ tier }: { tier: Tier }) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [highlight, setHighlight] = useState(false);
  const subscribeBtn = useRef<HTMLButtonElement | null>(null);

  // Deep-link handoff from aethersystems.net/aether-cloud.
  // The marketing SPA links paid CTAs to app.aethersystems.net/#tier-<key>.
  // When that hash matches this card's tier we scroll it into view, flash
  // a highlight, and focus the Subscribe button so Enter completes checkout.
  useEffect(() => {
    if (typeof window === "undefined") return;

    const applyHashFocus = () => {
      const target = `tier-${tier.key}`;
      if (window.location.hash.slice(1) !== target) return;
      // Defer one frame so layout is settled before scrolling.
      requestAnimationFrame(() => {
        document.getElementById(target)?.scrollIntoView({ behavior: "smooth", block: "center" });
        setHighlight(true);
        if (!tier.isFree) subscribeBtn.current?.focus();
        // Drop the highlight after the user has clearly seen it.
        window.setTimeout(() => setHighlight(false), 2400);
      });
    };

    applyHashFocus();
    window.addEventListener("hashchange", applyHashFocus);
    return () => window.removeEventListener("hashchange", applyHashFocus);
  }, [tier.key, tier.isFree]);

  async function onPaidSubscribe() {
    setLoading(true);
    setError(null);
    track.checkoutStarted({ tier: tier.key, price_id: "unknown" });
    try {
      const res = await fetch("/api/checkout", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ tier: tier.key }),
      });
      const body = await res.json().catch(() => ({} as { url?: string; error?: string }));
      if (!res.ok) {
        throw new Error(body.error ?? `checkout failed (${res.status})`);
      }
      if (!body.url) throw new Error("missing checkout url");
      window.location.href = body.url;
    } catch (e) {
      setError((e as Error).message);
      setLoading(false);
    }
  }

  const ringClass = highlight
    ? "ring-2 ring-blue-500 ring-offset-2 scroll-mt-24 transition-shadow"
    : "scroll-mt-24 transition-shadow";

  return (
    <div
      id={`tier-${tier.key}`}
      className={`flex flex-col border border-gray-200 rounded-xl p-6 bg-white shadow-sm ${ringClass}`}
    >
      <div className="mb-4">
        <h3 className="text-lg font-semibold">{tier.name}</h3>
        <p className="text-3xl font-bold mt-1">{tier.price}</p>
        <p className="text-sm text-gray-500 mt-1">{tier.tagline}</p>
      </div>
      <ul className="flex-1 space-y-2 mb-6 text-sm">
        {tier.features.map((f) => (
          <li key={f} className="flex items-start">
            <span className="mr-2">•</span>
            <span>{f}</span>
          </li>
        ))}
      </ul>
      {tier.isFree ? (
        <FreeSignupForm />
      ) : (
        <>
          <button
            ref={subscribeBtn}
            onClick={onPaidSubscribe}
            disabled={loading}
            className="w-full py-2 px-4 rounded-lg bg-black text-white font-medium hover:bg-gray-800 disabled:opacity-50"
          >
            {loading ? "Redirecting…" : tier.cta}
          </button>
          {error && <p className="text-xs text-red-600 mt-2">{error}</p>}
        </>
      )}
    </div>
  );
}
