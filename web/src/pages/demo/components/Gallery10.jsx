"use client";

import React from "react";

export function Gallery10() {
  return (
    <section id="relume" className="px-[5%] py-16 md:py-24 lg:py-28">
      <div className="container">
        <div className="mb-12 text-center md:mb-18 lg:mb-20">
          <h2 className="mb-5 text-5xl font-bold md:mb-6 md:text-7xl lg:text-8xl">
            Inside the Rotation Process
          </h2>
          <p className="md:text-md">
            A visual walkthrough of how AetherCloud rotates endpoints, signs
            outputs, and delivers tamper-evident proof at every step.
          </p>
        </div>
        <div className="gap-8 space-y-8 md:columns-3">
          <div className="block w-full">
            <img
              src="/aethercloudagent.webp"
              alt="AetherCloud agent initiating a signing sequence"
              className="size-full object-cover rounded-lg"
              loading="lazy"
            />
            <p className="mt-2 text-center text-sm text-neutral-600">
              The AetherCloud agent initiates the signing sequence
            </p>
          </div>
          <div className="block w-full">
            <img
              src="/bluecloudagent.webp"
              alt="Endpoint rotation powered by quantum-seeded entropy"
              className="size-full object-cover rounded-lg"
              loading="lazy"
            />
            <p className="mt-2 text-center text-sm text-neutral-600">
              Quantum-seeded entropy drives endpoint rotation
            </p>
          </div>
          <div className="block w-full">
            <img
              src="/diamond agent.webp"
              alt="Hardware attestation validates the signing environment"
              className="size-full object-cover rounded-lg"
              loading="lazy"
            />
            <p className="mt-2 text-center text-sm text-neutral-600">
              Hardware attestation validates the signing environment
            </p>
          </div>
          <div className="block w-full">
            <img
              src="/purple ghost glass.webp"
              alt="Ghost Proxy ensures zero-visibility data transit"
              className="size-full object-cover rounded-lg"
              loading="lazy"
            />
            <p className="mt-2 text-center text-sm text-neutral-600">
              Ghost Proxy ensures zero-visibility data transit
            </p>
          </div>
          <div className="block w-full">
            <img
              src="/yellow ghost.webp"
              alt="Cryptographic receipt is sealed and delivered"
              className="size-full object-cover rounded-lg"
              loading="lazy"
            />
            <p className="mt-2 text-center text-sm text-neutral-600">
              The cryptographic receipt is sealed and delivered
            </p>
          </div>
          <div className="block w-full">
            <img
              src="/Gemini_Generated_Image_a8kou8a8kou8a8ko.webp"
              alt="Tamper-evident verification completes the chain of trust"
              className="size-full object-cover rounded-lg"
              loading="lazy"
            />
            <p className="mt-2 text-center text-sm text-neutral-600">
              Verification completes the chain of trust
            </p>
          </div>
        </div>
      </div>
    </section>
  );
}
