// Activate a license on a specific machine.
//
// Called from the dashboard after first login, or from a "Redeem license key"
// flow. Requires authenticated user (verify_jwt=true in config.toml).
//
// POST https://cjjcdwrnpzwlvradbros.supabase.co/functions/v1/activate-license
// Authorization: Bearer <user_jwt>
//
// Body:
// {
//   "license_key": "ACLD-XXXX-XXXX-XXXX-XXXX",
//   "machine_id_hash": "<sha256 hex>",
//   "os": "windows" | "macos" | "linux",
//   "os_version": "10.0.22631",
//   "arch": "x64",
//   "app_version": "0.9.6"
// }

import { serviceClient, userClient } from "../_shared/supabase.ts";
import { jsonResponse, handleOptions } from "../_shared/cors.ts";

Deno.serve(async (req) => {
  if (req.method === "OPTIONS") return handleOptions();
  if (req.method !== "POST") {
    return jsonResponse({ error: "method_not_allowed" }, { status: 405 });
  }

  const authHeader = req.headers.get("Authorization");
  if (!authHeader) {
    return jsonResponse({ error: "unauthorized" }, { status: 401 });
  }

  // Resolve the caller's user_id via their JWT
  const userSb = userClient(authHeader);
  const { data: userData, error: userErr } = await userSb.auth.getUser();
  if (userErr || !userData.user) {
    return jsonResponse({ error: "invalid_jwt" }, { status: 401 });
  }

  let payload: any;
  try {
    payload = await req.json();
  } catch {
    return jsonResponse({ error: "invalid_json" }, { status: 400 });
  }

  const { license_key, machine_id_hash, os, os_version, arch, app_version } =
    payload;

  if (!license_key || !machine_id_hash || !os || !app_version) {
    return jsonResponse(
      {
        error: "missing_fields",
        required: ["license_key", "machine_id_hash", "os", "app_version"],
      },
      { status: 400 },
    );
  }

  const sb = serviceClient();

  // Find the license — must be owned by this user and active/pending
  const { data: license, error: licErr } = await sb
    .from("licenses")
    .select("id, user_id, status, max_installs, product, plan, expires_at")
    .eq("license_key", license_key)
    .maybeSingle();

  if (licErr) {
    return jsonResponse({ error: "db_error", message: licErr.message }, {
      status: 500,
    });
  }
  if (!license) {
    return jsonResponse({ error: "license_not_found" }, { status: 404 });
  }
  if (license.user_id !== userData.user.id) {
    return jsonResponse({ error: "license_not_owned_by_user" }, {
      status: 403,
    });
  }
  if (license.status !== "active" && license.status !== "pending_activation") {
    return jsonResponse(
      { error: "license_inactive", status: license.status },
      { status: 403 },
    );
  }
  if (license.expires_at && new Date(license.expires_at) < new Date()) {
    return jsonResponse({ error: "license_expired" }, { status: 403 });
  }

  // Upsert install. The check_install_quota trigger enforces max_installs.
  const { data: install, error: installErr } = await sb
    .from("installs")
    .upsert(
      {
        license_id: license.id,
        user_id: license.user_id,
        machine_id_hash,
        os,
        os_version: os_version ?? null,
        arch: arch ?? null,
        app_version,
        status: "active",
        last_seen_at: new Date().toISOString(),
      },
      { onConflict: "license_id,machine_id_hash" },
    )
    .select("id, installed_at")
    .single();

  if (installErr) {
    // Quota violation surfaces as a check_violation
    if (
      installErr.message.includes("install limit") ||
      installErr.code === "23514"
    ) {
      return jsonResponse(
        {
          error: "install_limit_reached",
          max_installs: license.max_installs,
        },
        { status: 403 },
      );
    }
    return jsonResponse(
      { error: "activation_failed", message: installErr.message },
      { status: 500 },
    );
  }

  // Flip license to active on first activation
  if (license.status === "pending_activation") {
    await sb
      .from("licenses")
      .update({
        status: "active",
        activated_at: new Date().toISOString(),
      })
      .eq("id", license.id);
  }

  return jsonResponse({
    ok: true,
    install_id: install.id,
    license_id: license.id,
    product: license.product,
    plan: license.plan,
    installed_at: install.installed_at,
  });
});
