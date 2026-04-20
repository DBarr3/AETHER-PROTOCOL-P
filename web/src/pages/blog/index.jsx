import React from "react";
import AetherHero from "../../components/AetherHero.jsx";
import { contactLink } from "../../lib/contactLink.js";
import { Blog30 } from "./components/Blog30";
import { Cta52 } from "./components/Cta52";

export default function Page() {
  return (
    <div>
      <AetherHero
        eyebrow="AETHER // FIELD NOTES"
        heading={
          <>
            Dispatches from the
            <br />
            <span className="text-aether-cyan">moving target.</span>
          </>
        }
        sub="Red team tear-downs, protocol changelogs, post-incident write-ups, and the occasional unvarnished opinion. Written by the operators who run the rotation."
        primary={{ label: "Latest post", to: "/blog-post" }}
        secondary={{ label: "Subscribe", to: contactLink({ intent: 'general', product: 'site_wide', cta: 'blog_subscribe' }) }}
      />
      <Blog30 />
      <Cta52 />
    </div>
  );
}
