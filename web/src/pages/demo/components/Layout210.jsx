"use client";

import { Button } from "@relume_io/relume-ui";
import React from "react";
import { RxChevronRight } from "react-icons/rx";

export function Layout210() {
  return (
    <section id="relume" className="px-[5%] py-16 md:py-24 lg:py-28">
      <div className="container">
        <div className="grid grid-cols-1 items-center gap-12 md:grid-cols-2 lg:gap-x-20">
          <div className="order-2 md:order-1">
            <div className="rounded-lg border border-border-primary bg-neutral-900 p-6 font-mono text-sm text-green-400">
              <p className="mb-2 text-neutral-500"># Step 1: Download the receipt</p>
              <p className="mb-4">$ aetherctl receipt download --id rec_7x9kLm</p>
              <p className="mb-2 text-neutral-500"># Step 2: Verify the SHA-256 hash</p>
              <p className="mb-4">$ aetherctl verify hash receipt.json</p>
              <p className="mb-1 text-green-300">  Content hash: a7f3c...d9e1b</p>
              <p className="mb-4 text-green-300">  Status: MATCH</p>
              <p className="mb-2 text-neutral-500"># Step 3: Confirm timestamp authority</p>
              <p className="mb-4">$ aetherctl verify timestamp receipt.json</p>
              <p className="mb-1 text-green-300">  Authority: DigiCert TSA</p>
              <p className="mb-4 text-green-300">  Signed at: 2026-04-15T09:41:22Z</p>
              <p className="mb-2 text-neutral-500"># Step 4: Validate JWT signature</p>
              <p className="mb-2">$ aetherctl verify jwt receipt.json</p>
              <p className="mb-1 text-green-300">  Algorithm: ES256</p>
              <p className="text-green-300">  Signature: VALID</p>
            </div>
          </div>
          <div className="order-1 md:order-2">
            <p className="mb-3 font-semibold md:mb-4">Verification Flow</p>
            <h2 className="mb-5 text-5xl font-bold md:mb-6 md:text-7xl lg:text-8xl">
              Verify any receipt with aetherctl
            </h2>
            <p className="mb-5 md:mb-6 md:text-md">
              Auditors do not need to trust AetherCloud. They download the
              receipt, verify the hash matches the content, confirm the timestamp
              against the independent authority, and validate the JWT signature.
              Three commands, zero trust required.
            </p>
            <ul className="my-4 list-none pl-0 space-y-3">
              <li className="flex items-start gap-3">
                <span className="flex size-6 shrink-0 items-center justify-center rounded-full bg-black text-xs font-bold text-white">1</span>
                <p><strong>Verify the SHA-256 hash</strong> -- confirms content has not been modified since signing</p>
              </li>
              <li className="flex items-start gap-3">
                <span className="flex size-6 shrink-0 items-center justify-center rounded-full bg-black text-xs font-bold text-white">2</span>
                <p><strong>Confirm timestamp authority</strong> -- proves when the receipt was created via third-party TSA</p>
              </li>
              <li className="flex items-start gap-3">
                <span className="flex size-6 shrink-0 items-center justify-center rounded-full bg-black text-xs font-bold text-white">3</span>
                <p><strong>Validate the JWT signature</strong> -- ensures the receipt was issued by a legitimate AetherCloud key</p>
              </li>
            </ul>
            <div className="mt-6 flex flex-wrap gap-4 md:mt-8">
              <Button title="Install aetherctl" variant="secondary">
                Install aetherctl
              </Button>
              <Button
                title="Verification guide"
                variant="link"
                size="link"
                iconRight={<RxChevronRight />}
              >
                Verification guide
              </Button>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
