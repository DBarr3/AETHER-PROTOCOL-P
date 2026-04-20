"use client";

import { Button, Input } from "@relume_io/relume-ui";
import React, { useState } from "react";
import { Link } from "react-router-dom";
import { contactLink } from "../../../lib/contactLink.js";
import {
  BiLogoFacebookCircle,
  BiLogoInstagram,
  BiLogoLinkedinSquare,
  BiLogoYoutube,
} from "react-icons/bi";
import { FaXTwitter } from "react-icons/fa6";

const useForm = () => {
  const [email, setEmail] = useState("");
  const handleSetEmail = (event) => {
    setEmail(event.target.value);
  };
  const handleSubmit = (event) => {
    event.preventDefault();
  };
  return {
    email,
    handleSetEmail,
    handleSubmit,
  };
};

export function Footer5() {
  const formState = useForm();
  return (
    <footer id="relume" className="px-[5%] py-12 md:py-18 lg:py-20">
      <div className="container">
        <div className="rb-12 mb-12 block items-start justify-between md:mb-18 lg:mb-20 lg:flex">
          <div className="rb-6 mb-6 lg:mb-0">
            <h1 className="font-semibold md:text-md">Stay in the loop</h1>
            <p>Get updates on signed receipts and security</p>
          </div>
          <div className="max-w-md lg:min-w-[25rem]">
            <form
              className="mb-3 grid grid-cols-1 gap-x-4 gap-y-3 sm:grid-cols-[1fr_max-content] sm:gap-y-4 md:gap-4"
              onSubmit={formState.handleSubmit}
            >
              <Input
                id="email"
                type="email"
                placeholder="Your email"
                value={formState.email}
                onChange={formState.handleSetEmail}
              />
              <Button title="Subscribe" variant="secondary" size="sm">
                Subscribe
              </Button>
            </form>
            <p className="text-xs">
              We respect your inbox. Unsubscribe anytime.
            </p>
          </div>
        </div>
        <div className="rb-12 mb-12 grid grid-cols-1 items-start gap-x-8 gap-y-10 sm:grid-cols-4 md:mb-18 md:gap-y-12 lg:mb-20">
          <a href="/" className="sm:col-start-1 sm:row-start-1">
            <span className="text-lg font-bold tracking-tight">
              Aether Security
            </span>
          </a>
          <div className="flex flex-col items-start justify-start">
            <h2 className="mb-3 font-semibold md:mb-4">Products</h2>
            <ul>
              <li className="py-2 text-sm">
                <Link to="/aether-cloud" className="flex items-center gap-3">AetherCloud</Link>
              </li>
              <li className="py-2 text-sm">
                <Link to="/protocol-family" className="flex items-center gap-3">Protocol Family</Link>
              </li>
              <li className="py-2 text-sm">
                <Link to="/pricing" className="flex items-center gap-3">Pricing</Link>
              </li>
              <li className="py-2 text-sm">
                <Link to="/demo" className="flex items-center gap-3">Demo</Link>
              </li>
            </ul>
          </div>
          <div className="flex flex-col items-start justify-start">
            <h2 className="mb-3 font-semibold md:mb-4">Resources</h2>
            <ul>
              <li className="py-2 text-sm">
                <Link to="/documentation" className="flex items-center gap-3">Documentation</Link>
              </li>
              <li className="py-2 text-sm">
                <Link to="/blog" className="flex items-center gap-3">Blog</Link>
              </li>
              <li className="py-2 text-sm">
                <Link to="/protocol-family" className="flex items-center gap-3">Protocol Specs</Link>
              </li>
            </ul>
          </div>
          <div className="flex flex-col items-start justify-start">
            <h2 className="mb-3 font-semibold md:mb-4">Company</h2>
            <ul>
              <li className="py-2 text-sm">
                <Link to={contactLink({ intent: 'general', product: 'site_wide', cta: 'footer_contact' })} className="flex items-center gap-3">Contact</Link>
              </li>
              <li className="py-2 text-sm">
                <Link to={contactLink({ intent: 'support', product: 'site_wide', cta: 'footer_support' })} className="flex items-center gap-3">Support</Link>
              </li>
            </ul>
          </div>
        </div>
        <div className="h-px w-full bg-black" />
        <div className="flex flex-col-reverse items-start pb-4 pt-6 text-sm md:justify-start md:pb-0 md:pt-8 lg:flex-row lg:items-center lg:justify-between">
          <div className="flex flex-col-reverse items-start md:flex-row md:gap-6 lg:items-center">
            <div className="grid grid-flow-row grid-cols-[max-content] justify-center gap-y-4 md:grid-flow-col md:justify-center md:gap-x-6 md:gap-y-0 lg:text-left">
              <p className="mt-8 md:mt-0">
                © 2026 Aether Security. All rights reserved.
              </p>
            </div>
          </div>
          <div className="mb-8 flex items-center justify-center gap-3 lg:mb-0">
            <a href="#" aria-label="Facebook">
              <BiLogoFacebookCircle className="size-6" />
            </a>
            <a href="#" aria-label="Instagram">
              <BiLogoInstagram className="size-6" />
            </a>
            <a href="#" aria-label="Twitter">
              <FaXTwitter className="size-6 p-0.5" />
            </a>
            <a href="#" aria-label="LinkedIn">
              <BiLogoLinkedinSquare className="size-6" />
            </a>
            <a href="#" aria-label="YouTube">
              <BiLogoYoutube className="size-6" />
            </a>
          </div>
        </div>
      </div>
    </footer>
  );
}
