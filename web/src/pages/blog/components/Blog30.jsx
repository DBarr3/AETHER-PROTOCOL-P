"use client";

import {
  Button,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
} from "@relume_io/relume-ui";
import { AnimatePresence, motion } from "framer-motion";
import React, { useState } from "react";
import { RxChevronRight } from "react-icons/rx";

const useRelume = ({ defaultValue, selects }) => {
  const [activeSelect, setActiveSelect] = useState(defaultValue);
  const currentSelect = selects.find(function (select) {
    return select.value === activeSelect;
  });
  return { activeSelect, setActiveSelect, currentSelect };
};

export function Blog30() {
  const useActive = useRelume({
    defaultValue: "all-posts",
    selects: [
      {
        value: "all-posts",
        trigger: "All Posts",
        content: [
          {
            url: "#",
            image: {
              src: "/aethercloudagent.webp",
              alt: "Moving target defense cost analysis",
            },
            category: "Security",
            readTime: "9 min read",
            title: "What a Moving Target Actually Costs an Attacker",
            description:
              "We ran a 90-day red team exercise against our own infrastructure. Here is what we learned about the real economics of attacking a system that never sits still.",
            button: {
              title: "Read more",
              variant: "link",
              size: "link",
              iconRight: <RxChevronRight />,
            },
          },
          {
            url: "#",
            image: {
              src: "/bluecloudagent.webp",
              alt: "Quantum-tap entropy engineering",
            },
            category: "Engineering",
            readTime: "12 min read",
            title: "Quantum-Tap Entropy: Why We Built Our Own RNG",
            description:
              "Software PRNGs are predictable if you know the seed. We built a hardware quantum random number generator that feeds fresh entropy into every signing key rotation.",
            button: {
              title: "Read more",
              variant: "link",
              size: "link",
              iconRight: <RxChevronRight />,
            },
          },
          {
            url: "#",
            image: {
              src: "/diamond agent.webp",
              alt: "SOC 2 compliance with cryptographic receipts",
            },
            category: "Compliance",
            readTime: "7 min read",
            title: "SOC 2 Type II with Cryptographic Receipts",
            description:
              "How we passed our SOC 2 Type II audit using signed receipts as the primary evidence trail -- and why auditors preferred math over screenshots.",
            button: {
              title: "Read more",
              variant: "link",
              size: "link",
              iconRight: <RxChevronRight />,
            },
          },
        ],
      },
      {
        value: "security",
        trigger: "Security",
        content: [
          {
            url: "#",
            image: {
              src: "/aethercloudagent.webp",
              alt: "Moving target defense cost analysis",
            },
            category: "Security",
            readTime: "9 min read",
            title: "What a Moving Target Actually Costs an Attacker",
            description:
              "We ran a 90-day red team exercise against our own infrastructure. Here is what we learned about the real economics of attacking a system that never sits still.",
            button: {
              title: "Read more",
              variant: "link",
              size: "link",
              iconRight: <RxChevronRight />,
            },
          },
          {
            url: "#",
            image: {
              src: "/purple ghost glass.webp",
              alt: "Ghost Proxy threat model analysis",
            },
            category: "Security",
            readTime: "8 min read",
            title: "Ghost Proxy Threat Model: What We Defend Against",
            description:
              "A transparent breakdown of the threat model behind Ghost Proxy, including the attacks we prevent and the ones we explicitly scope out.",
            button: {
              title: "Read more",
              variant: "link",
              size: "link",
              iconRight: <RxChevronRight />,
            },
          },
          {
            url: "#",
            image: {
              src: "/yellow ghost.webp",
              alt: "Hardware attestation deep dive",
            },
            category: "Security",
            readTime: "6 min read",
            title: "Hardware Attestation: Trust the Silicon, Not the Software",
            description:
              "How we use TPM-based attestation to verify that signing happens in a genuine, unmodified execution environment before any key material is released.",
            button: {
              title: "Read more",
              variant: "link",
              size: "link",
              iconRight: <RxChevronRight />,
            },
          },
        ],
      },
      {
        value: "product",
        trigger: "Product",
        content: [
          {
            url: "#",
            image: {
              src: "/Gemini_Generated_Image_a8kou8a8kou8a8ko.webp",
              alt: "AetherCloud product launch",
            },
            category: "Product",
            readTime: "5 min read",
            title: "Introducing AetherCloud: Signed AI Outputs at Scale",
            description:
              "Every AI decision your organization makes now comes with a cryptographic receipt. Here is what that means for your workflow and your audit trail.",
            button: {
              title: "Read more",
              variant: "link",
              size: "link",
              iconRight: <RxChevronRight />,
            },
          },
          {
            url: "#",
            image: {
              src: "/purple ghost glass.webp",
              alt: "Ghost Proxy product announcement",
            },
            category: "Product",
            readTime: "5 min read",
            title: "Ghost Proxy: Zero-Visibility Data Transit",
            description:
              "Your AI outputs stay yours. Ghost Proxy ensures that not even AetherCloud can see the content being signed -- only you hold the keys.",
            button: {
              title: "Read more",
              variant: "link",
              size: "link",
              iconRight: <RxChevronRight />,
            },
          },
          {
            url: "#",
            image: {
              src: "/bluecloudagent.webp",
              alt: "Aetherctl CLI tool",
            },
            category: "Product",
            readTime: "4 min read",
            title: "aetherctl: Verify Receipts from Your Terminal",
            description:
              "A single CLI command to download, verify, and inspect any signed receipt. Built for developers who prefer the terminal over dashboards.",
            button: {
              title: "Read more",
              variant: "link",
              size: "link",
              iconRight: <RxChevronRight />,
            },
          },
        ],
      },
      {
        value: "engineering",
        trigger: "Engineering",
        content: [
          {
            url: "#",
            image: {
              src: "/bluecloudagent.webp",
              alt: "Quantum-tap entropy engineering",
            },
            category: "Engineering",
            readTime: "12 min read",
            title: "Quantum-Tap Entropy: Why We Built Our Own RNG",
            description:
              "Software PRNGs are predictable if you know the seed. We built a hardware quantum random number generator that feeds fresh entropy into every signing key rotation.",
            button: {
              title: "Read more",
              variant: "link",
              size: "link",
              iconRight: <RxChevronRight />,
            },
          },
          {
            url: "#",
            image: {
              src: "/aethercloudagent.webp",
              alt: "Endpoint rotation engineering",
            },
            category: "Engineering",
            readTime: "10 min read",
            title: "15-Minute Key Rotation at Scale: The Engineering Challenge",
            description:
              "Rotating signing keys every fifteen minutes across a distributed system without dropping a single request. Here is how we solved the coordination problem.",
            button: {
              title: "Read more",
              variant: "link",
              size: "link",
              iconRight: <RxChevronRight />,
            },
          },
          {
            url: "#",
            image: {
              src: "/diamond agent.webp",
              alt: "Receipt verification architecture",
            },
            category: "Engineering",
            readTime: "8 min read",
            title: "Designing a Receipt Format That Auditors Actually Trust",
            description:
              "The technical decisions behind our receipt schema -- why we chose JWS over JWE, how we handle key rollover, and what makes independent verification possible.",
            button: {
              title: "Read more",
              variant: "link",
              size: "link",
              iconRight: <RxChevronRight />,
            },
          },
        ],
      },
      {
        value: "compliance",
        trigger: "Compliance",
        content: [
          {
            url: "#",
            image: {
              src: "/diamond agent.webp",
              alt: "SOC 2 compliance with cryptographic receipts",
            },
            category: "Compliance",
            readTime: "7 min read",
            title: "SOC 2 Type II with Cryptographic Receipts",
            description:
              "How we passed our SOC 2 Type II audit using signed receipts as the primary evidence trail -- and why auditors preferred math over screenshots.",
            button: {
              title: "Read more",
              variant: "link",
              size: "link",
              iconRight: <RxChevronRight />,
            },
          },
          {
            url: "#",
            image: {
              src: "/yellow ghost.webp",
              alt: "EU AI Act compliance preparation",
            },
            category: "Compliance",
            readTime: "6 min read",
            title: "Preparing for the EU AI Act with Tamper-Evident Audit Trails",
            description:
              "The EU AI Act requires demonstrable proof of AI decision-making. Cryptographic receipts provide exactly that -- here is how to get ready before enforcement begins.",
            button: {
              title: "Read more",
              variant: "link",
              size: "link",
              iconRight: <RxChevronRight />,
            },
          },
          {
            url: "#",
            image: {
              src: "/Gemini_Generated_Image_a8kou8a8kou8a8ko.webp",
              alt: "HIPAA audit trail compliance",
            },
            category: "Compliance",
            readTime: "5 min read",
            title: "HIPAA-Grade Audit Trails Without the Paperwork",
            description:
              "Healthcare organizations using AI need provable audit trails. Signed receipts replace manual logging with cryptographic proof that regulators can verify independently.",
            button: {
              title: "Read more",
              variant: "link",
              size: "link",
              iconRight: <RxChevronRight />,
            },
          },
        ],
      },
    ],
  });
  return (
    <section id="relume" className="px-[5%] py-16 md:py-24 lg:py-28">
      <div className="container flex max-w-lg flex-col">
        <div className="mb-12 text-center md:mb-18 lg:mb-20">
          <div className="w-full max-w-lg">
            <p className="mb-3 font-semibold md:mb-4">Featured</p>
            <h1 className="mb-5 text-6xl font-bold md:mb-6 md:text-9xl lg:text-10xl">
              Latest from the Team
            </h1>
            <p className="md:text-md">
              Red team findings, engineering decisions, and compliance
              strategies -- straight from the people building Aether Security.
            </p>
          </div>
        </div>
        <div className="flex flex-col justify-start">
          <div className="md:min-w- mb-10">
            <Select
              value={useActive.activeSelect}
              onValueChange={useActive.setActiveSelect}
            >
              <SelectTrigger className="min-w-[12.5rem] px-4 py-2 md:w-auto">
                All posts
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all-posts">All Posts</SelectItem>
                <SelectItem value="security">Security</SelectItem>
                <SelectItem value="product">Product</SelectItem>
                <SelectItem value="engineering">Engineering</SelectItem>
                <SelectItem value="compliance">Compliance</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <AnimatePresence mode="wait">
            <motion.div
              key={useActive.activeSelect}
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.2, ease: "easeInOut" }}
            >
              <div className="grid grid-cols-1 gap-x-12 gap-y-12 md:gap-y-16">
                {useActive.currentSelect?.content.map((post, index) => (
                  <div key={index} className="flex flex-col border border-border-primary">
                    <a
                      href={post.url}
                      className="inline-block w-full max-w-full overflow-hidden"
                    >
                      <div className="w-full overflow-hidden">
                        <img
                          src={post.image.src}
                          alt={post.image.alt}
                          className="aspect-video size-full object-cover"
                          loading="lazy"
                        />
                      </div>
                    </a>
                    <div className="px-5 py-6 md:px-6">
                      <div className="rb-4 mb-4 flex w-full items-center justify-start">
                        <p className="mr-4 bg-background-secondary px-2 py-1 text-sm font-semibold">
                          {post.category}
                        </p>
                        <p className="inline text-sm font-semibold">{post.readTime}</p>
                      </div>
                      <a href={post.url} className="mb-2 block max-w-full">
                        <h5 className="text-2xl font-bold md:text-4xl">
                          {post.title}
                        </h5>
                      </a>
                      <p>{post.description}</p>
                      <Button
                        variant={post.button.variant}
                        size={post.button.size}
                        iconRight={post.button.iconRight}
                        className="mt-6 flex items-center justify-center gap-x-2"
                      >
                        {post.button.title}
                      </Button>
                    </div>
                  </div>
                ))}
              </div>
            </motion.div>
          </AnimatePresence>
        </div>
      </div>
    </section>
  );
}
