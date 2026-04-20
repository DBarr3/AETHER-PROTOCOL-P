"use client";

import { Button } from "@relume_io/relume-ui";
import React from "react";

export function Faq14() {
  return (
    <section id="relume" className="px-[5%] py-16 md:py-24 lg:py-28">
      <div className="container">
        <div className="mx-auto mb-12 w-full max-w-lg text-center md:mb-18 lg:mb-20">
          <h2 className="rb-5 mb-5 text-5xl font-bold md:mb-6 md:text-7xl lg:text-8xl">
            Demo FAQ
          </h2>
          <p className="md:text-md">
            Common questions about signed receipts, verification, and how the
            demo works.
          </p>
        </div>
        <div className="container grid grid-cols-1 items-start justify-center gap-y-12 md:grid-cols-3 md:gap-x-8 md:gap-y-16 lg:gap-x-12 lg:gap-y-16">
          <div className="flex w-full flex-col items-center text-center">
            <div className="rb-5 mb-5 md:mb-6">
              <svg className="size-12" viewBox="0 0 48 48" fill="none"><rect x="6" y="6" width="36" height="36" rx="4" stroke="currentColor" strokeWidth="2"/><path d="M16 24h16M16 18h16M16 30h10" stroke="currentColor" strokeWidth="2" strokeLinecap="round"/></svg>
            </div>
            <h3 className="mb-3 font-bold md:mb-4 md:text-md">
              What goes into a signed receipt?
            </h3>
            <p>
              Every receipt contains a SHA-256 hash of the AI output, an
              independent timestamp from a third-party authority, and a
              quantum-seeded JWT that rotates every fifteen minutes. Together
              they form an unforgeable proof of what was generated and when.
            </p>
          </div>
          <div className="flex w-full flex-col items-center text-center">
            <div className="rb-5 mb-5 md:mb-6">
              <svg className="size-12" viewBox="0 0 48 48" fill="none"><path d="M8 24h32" stroke="currentColor" strokeWidth="2" strokeLinecap="round"/><path d="M14 12v24M24 8v32M34 14v20" stroke="currentColor" strokeWidth="2" strokeLinecap="round"/></svg>
            </div>
            <h3 className="mb-3 font-bold md:mb-4 md:text-md">
              How is this different from a log file?
            </h3>
            <p>
              Logs can be edited, backdated, or deleted after the fact. A signed
              receipt cannot be modified because any change breaks the
              cryptographic signature. The proof is mathematical, not
              procedural.
            </p>
          </div>
          <div className="flex w-full flex-col items-center text-center">
            <div className="rb-5 mb-5 md:mb-6">
              <svg className="size-12" viewBox="0 0 48 48" fill="none"><circle cx="24" cy="24" r="16" stroke="currentColor" strokeWidth="2"/><path d="M18 24l4 4 8-8" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"/></svg>
            </div>
            <h3 className="mb-3 font-bold md:mb-4 md:text-md">
              Can an auditor verify this independently?
            </h3>
            <p>
              Yes. The hash, timestamp, and JWT signature are all independently
              verifiable using aetherctl or standard cryptographic tools. No
              trust in AetherCloud is required -- the math speaks for itself.
            </p>
          </div>
          <div className="flex w-full flex-col items-center text-center">
            <div className="rb-5 mb-5 md:mb-6">
              <svg className="size-12" viewBox="0 0 48 48" fill="none"><path d="M24 4L8 12v12c0 10 7 18 16 20 9-2 16-10 16-20V12L24 4z" stroke="currentColor" strokeWidth="2"/><path d="M18 24l4 4 8-8" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/></svg>
            </div>
            <h3 className="mb-3 font-bold md:mb-4 md:text-md">
              Does this satisfy compliance requirements?
            </h3>
            <p>
              Signed receipts satisfy audit trail requirements for SOC 2 Type
              II, HIPAA, and the EU AI Act because the proof is cryptographic,
              not based on self-reported controls. Auditors verify the math
              directly.
            </p>
          </div>
          <div className="flex w-full flex-col items-center text-center">
            <div className="rb-5 mb-5 md:mb-6">
              <svg className="size-12" viewBox="0 0 48 48" fill="none"><rect x="8" y="16" width="32" height="20" rx="3" stroke="currentColor" strokeWidth="2"/><path d="M16 16V12a8 8 0 0116 0v4" stroke="currentColor" strokeWidth="2"/><circle cx="24" cy="28" r="3" fill="currentColor"/></svg>
            </div>
            <h3 className="mb-3 font-bold md:mb-4 md:text-md">
              Is my data safe during the demo?
            </h3>
            <p>
              The demo runs entirely in your browser. In production, Ghost Proxy
              ensures AetherCloud never sees your content -- signing happens
              inside your isolated vault with your keys, so your data never
              leaves your control.
            </p>
          </div>
          <div className="flex w-full flex-col items-center text-center">
            <div className="rb-5 mb-5 md:mb-6">
              <svg className="size-12" viewBox="0 0 48 48" fill="none"><circle cx="24" cy="24" r="16" stroke="currentColor" strokeWidth="2"/><path d="M24 16v8l6 4" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/></svg>
            </div>
            <h3 className="mb-3 font-bold md:mb-4 md:text-md">
              How often do signing keys rotate?
            </h3>
            <p>
              Quantum-seeded signing keys rotate every fifteen minutes by
              default. Each rotation uses fresh entropy from our quantum random
              number generator, making key prediction mathematically impossible
              even with advance knowledge of prior keys.
            </p>
          </div>
        </div>
        <div className="mt-12 text-center md:mt-18 lg:mt-20">
          <h4 className="mb-3 text-2xl font-bold md:mb-4 md:text-3xl md:leading-[1.3] lg:text-4xl">
            Want the full technical breakdown?
          </h4>
          <p className="md:text-md">
            Read our documentation for protocol specs, SDK guides, and
            architecture deep dives.
          </p>
          <div className="mt-6 md:mt-8">
            <Button title="Read the Docs" variant="secondary">
              Read the Docs
            </Button>
          </div>
        </div>
      </div>
    </section>
  );
}
