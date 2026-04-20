import React from "react";
import { Link, useSearchParams } from "react-router-dom";
import { DOWNLOAD_URL } from "../../lib/config.js";

/**
 * Post-Stripe-checkout landing page.
 *
 * URL: /welcome?session=cs_test_... (matches `create-checkout-session`
 * edge function's DEFAULT_SUCCESS_URL template).
 *
 * Behavior:
 *  - Shows the AetherCloud-Setup.exe download button
 *  - Tells the user a license key is en route (stripe-webhook edge
 *    function generates + emails it via Resend on
 *    `checkout.session.completed`)
 *  - Intentionally does NOT fetch the session server-side to render
 *    tier info. The welcome email is the authoritative delivery
 *    channel; this page is a fast "you're in, download now" state.
 *
 * If the user arrived here without a session (manual URL visit), the
 * page still renders usefully — the download button is the primary
 * action and doesn't require a session.
 */
export default function Welcome() {
  const [params] = useSearchParams();
  // Both ?session= (from create-checkout-session template) and ?session_id=
  // (Stripe convention) are accepted. We just use it to show a subtle
  // confirmation that the link came from a real checkout.
  const hasSession = Boolean(params.get("session") || params.get("session_id"));

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
          {hasSession ? "CHECKOUT // COMPLETE" : "AETHERCLOUD // READY"}
        </p>

        <h1 style={{
          fontSize: "2.5rem",
          fontWeight: 700,
          margin: "0 0 1rem",
          textAlign: "center",
          lineHeight: 1.1,
        }}>
          Welcome to <span style={{ color: "#00d4ff" }}>AetherCloud</span>.
        </h1>

        <p style={{
          color: "#95a2c8",
          textAlign: "center",
          lineHeight: 1.6,
          marginBottom: "2.5rem",
        }}>
          Your subscription is active. Download the AetherCloud installer below,
          run it, and sign in with the license key we&rsquo;re emailing to you.
        </p>

        <div style={{
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          gap: "1rem",
          marginBottom: "2rem",
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
            Download AetherCloud Installer
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
          marginBottom: "1.5rem",
        }}>
          <p style={{
            fontSize: 10,
            letterSpacing: "0.12em",
            textTransform: "uppercase",
            color: "#d4a017",
            margin: "0 0 0.6rem",
          }}>
            NEXT &mdash; YOUR LICENSE KEY
          </p>
          <p style={{ fontSize: 13, color: "#95a2c8", margin: 0, lineHeight: 1.6 }}>
            Check your email from{" "}
            <strong style={{ color: "#e8e6e0" }}>no-reply@aethersystems.net</strong>.
            The email contains your license key (format <code style={{ color: "#00d4ff" }}>AETH-CLD-XXXX-XXXX-XXXX</code>).
            Paste it into the AetherCloud desktop app to activate. Didn&rsquo;t
            get it within 2 minutes?{" "}
            <a href="mailto:support@aethersystems.net" style={{ color: "#00d4ff" }}>
              email support
            </a>.
          </p>
        </div>

        <p style={{ textAlign: "center", marginTop: "2rem" }}>
          <Link to="/" style={{ fontSize: 12, color: "#6b7280", textDecoration: "underline" }}>
            ← back to aethersystems.net
          </Link>
        </p>
      </div>
    </main>
  );
}
