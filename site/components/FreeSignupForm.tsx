"use client";

import { useState } from "react";
import { track } from "@/lib/track";

export function FreeSignupForm() {
  const [email, setEmail] = useState("");
  const [state, setState] = useState<"idle" | "submitting" | "done" | "error">("idle");
  const [error, setError] = useState<string | null>(null);

  const freeSignupUrl = process.env.NEXT_PUBLIC_SUPABASE_FREE_SIGNUP_URL ?? "";

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (state === "submitting") return;
    if (!freeSignupUrl) {
      setError("signup endpoint not configured");
      setState("error");
      return;
    }

    track.signupStarted("pricing_page");
    setState("submitting");
    setError(null);

    try {
      const res = await fetch(freeSignupUrl, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: email.trim().toLowerCase() }),
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(body.error ?? `signup failed (${res.status})`);

      track.signupCompleted({ method: "email" });
      window.location.href = "/success";
    } catch (e) {
      setError((e as Error).message);
      setState("error");
    }
  }

  return (
    <form onSubmit={onSubmit} className="flex flex-col gap-2">
      <input
        type="email"
        required
        value={email}
        onChange={(e) => setEmail(e.target.value)}
        placeholder="you@example.com"
        className="px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-black"
        disabled={state === "submitting"}
      />
      <button
        type="submit"
        disabled={state === "submitting" || !email}
        className="w-full py-2 px-4 rounded-lg bg-black text-white font-medium hover:bg-gray-800 disabled:opacity-50"
      >
        {state === "submitting" ? "Signing up…" : "Get started free"}
      </button>
      {error && <p className="text-xs text-red-600 mt-1">{error}</p>}
    </form>
  );
}
