// Shared helpers used by both stripe-webhook and free-signup functions.
// DO NOT deploy as a function — the leading underscore on the directory
// tells Supabase to skip it.

export function generateLicenseKey(): string {
  const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789";
  const bytes = new Uint8Array(12);
  crypto.getRandomValues(bytes);
  const chars = Array.from(bytes, (b) => alphabet[b % alphabet.length]);
  const g1 = chars.slice(0, 4).join("");
  const g2 = chars.slice(4, 8).join("");
  const g3 = chars.slice(8, 12).join("");
  return `AETH-CLD-${g1}-${g2}-${g3}`;
}

export interface SendEmailOpts {
  fromEmail: string;
  resendKey: string;
  appUrl: string;
}

export async function sendWelcomeEmail(
  to: string,
  licenseKey: string,
  tier: string,
  opts: SendEmailOpts,
): Promise<void> {
  if (!opts.resendKey) {
    console.warn("RESEND_API_KEY not set, skipping email");
    return;
  }
  const res = await fetch("https://api.resend.com/emails", {
    method: "POST",
    headers: {
      "Authorization": `Bearer ${opts.resendKey}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      from: opts.fromEmail,
      to,
      subject: "Welcome to AetherCloud — your license key",
      html: `
        <p>Thanks for subscribing to AetherCloud (<strong>${tier}</strong> tier).</p>
        <p>Your license key:</p>
        <p style="font-family:monospace;font-size:16px;padding:12px;background:#f4f4f4;border-radius:4px">${licenseKey}</p>
        <p>Paste this into the AetherCloud desktop app to activate, or visit <a href="${opts.appUrl}">${opts.appUrl}</a>.</p>
        <p>— Aether Systems</p>
      `,
    }),
  });
  if (!res.ok) {
    console.error("Resend failed:", res.status, await res.text());
  }
}

export interface CaptureEventOpts {
  posthogKey: string;
  posthogHost: string;
  distinctId: string;
  event: string;
  properties?: Record<string, unknown>;
}

// Fires a server-side PostHog event via fetch.
// Works in Deno runtime where posthog-node does not.
// Never throws — analytics must not break webhooks.
export async function captureServerEvent(opts: CaptureEventOpts): Promise<void> {
  if (!opts.posthogKey) {
    console.warn("POSTHOG_KEY not set, skipping server event");
    return;
  }
  try {
    const url = `${opts.posthogHost.replace(/\/$/, "")}/capture/`;
    const res = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        api_key: opts.posthogKey,
        event: opts.event,
        distinct_id: opts.distinctId,
        properties: opts.properties ?? {},
        timestamp: new Date().toISOString(),
      }),
    });
    if (!res.ok) {
      console.error("PostHog capture failed:", res.status, await res.text());
    }
  } catch (err) {
    console.error("PostHog capture threw:", err);
  }
}

// Commonly abused throwaway email domains. Hardcoded for speed.
// proton.me and duck.com are deliberately NOT blocked — paying customers use them.
export const DISPOSABLE_EMAIL_DOMAINS = new Set<string>([
  "mailinator.com", "guerrillamail.com", "guerrillamail.info", "guerrillamail.net",
  "guerrillamail.org", "10minutemail.com", "10minutemail.net", "tempmail.org",
  "tempmail.com", "temp-mail.org", "trashmail.com", "trashmail.net",
  "yopmail.com", "yopmail.net", "yopmail.fr", "throwawaymail.com",
  "throwaway.email", "sharklasers.com", "maildrop.cc", "mintemail.com",
  "fakeinbox.com", "getnada.com", "nada.email", "mohmal.com",
  "tempail.com", "dispostable.com", "emailondeck.com", "mytemp.email",
  "inboxbear.com", "incognitomail.org", "mailnesia.com", "mytrashmail.com",
  "spamgourmet.com", "spamex.com", "spambox.us", "spambog.com",
  "tempmailo.com", "tempinbox.com", "tempmail.ninja", "throwawaymailbox.com",
  "mailcatch.com", "burnermail.io", "mailtemp.info", "email-temp.com",
  "anonaddy.me",
  "mailnull.com", "emailsensei.com", "tempr.email", "tmail.ws",
  "getairmail.com", "mail-temp.com", "discard.email", "mailforspam.com",
  "mvrht.net", "cool.fr.nf", "jetable.fr.nf", "nospam.ze.tc",
  "spam.la", "speed.1s.fr", "oosi.ru",
]);

export function isDisposableEmail(email: string): boolean {
  const at = email.lastIndexOf("@");
  if (at < 0) return false;
  const domain = email.slice(at + 1).toLowerCase().trim();
  return DISPOSABLE_EMAIL_DOMAINS.has(domain);
}

export function isValidEmail(email: string): boolean {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email);
}
