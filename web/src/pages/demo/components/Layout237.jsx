"use client";

import { Button } from "@relume_io/relume-ui";
import React from "react";
import { RxChevronRight } from "react-icons/rx";

export function Layout237() {
  return (
    <section id="relume" className="px-[5%] py-16 md:py-24 lg:py-28">
      <div className="container">
        <div className="flex flex-col items-center">
          <div className="rb-12 mb-12 w-full max-w-lg text-center md:mb-18 lg:mb-20">
            <p className="mb-3 font-semibold md:mb-4">Three Pillars of Proof</p>
            <h2 className="rb-5 mb-5 text-5xl font-bold md:mb-6 md:text-7xl lg:text-8xl">
              What makes a receipt tamper-evident
            </h2>
            <p className="md:text-md">
              Every output is cryptographically sealed the moment it leaves the
              model. Change one byte and the entire signature breaks. Here is
              exactly how that works.
            </p>
          </div>
          <div className="grid grid-cols-1 items-start justify-center gap-y-12 md:grid-cols-3 md:gap-x-8 md:gap-y-16 lg:gap-x-12">
            <div className="flex w-full flex-col items-center text-center">
              <div className="rb-5 mb-5 md:mb-6">
                <svg className="size-12 text-black" viewBox="0 0 48 48" fill="none" xmlns="http://www.w3.org/2000/svg">
                  <rect x="4" y="4" width="40" height="40" rx="4" stroke="currentColor" strokeWidth="2" />
                  <path d="M14 24h20M14 18h20M14 30h12" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
                  <path d="M32 28l4 4-4 4" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              </div>
              <h3 className="mb-5 text-2xl font-bold md:mb-6 md:text-3xl md:leading-[1.3] lg:text-4xl">
                SHA-256 Content Signing
              </h3>
              <p>
                Every AI output is hashed with SHA-256 at the moment of
                generation. The resulting digest is unique to that exact content
                -- alter a single character and the hash changes completely,
                instantly revealing tampering.
              </p>
            </div>
            <div className="flex w-full flex-col items-center text-center">
              <div className="rb-5 mb-5 md:mb-6">
                <svg className="size-12 text-black" viewBox="0 0 48 48" fill="none" xmlns="http://www.w3.org/2000/svg">
                  <circle cx="24" cy="24" r="18" stroke="currentColor" strokeWidth="2" />
                  <circle cx="24" cy="24" r="6" fill="currentColor" />
                  <path d="M24 6v4M24 38v4M6 24h4M38 24h4M10 10l3 3M35 35l3 3M10 38l3-3M35 13l3-3" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
                </svg>
              </div>
              <h3 className="mb-5 text-2xl font-bold md:mb-6 md:text-3xl md:leading-[1.3] lg:text-4xl">
                Quantum-Seeded Entropy
              </h3>
              <p>
                JWT signing keys are generated from quantum random number
                generators, not pseudorandom software. This eliminates seed
                prediction attacks and ensures every token is cryptographically
                unique and unguessable.
              </p>
            </div>
            <div className="flex w-full flex-col items-center text-center">
              <div className="rb-5 mb-5 md:mb-6">
                <svg className="size-12 text-black" viewBox="0 0 48 48" fill="none" xmlns="http://www.w3.org/2000/svg">
                  <path d="M24 4L8 12v12c0 10 7 18 16 20 9-2 16-10 16-20V12L24 4z" stroke="currentColor" strokeWidth="2" strokeLinejoin="round" />
                  <path d="M18 24l4 4 8-8" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              </div>
              <h3 className="mb-5 text-2xl font-bold md:mb-6 md:text-3xl md:leading-[1.3] lg:text-4xl">
                Tamper-Evident Receipts
              </h3>
              <p>
                The signed receipt bundles the content hash, an independent
                timestamp from a third-party authority, and the quantum-seeded
                JWT into a single verifiable artifact. Anyone can check it;
                nobody can forge it.
              </p>
            </div>
          </div>
          <div className="mt-10 flex items-center gap-4 md:mt-14 lg:mt-16">
            <Button variant="secondary">Generate a Receipt</Button>
            <Button iconRight={<RxChevronRight />} variant="link" size="link">
              View sample receipt
            </Button>
          </div>
        </div>
      </div>
    </section>
  );
}
