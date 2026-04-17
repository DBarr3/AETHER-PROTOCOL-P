/**
 * AetherCloud installer telemetry client.
 * Runs in the main process — ships install_events to Supabase.
 *
 * Safe to ship: only posts anonymized event data. Uses the Supabase anon key
 * which is designed for client-side use and is protected by RLS + the
 * ingest-install-event edge function's own validation.
 *
 * Environment variables (optional — sensible defaults shipped):
 *   AETHER_TELEMETRY_URL    — override the ingest endpoint
 *   AETHER_TELEMETRY_ANON   — override the anon key
 *   AETHER_TELEMETRY_OFF    — set truthy to disable entirely (dev/CI)
 */

const crypto = require('crypto');
const os = require('os');
const https = require('https');
const { URL } = require('url');

// ── Config ──────────────────────────────────────────────────
const PROJECT_URL = 'https://cjjcdwrnpzwlvradbros.supabase.co';
// Publishable key — safe to embed in client apps by design.
// Protected by RLS policies and by the edge function's own payload validation.
// Rotate via Supabase Dashboard → Settings → API → API Keys.
const DEFAULT_ANON_KEY = 'sb_publishable_phtgDkX4AoIyp2_QCmX3Hw_beRB_fDR';

const ENDPOINT =
  process.env.AETHER_TELEMETRY_URL ||
  `${PROJECT_URL}/functions/v1/ingest-install-event`;

const ANON_KEY = process.env.AETHER_TELEMETRY_ANON || DEFAULT_ANON_KEY;

const DISABLED = !!process.env.AETHER_TELEMETRY_OFF;

// ── Session + machine identity ──────────────────────────────
const sessionId = crypto.randomUUID();

let _machineIdHash = null;
function machineIdHash() {
  if (_machineIdHash) return _machineIdHash;
  try {
    const { machineIdSync } = require('node-machine-id');
    const raw = machineIdSync({ original: true });
    _machineIdHash = crypto.createHash('sha256').update(raw).digest('hex');
  } catch {
    // Fallback: hostname + homedir — stable per user but not bulletproof
    const raw = os.hostname() + '|' + os.homedir();
    _machineIdHash = crypto.createHash('sha256').update(raw).digest('hex');
  }
  return _machineIdHash;
}

// ── Platform detection ──────────────────────────────────────
function platformName() {
  const p = process.platform;
  if (p === 'win32') return 'windows';
  if (p === 'darwin') return 'macos';
  return 'linux';
}

function context(extra = {}) {
  return {
    session_id: sessionId,
    machine_id_hash: machineIdHash(),
    os: platformName(),
    os_version: os.release(),
    arch: process.arch,
    app_version: require('./package.json').version || '0.0.0',
    installer_version: require('./package.json').version || '0.0.0',
    ...extra,
  };
}

// ── Network send — non-blocking, fire-and-forget ───────────
function post(payload) {
  return new Promise((resolve) => {
    if (DISABLED) return resolve({ skipped: true });
    if (!ANON_KEY) {
      console.warn('[telemetry] no anon key configured — skipping');
      return resolve({ skipped: true, reason: 'no_anon_key' });
    }

    const body = JSON.stringify(payload);
    const url = new URL(ENDPOINT);

    const req = https.request(
      {
        method: 'POST',
        hostname: url.hostname,
        path: url.pathname,
        headers: {
          'Content-Type': 'application/json',
          'Content-Length': Buffer.byteLength(body),
          apikey: ANON_KEY,
          Authorization: `Bearer ${ANON_KEY}`,
        },
      },
      (res) => {
        let chunks = '';
        res.on('data', (d) => (chunks += d));
        res.on('end', () => {
          let parsed = null;
          try { parsed = JSON.parse(chunks); } catch { parsed = chunks; }
          resolve({ status: res.statusCode, body: parsed });
        });
      },
    );

    req.on('error', (err) => {
      // Never crash the installer on telemetry failure
      resolve({ error: err.message });
    });

    req.setTimeout(5000, () => {
      req.destroy();
      resolve({ error: 'timeout' });
    });

    req.write(body);
    req.end();
  });
}

// ── Public API ─────────────────────────────────────────────
/**
 * Emit an install event. event_type must be one of the enum values in
 * public.install_event_type. Extra fields (percent, label, license_key,
 * error_code, error_message, metadata) are merged into the payload.
 */
async function emit(event_type, extra = {}) {
  const payload = {
    event_type,
    occurred_at: new Date().toISOString(),
    ...context(extra),
  };
  return post(payload);
}

module.exports = {
  sessionId,
  machineIdHash,
  emit,
  ENDPOINT,
};
