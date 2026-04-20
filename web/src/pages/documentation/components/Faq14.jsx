"use client";

import { Button } from "@relume_io/relume-ui";
import React from "react";

export function Faq14() {
  return (
    <section id="relume" className="px-[5%] py-16 md:py-24 lg:py-28">
      <div className="container">
        <div className="mx-auto mb-12 w-full max-w-lg text-center md:mb-18 lg:mb-20">
          <h2 className="rb-5 mb-5 text-5xl font-bold md:mb-6 md:text-7xl lg:text-8xl">
            Technical FAQ
          </h2>
          <p className="md:text-md">
            Common questions about rotation protocols, attestation, and
            deployment architecture.
          </p>
        </div>
        <div className="container grid grid-cols-1 items-start justify-center gap-y-12 md:grid-cols-3 md:gap-x-8 md:gap-y-16 lg:gap-x-12 lg:gap-y-16">
          <div className="flex w-full flex-col items-center text-center">
            <div className="rb-5 mb-5 md:mb-6">
              <img
                src="https://d22po4pjz3o32e.cloudfront.net/relume-icon.svg"
                alt="Rotation icon"
                className="size-12"
                loading="lazy"
              />
            </div>
            <h3 className="mb-3 font-bold md:mb-4 md:text-md">
              What happens to in-flight connections during a rotation?
            </h3>
            <p>
              Ghost maintains a configurable overlap window (default 2x cadence)
              where both the old and new endpoint tuples are valid. In-flight
              connections drain naturally. TLS session tickets are re-keyed to
              the new identity before the old tuple expires.
            </p>
          </div>
          <div className="flex w-full flex-col items-center text-center">
            <div className="rb-5 mb-5 md:mb-6">
              <img
                src="https://d22po4pjz3o32e.cloudfront.net/relume-icon.svg"
                alt="Latency icon"
                className="size-12"
                loading="lazy"
              />
            </div>
            <h3 className="mb-3 font-bold md:mb-4 md:text-md">
              How much latency does Scrambler add?
            </h3>
            <p>
              Median added latency is 8-15ms for 3-hop paths within a single
              region. Cross-region paths with 5+ hops typically add 25-40ms.
              Scrambler selects paths that factor in real-time latency
              measurements, so overhead stays bounded even under load.
            </p>
          </div>
          <div className="flex w-full flex-col items-center text-center">
            <div className="rb-5 mb-5 md:mb-6">
              <img
                src="https://d22po4pjz3o32e.cloudfront.net/relume-icon.svg"
                alt="Entropy icon"
                className="size-12"
                loading="lazy"
              />
            </div>
            <h3 className="mb-3 font-bold md:mb-4 md:text-md">
              What if the QRNG hardware fails?
            </h3>
            <p>
              Each coordination node maintains a 1 MiB entropy buffer. If the
              QRNG module goes offline, the node falls back to CSPRNG seeded
              from the buffer while alerting operators. Rotations continue
              uninterrupted. The node is marked degraded until QRNG is restored.
            </p>
          </div>
          <div className="flex w-full flex-col items-center text-center">
            <div className="rb-5 mb-5 md:mb-6">
              <img
                src="https://d22po4pjz3o32e.cloudfront.net/relume-icon.svg"
                alt="Compliance icon"
                className="size-12"
                loading="lazy"
              />
            </div>
            <h3 className="mb-3 font-bold md:mb-4 md:text-md">
              Which compliance frameworks are supported?
            </h3>
            <p>
              The commitment ledger maps rotation events to NIST 800-53, ISO
              27001, SOC 2 Type II, and PCI DSS v4.0 controls automatically.
              Auditors can independently verify Merkle proofs and timestamp
              authority responses without Aether infrastructure access.
            </p>
          </div>
          <div className="flex w-full flex-col items-center text-center">
            <div className="rb-5 mb-5 md:mb-6">
              <img
                src="https://d22po4pjz3o32e.cloudfront.net/relume-icon.svg"
                alt="Kubernetes icon"
                className="size-12"
                loading="lazy"
              />
            </div>
            <h3 className="mb-3 font-bold md:mb-4 md:text-md">
              Can I run Aether in an air-gapped environment?
            </h3>
            <p>
              Yes. The aether-operator supports air-gapped deployments with
              local coordination nodes. QRNG entropy is provided by on-premise
              hardware modules. The commitment ledger anchors to an internal
              timestamping authority instead of public services.
            </p>
          </div>
          <div className="flex w-full flex-col items-center text-center">
            <div className="rb-5 mb-5 md:mb-6">
              <img
                src="https://d22po4pjz3o32e.cloudfront.net/relume-icon.svg"
                alt="Predator icon"
                className="size-12"
                loading="lazy"
              />
            </div>
            <h3 className="mb-3 font-bold md:mb-4 md:text-md">
              Does Predator trace-back actively probe external systems?
            </h3>
            <p>
              No. Trace-back is entirely passive. It correlates timing metadata
              and connection patterns across mesh relay nodes to identify
              adversary origin points. No packets are sent to external systems.
              All trace-back operations are logged and attested in the ledger.
            </p>
          </div>
        </div>
        <div className="mt-12 text-center md:mt-18 lg:mt-20">
          <h4 className="mb-3 text-2xl font-bold md:mb-4 md:text-3xl md:leading-[1.3] lg:text-4xl">
            Need deeper technical guidance?
          </h4>
          <p className="md:text-md">
            Reach out to our solutions engineering team or join the community
            Discord.
          </p>
          <div className="mt-6 md:mt-8">
            <Button title="Contact Engineering" variant="secondary">
              Contact Engineering
            </Button>
          </div>
        </div>
      </div>
    </section>
  );
}
