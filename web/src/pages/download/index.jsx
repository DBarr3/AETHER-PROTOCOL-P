import React from "react";
import { Link } from "react-router-dom";
import { DOWNLOAD_URL, CHECKOUT_URL, TIER_CHECKOUT_LINKS } from "../../lib/config.js";

/**
 * Direct-download landing page (free tier).
 *
 * URL: /download
 *
 * Intent: the aether-cloud page's Free tier links here; this is a low-friction
 * "click to download" with install guidance. No email capture (Free tier can
 * sign up from inside the installed app; today the download itself is open so
 * evaluators can try the product before touching a form).
 *
 * Paid tiers never hit this page — they go through /success with a session_id.
 */
export default function Download() {
  return (
    <main style={{
      minHeight: "100vh",
      background: "#0a0a0f",
      color: "#e8e6e0",
      fontFamily: "'IBM Plex Mono', monospace",
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
      padding: "2rem",
    }}>
      <div style={{ maxWidth: 640, width: "100%" }}>
        <p style={{
          fontSize: 11,
          letterSpacing: "0.14em",
          textTransform: "uppercase",
          color: "#00d4ff",
          marginBottom: "1.5rem",
          textAlign: "center",
        }}>
          FREE DOWNLOAD // NO CARD
        </p>

        <h1 style={{
          fontSize: "2.5rem",
          fontWeight: 700,
          margin: "0 0 1rem",
          textAlign: "center",
          lineHeight: 1.1,
        }}>
          Download <span style={{ color: "#00d4ff" }}>AetherCloud</span>.
        </h1>

        <p style={{
          color: "#95a2c8",
          textAlign: "center",
          lineHeight: 1.6,
          marginBottom: "2.5rem",
        }}>
          Click the button below to download the installer. Run it, accept the
          consent checkbox, and the app installs in ~60 seconds.
        </p>

        <div style={{
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          gap: "0.75rem",
          marginBottom: "2.5rem",
        }}>
          <a
            href={DOWNLOAD_URL}
            style={{
              display: "inline-block",
              padding: "1rem 2.5rem",
              background: "#00d4ff",
              color: "#0a0a0f",
              fontWeight: 700,
              fontSize: "0.9rem",
              textDecoration: "none",
              borderRadius: 4,
              letterSpacing: "0.05em",
              textTransform: "uppercase",
            }}
          >
            Download for Windows
          </a>
          <p style={{ fontSize: 12, color: "#6b7280", margin: 0 }}>
            ~13 MB&nbsp;&middot;&nbsp;Windows 10 or later
          </p>
        </div>

        <div style={{
          border: "1px solid #1a1f2e",
          borderRadius: 8,
          background: "rgba(10, 12, 16, 0.6)",
          padding: "1.25rem",
          marginBottom: "1rem",
        }}>
          <p style={{
            fontSize: 10,
            letterSpacing: "0.12em",
            textTransform: "uppercase",
            color: "#d4a017",
            margin: "0 0 0.6rem",
          }}>
            HEADS UP
          </p>
          <p style={{ fontSize: 13, color: "#95a2c8", margin: 0, lineHeight: 1.6 }}>
            Windows may show a &ldquo;protected your PC&rdquo; warning on first
            install while our code-signing certificate is being issued. Click{" "}
            <strong style={{ color: "#e8e6e0" }}>More info &rarr; Run anyway</strong>.
            The binary is downloaded over HTTPS and the wizard verifies the
            payload SHA-256 before anything is written to disk.
          </p>
        </div>

        <div style={{
          border: "1px solid #1a1f2e",
          borderRadius: 8,
          background: "rgba(10, 12, 16, 0.6)",
          padding: "1.25rem",
          marginBottom: "2rem",
        }}>
          <p style={{
            fontSize: 10,
            letterSpacing: "0.12em",
            textTransform: "uppercase",
            color: "#00d4ff",
            margin: "0 0 0.6rem",
          }}>
            NEED MORE TOKENS?
          </p>
          <p style={{ fontSize: 13, color: "#95a2c8", margin: 0, lineHeight: 1.6 }}>
            Free tier is capped at 15,000 tokens/month. Upgrade paths:
          </p>
          <div style={{ display: "flex", flexWrap: "wrap", gap: "0.5rem", marginTop: "0.75rem" }}>
            <a
              href={TIER_CHECKOUT_LINKS.Solo}
              style={{
                display: "inline-block",
                padding: "0.55rem 1rem",
                background: "#00d4ff",
                color: "#0a0a0f",
                fontWeight: 700,
                fontSize: 12,
                textDecoration: "none",
                borderRadius: 4,
                letterSpacing: "0.04em",
                textTransform: "uppercase",
              }}
            >
              Solo $19.99/mo
            </a>
            <a
              href={TIER_CHECKOUT_LINKS.Professional}
              style={{
                display: "inline-block",
                padding: "0.55rem 1rem",
                background: "transparent",
                color: "#e8e6e0",
                fontWeight: 600,
                fontSize: 12,
                textDecoration: "none",
                borderRadius: 4,
                border: "1px solid #2a3350",
                letterSpacing: "0.04em",
                textTransform: "uppercase",
              }}
            >
              Pro $49/mo
            </a>
            <a
              href={TIER_CHECKOUT_LINKS.Team}
              style={{
                display: "inline-block",
                padding: "0.55rem 1rem",
                background: "transparent",
                color: "#e8e6e0",
                fontWeight: 600,
                fontSize: 12,
                textDecoration: "none",
                borderRadius: 4,
                border: "1px solid #2a3350",
                letterSpacing: "0.04em",
                textTransform: "uppercase",
              }}
            >
              Team $89/mo
            </a>
          </div>
          <p style={{ fontSize: 11, color: "#6b7280", margin: "0.6rem 0 0", lineHeight: 1.5 }}>
            Opens {new URL(CHECKOUT_URL).host} &mdash; Stripe-hosted checkout.
          </p>
        </div>

        <p style={{ textAlign: "center" }}>
          <Link to="/" style={{ fontSize: 12, color: "#6b7280", textDecoration: "underline" }}>
            ← back to aethersystems.net
          </Link>
        </p>
      </div>
    </main>
  );
}
