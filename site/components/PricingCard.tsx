"use client";

import { useState } from "react";
import { track } from "@/lib/track";
import type { Tier } from "@/lib/tiers";
import { FreeSignupForm } from "./FreeSignupForm";

export function PricingCard({ tier }: { tier: Tier }) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

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
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.error ?? `checkout failed (${res.status})`);
      }
      const { url } = await res.json();
      if (!url) throw new Error("missing checkout url");
      window.location.href = url;
    } catch (e) {
      setError((e as Error).message);
      setLoading(false);
    }
  }

  return (
    <div className="flex flex-col border border-gray-200 rounded-xl p-6 bg-white shadow-sm">
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
