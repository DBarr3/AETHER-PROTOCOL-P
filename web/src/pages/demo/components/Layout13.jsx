"use client";

import { Button } from "@relume_io/relume-ui";
import React, { useState } from "react";
import { RxChevronRight } from "react-icons/rx";

export function Layout13() {
  const [inputText, setInputText] = useState("");
  const [receipt, setReceipt] = useState(null);

  const handleSign = (e) => {
    e.preventDefault();
    if (!inputText.trim()) return;
    // Simulated receipt generation
    const hash = "a7f3c" + Math.random().toString(36).slice(2, 10) + "d9e1b";
    setReceipt({
      hash: `sha256:${hash}...`,
      timestamp: new Date().toISOString(),
      jwt: `eyJhbGciOiJFUzI1NiIsInR5cCI6IkpXVCJ9.${btoa(inputText.slice(0, 20)).replace(/=/g, "")}...`,
    });
  };

  return (
    <section id="relume" className="px-[5%] py-16 md:py-24 lg:py-28">
      <div className="container">
        <div className="grid grid-cols-1 gap-y-12 md:grid-flow-row md:grid-cols-2 md:items-center md:gap-x-12 lg:gap-x-20">
          <div>
            <p className="mb-3 font-semibold md:mb-4">Live Signing</p>
            <h2 className="rb-5 mb-5 text-5xl font-bold md:mb-6 md:text-7xl lg:text-8xl">
              Paste any AI output and sign it now
            </h2>
            <p className="mb-5 md:mb-6 md:text-md">
              No account needed. Paste any text into the signing field, click
              Sign, and get back a tamper-evident receipt with a SHA-256 hash,
              independent timestamp, and quantum-seeded JWT -- all verifiable
              with a single command.
            </p>
            <div className="flex flex-wrap items-center gap-x-6 gap-y-4 py-2">
              <div className="flex items-center gap-2">
                <svg className="size-5" viewBox="0 0 20 20" fill="none"><path d="M10 2L3 6v4c0 5 3 9 7 10 4-1 7-5 7-10V6l-7-4z" stroke="currentColor" strokeWidth="1.5"/><path d="M7 10l2 2 4-4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/></svg>
                <span className="text-sm font-medium">SHA-256 Hashed</span>
              </div>
              <div className="flex items-center gap-2">
                <svg className="size-5" viewBox="0 0 20 20" fill="none"><circle cx="10" cy="10" r="7" stroke="currentColor" strokeWidth="1.5"/><path d="M10 6v4l3 2" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/></svg>
                <span className="text-sm font-medium">Timestamped</span>
              </div>
              <div className="flex items-center gap-2">
                <svg className="size-5" viewBox="0 0 20 20" fill="none"><rect x="3" y="8" width="14" height="9" rx="2" stroke="currentColor" strokeWidth="1.5"/><path d="M6 8V5a4 4 0 018 0v3" stroke="currentColor" strokeWidth="1.5"/></svg>
                <span className="text-sm font-medium">JWT Sealed</span>
              </div>
            </div>
            <div className="mt-6 flex flex-wrap items-center gap-4 md:mt-8">
              <Button title="Open Signing Tool" variant="secondary">
                Open Signing Tool
              </Button>
              <Button
                title="How it works"
                variant="link"
                size="link"
                iconRight={<RxChevronRight />}
              >
                How it works
              </Button>
            </div>
          </div>
          <div>
            <div className="rounded-lg border border-border-primary bg-neutral-50 p-6">
              <form onSubmit={handleSign}>
                <label className="mb-2 block text-sm font-semibold">Paste AI output</label>
                <textarea
                  className="mb-4 w-full rounded border border-neutral-300 bg-white p-3 font-mono text-sm focus:border-black focus:outline-none"
                  rows={5}
                  placeholder="Paste any AI-generated text here..."
                  value={inputText}
                  onChange={(e) => setInputText(e.target.value)}
                />
                <Button title="Sign" type="submit" className="w-full">
                  Sign This Output
                </Button>
              </form>
              {receipt && (
                <div className="mt-4 rounded border border-green-200 bg-green-50 p-4">
                  <p className="mb-1 text-xs font-semibold text-green-800">Receipt Generated</p>
                  <p className="font-mono text-xs text-green-700 break-all">
                    Hash: {receipt.hash}
                  </p>
                  <p className="font-mono text-xs text-green-700 break-all">
                    Time: {receipt.timestamp}
                  </p>
                  <p className="font-mono text-xs text-green-700 break-all">
                    JWT: {receipt.jwt}
                  </p>
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
