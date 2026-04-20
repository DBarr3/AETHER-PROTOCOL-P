"use client";

import { Button } from "@relume_io/relume-ui";
import React from "react";

export function Cta53() {
  return (
    <section id="relume" className="px-[5%] py-16 md:py-24 lg:py-28">
      <div className="container relative">
        <div className="relative z-10 flex flex-col items-center p-8 md:p-12 lg:p-16">
          <div className="max-w-lg text-center">
            <h2 className="rb-5 mb-5 text-5xl font-bold text-text-alternative md:mb-6 md:text-7xl lg:text-8xl">
              Ready to prove every decision?
            </h2>
            <p className="text-text-alternative md:text-md">
              Start generating tamper-evident receipts for your AI outputs
              today. Starter plan includes 1,000 signed receipts per month.
            </p>
          </div>
          <div className="mt-6 flex flex-wrap items-center justify-center gap-4 md:mt-8">
            <Button title="Get Started Free">Get Started Free</Button>
            <Button title="Talk to Sales" variant="secondary-alt">
              Talk to Sales
            </Button>
          </div>
        </div>
        <div className="absolute inset-0 z-0">
          <img
            src="/aethercloudagent.webp"
            className="size-full object-cover"
            alt="AetherCloud signing infrastructure"
            loading="lazy"
          />
          <div className="absolute inset-0 bg-black/70" />
        </div>
      </div>
    </section>
  );
}
