// Service-role Supabase client for server-side writes (bypasses RLS).
// Only instantiate inside edge functions — never ship service_role to browsers.

import { createClient, SupabaseClient } from "https://esm.sh/@supabase/supabase-js@2.45.0";

let _serviceClient: SupabaseClient | null = null;

export function serviceClient(): SupabaseClient {
  if (_serviceClient) return _serviceClient;

  const url = Deno.env.get("SUPABASE_URL");
  const serviceKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY");

  if (!url || !serviceKey) {
    throw new Error(
      "Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY env vars",
    );
  }

  _serviceClient = createClient(url, serviceKey, {
    auth: { persistSession: false, autoRefreshToken: false },
  });

  return _serviceClient;
}

/** Client that honors the caller's JWT — use inside verify_jwt=true functions. */
export function userClient(authHeader: string | null): SupabaseClient {
  const url = Deno.env.get("SUPABASE_URL");
  const anonKey = Deno.env.get("SUPABASE_ANON_KEY");

  if (!url || !anonKey) {
    throw new Error("Missing SUPABASE_URL or SUPABASE_ANON_KEY env vars");
  }

  return createClient(url, anonKey, {
    global: { headers: { Authorization: authHeader ?? "" } },
    auth: { persistSession: false, autoRefreshToken: false },
  });
}
