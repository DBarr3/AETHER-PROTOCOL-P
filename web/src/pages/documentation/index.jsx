import React from "react";
import AetherHero from "../../components/AetherHero.jsx";
import { contactLink } from "../../lib/contactLink.js";
import { Content27 } from "./components/Content27";
import { Faq14 } from "./components/Faq14";
import { Cta53 } from "./components/Cta53";
import { Cta52 } from "./components/Cta52";

export default function Page() {
  return (
    <div>
      <AetherHero
        eyebrow="AETHER // DOCUMENTATION"
        heading={
          <>
            The protocol,
            <br />
            <span className="text-aether-cyan">written down.</span>
          </>
        }
        sub="Architecture, rotation semantics, attestation flow, and integration guides. Written by the people who built it. Everything from the quantum-tap hardware spec to the commitment ledger format, with copy-pasteable CLI examples."
        primary={{ label: "Quickstart", to: "#quickstart" }}
        secondary={{ label: "Download whitepaper", to: contactLink({ intent: 'general', product: 'site_wide', cta: 'docs_whitepaper' }) }}
      />
      <Content27 />
      <Faq14 />
      <Cta53 />
      <Cta52 />
    </div>
  );
}
