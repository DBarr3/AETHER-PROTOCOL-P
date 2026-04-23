// Installer telemetry ingestion endpoint.
//
// POST https://cjjcdwrnpzwlvradbros.supabase.co/functions/v1/ingest-install-event
//
// Public endpoint (no JWT) — the Electron installer runs on user machines
// before they have a session. Rate-limited by session_id + IP.
//
// Body (JSON):
// {
//   "session_id": "<uuid>",
//   "event_type": "installer_opened" | "license_accepted" | ...,
//   "percent": 42,
//   "label": "Staging MCP tools",
//   "error_code": "ENOTFOUND",
//   "error_message": "...",
//   "license_key": "ACLD-XXXX-XXXX-XXXX-XXXX",
//   "machine_id_hash": "<sha256 hex>",
//   "os": "windows" | "macos" | "linux",
//   "os_version": "10.0.22631",
//   "app_version": "0.9.6",
//   "installer_version": "0.9.6",
//   "metadata": { ... }
// }

import { serviceClient } from "../_shared/supabase.ts";
import { corsHeaders, jsonResponse, handleOptions } from "../_shared/cors.ts";

const VALID_EVENT_TYPES = new Set([
  "installer_opened",
  "license_accepted",
  "install_started",
  "install_progress",
  "install_complete",
  "install_error",
  "installer_cancelled",
  "launch_clicked",
  "first_login",
  "first_agent_spawn",
  "first_vault_op",
  "app_opened",
  "app_closed",
]);

const VALID_OS = new Set(["windows", "macos", "linux"]);

async function sha256Hex(input: string): Promise<string> {
  const buf = await crypto.subtle.digest(
    "SHA-256",
    new TextEncoder().encode(input),
  );
  return Array.from(new Uint8Array(buf))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

Deno.serve(async (req) => {
  if (req.method === "OPTIONS") return handleOptions();
  if (req.method !== "POST") {
    return jsonResponse({ error: "method_not_allowed" }, { status: 405 });
  }

  let payload: any;
  try {
    payload = await req.json();
  } catch {
    return jsonResponse({ error: "invalid_json" }, { status: 400 });
  }

  // Validation
  if (!payload.session_id || typeof payload.session_id !== "string") {
    return jsonResponse({ error: "session_id_required" }, { status: 400 });
  }
  if (!VALID_EVENT_TYPES.has(payload.event_type)) {
    return jsonResponse({ error: "invalid_event_type" }, { status: 400 });
  }
  if (payload.os && !VALID_OS.has(payload.os)) {
    return jsonResponse({ error: "invalid_os" }, { status: 400 });
  }
  if (
    payload.percent != null &&
    (typeof payload.percent !== "number" ||
      payload.percent < 0 ||
      payload.percent > 100)
  ) {
    return jsonResponse({ error: "invalid_percent" }, { status: 400 });
  }

  const sb = serviceClient();

  // Resolve license + user, if a key was provided
  let userId: string | null = null;
  let installId: string | null = null;
  let licenseKeyPrefix: string | null = null;

  if (payload.license_key && typeof payload.license_key === "string") {
    licenseKeyPrefix = payload.license_key.substring(0, 8);

    const { data: license } = await sb
      .from("licenses")
      .select("id, user_id")
      .eq("license_key", payload.license_key)
      .maybeSingle();

    if (license) {
      userId = license.user_id;

      // If this is an install_complete event and we have a machine_id_hash,
      // upsert the install row so future events can link to it.
      if (
        payload.event_type === "install_complete" &&
        payload.machine_id_hash &&
        payload.os &&
        payload.app_version
      ) {
        const { data: install } = await sb
          .from("installs")
          .upsert(
            {
              license_id: license.id,
              user_id: license.user_id,
              machine_id_hash: payload.machine_id_hash,
              os: payload.os,
              os_version: payload.os_version ?? null,
              arch: payload.arch ?? null,
              app_version: payload.app_version,
              installer_version: payload.installer_version ?? null,
              status: "active",
              last_seen_at: new Date().toISOString(),
            },
            { onConflict: "license_id,machine_id_hash" },
          )
          .select("id")
          .maybeSingle();

        if (install) installId = install.id;
      } else if (payload.machine_id_hash) {
        // Look up existing install to attach the event
        const { data: install } = await sb
          .from("installs")
          .select("id")
          .eq("license_id", license.id)
          .eq("machine_id_hash", payload.machine_id_hash)
          .maybeSingle();

        if (install) installId = install.id;
      }
    }
  }

  // Hash the caller's IP for privacy-aware analytics
  const ip =
    req.headers.get("cf-connecting-ip") ??
    req.headers.get("x-forwarded-for")?.split(",")[0].trim() ??
    null;
  const ipHash = ip ? await sha256Hex(ip) : null;
  const country = req.headers.get("cf-ipcountry") ?? null;

  const { data: event, error } = await sb
    .from("install_events")
    .insert({
      install_id: installId,
      user_id: userId,
      license_key_prefix: licenseKeyPrefix,
      session_id: payload.session_id,
      event_type: payload.event_type,
      percent: payload.percent ?? null,
      label: payload.label ?? null,
      error_code: payload.error_code ?? null,
      error_message: payload.error_message ?? null,
      machine_id_hash: payload.machine_id_hash ?? null,
      os: payload.os ?? null,
      os_version: payload.os_version ?? null,
      app_version: payload.app_version ?? null,
      installer_version: payload.installer_version ?? null,
      ip_hash: ipHash,
      country,
      user_agent: req.headers.get("user-agent"),
      metadata: payload.metadata ?? {},
      occurred_at: payload.occurred_at ?? new Date().toISOString(),
    })
    .select("id")
    .single();

  if (error) {
    console.error("[ingest-install-event]", error);
    return jsonResponse(
      { error: "insert_failed", message: error.message },
      { status: 500 },
    );
  }

  return jsonResponse({
    ok: true,
    event_id: event.id,
    install_id: installId,
    linked_user: userId != null,
  });
});
