/**
 * AetherCloud-L Desktop — Secure Key Manager
 * Aether Systems LLC · Patent Pending
 *
 * Stores API keys using electron-store with AES encryption at rest.
 * Keys are persisted in the Electron userData folder (platform-specific).
 *
 * On startup, hydrate() injects stored keys into:
 *   - process.env (ANTHROPIC_API_KEY)
 *   - ~/.aether/ibm_credentials.json (IBM Quantum)
 *
 * SECURITY: Key values are NEVER logged or exposed. Only key names are logged.
 */

const { app } = require('electron');
const crypto   = require('crypto');
const path     = require('path');
const fs       = require('fs');

// ── Encryption key derivation ────────────────────────
// Derive a deterministic encryption key from the machine-specific userData path.
// This ties the encrypted store to this machine's user profile.
function deriveEncryptionKey() {
  const seed = app.getPath('userData');
  return crypto.createHash('sha256').update(seed).digest('hex');
}

// ── Lazy-init store (electron-store requires app to be ready) ──
let _store = null;
function getStore() {
  if (_store) return _store;
  const Store = require('electron-store');
  _store = new Store({
    name: 'aethercloud-keys',
    encryptionKey: deriveEncryptionKey(),
    schema: {
      keys: {
        type: 'object',
        default: {},
      },
    },
  });
  return _store;
}

// ── Key names allowed ────────────────────────────────
const ALLOWED_KEYS = new Set([
  'ANTHROPIC_API_KEY',
  'IBM_QUANTUM_API_KEY',
]);

// ── Public API ───────────────────────────────────────

function setKey(name, value) {
  if (!ALLOWED_KEYS.has(name)) {
    console.warn(`[KeyManager] Rejected unknown key name: ${name}`);
    return false;
  }
  const store = getStore();
  const keys = store.get('keys', {});
  keys[name] = value;
  store.set('keys', keys);
  console.log(`[KeyManager] Stored key: ${name}`);
  return true;
}

function getKey(name) {
  const store = getStore();
  const keys = store.get('keys', {});
  return keys[name] || null;
}

function hasKey(name) {
  const store = getStore();
  const keys = store.get('keys', {});
  return !!keys[name];
}

function deleteKey(name) {
  const store = getStore();
  const keys = store.get('keys', {});
  if (keys[name]) {
    delete keys[name];
    store.set('keys', keys);
    console.log(`[KeyManager] Deleted key: ${name}`);
    return true;
  }
  return false;
}

function getAllKeyNames() {
  const store = getStore();
  const keys = store.get('keys', {});
  return Object.keys(keys);
}

/**
 * hydrate() — called once on app ready.
 * Injects stored keys into the runtime environment:
 *   - ANTHROPIC_API_KEY → process.env
 *   - IBM_QUANTUM_API_KEY → ~/.aether/ibm_credentials.json + process.env
 */
function hydrate() {
  console.log('[KeyManager] Hydrating keys into runtime...');

  // Anthropic API key → process.env
  const anthropicKey = getKey('ANTHROPIC_API_KEY');
  if (anthropicKey) {
    process.env.ANTHROPIC_API_KEY = anthropicKey;
    console.log('[KeyManager] Injected ANTHROPIC_API_KEY into process.env');
  }

  // IBM Quantum API key → ~/.aether/ibm_credentials.json + process.env
  const ibmKey = getKey('IBM_QUANTUM_API_KEY');
  if (ibmKey) {
    process.env.IBM_QUANTUM_API_KEY = ibmKey;
    console.log('[KeyManager] Injected IBM_QUANTUM_API_KEY into process.env');
    writeIBMCredentials(ibmKey);
  }

  const storedKeys = getAllKeyNames();
  console.log(`[KeyManager] Hydration complete — ${storedKeys.length} key(s): [${storedKeys.join(', ')}]`);
}

/**
 * Write IBM credentials to ~/.aether/ibm_credentials.json
 * This is the path that quantum_backend.py's load_ibm_credentials() searches.
 */
function writeIBMCredentials(apiKey) {
  try {
    const homeDir = require('os').homedir();
    const aetherDir = path.join(homeDir, '.aether');
    const credPath  = path.join(aetherDir, 'ibm_credentials.json');

    fs.mkdirSync(aetherDir, { recursive: true });
    fs.writeFileSync(credPath, JSON.stringify({
      name: 'AETHER1',
      apikey: apiKey,
    }, null, 2), { mode: 0o600 });

    console.log('[KeyManager] Wrote IBM credentials to ~/.aether/ibm_credentials.json');
  } catch (err) {
    console.error('[KeyManager] Failed to write IBM credentials:', err.message);
  }
}

/**
 * getEnvForPython() — returns a copy of process.env with stored keys injected.
 * Used when spawning the Python backend process.
 */
function getEnvForPython() {
  const env = { ...process.env };

  const anthropicKey = getKey('ANTHROPIC_API_KEY');
  if (anthropicKey) env.ANTHROPIC_API_KEY = anthropicKey;

  const ibmKey = getKey('IBM_QUANTUM_API_KEY');
  if (ibmKey) env.IBM_QUANTUM_API_KEY = ibmKey;

  return env;
}

/**
 * validate() — check which keys are usable.
 * Returns { anthropic: bool, ibm: bool }.
 */
function validate() {
  const anthropic = !!getKey('ANTHROPIC_API_KEY');

  // IBM: either in store, or the credentials file exists
  let ibm = !!getKey('IBM_QUANTUM_API_KEY');
  if (!ibm) {
    try {
      const homeDir = require('os').homedir();
      const credPath = path.join(homeDir, '.aether', 'ibm_credentials.json');
      ibm = fs.existsSync(credPath);
    } catch {
      ibm = false;
    }
  }

  return { anthropic, ibm };
}

module.exports = {
  setKey,
  getKey,
  hasKey,
  deleteKey,
  getAllKeyNames,
  hydrate,
  getEnvForPython,
  validate,
};
