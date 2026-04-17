// License-key generation + hashing for AetherCloud.
// Format: ACLD-XXXX-XXXX-XXXX-XXXX (25 chars incl. dashes, base32 alphabet without
// ambiguous chars). Hash is SHA-256 hex — only the hash is used for lookups
// in server paths that need to verify keys without leaking them in logs.

const ALPHABET = "ABCDEFGHJKMNPQRSTVWXYZ23456789"; // 30 chars, excludes 0/O, 1/I/L, U/V ambiguity

function randomChar(): string {
  const buf = new Uint8Array(1);
  crypto.getRandomValues(buf);
  return ALPHABET[buf[0] % ALPHABET.length];
}

function randomBlock(n: number): string {
  return Array.from({ length: n }, randomChar).join("");
}

export function generateLicenseKey(
  prefix: "ACLD" | "ASEC" | "APRT" = "ACLD",
): string {
  return `${prefix}-${randomBlock(4)}-${randomBlock(4)}-${randomBlock(4)}-${randomBlock(4)}`;
}

export async function hashLicenseKey(key: string): Promise<string> {
  const data = new TextEncoder().encode(key);
  const digest = await crypto.subtle.digest("SHA-256", data);
  return Array.from(new Uint8Array(digest))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

export function prefixFor(
  product: "aether_cloud" | "aether_security" | "aether_protocol",
): "ACLD" | "ASEC" | "APRT" {
  if (product === "aether_cloud") return "ACLD";
  if (product === "aether_security") return "ASEC";
  return "APRT";
}
