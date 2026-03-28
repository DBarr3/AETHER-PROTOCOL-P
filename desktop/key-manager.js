/**
 * AetherCloud-L Desktop — Secure Key Manager
 * Aether Systems LLC · Patent Pending
 *
 * Stores API keys using electron-store with AES encryption at rest.
 * Keys are persisted in the Electron userData folder (platform-specific).
 *
 * On startup, hydrate() injects stored keys into:
 *   - process.env (ANTHROPIC_API_KEY)
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
 */
function hydrate() {
  console.log('[KeyManager] Hydrating keys into runtime...');

  const anthropicKey = getKey('ANTHROPIC_API_KEY');
  if (anthropicKey) {
    process.env.ANTHROPIC_API_KEY = anthropicKey;
    console.log('[KeyManager] Injected ANTHROPIC_API_KEY into process.env');
  }

  const storedKeys = getAllKeyNames();
  console.log(`[KeyManager] Hydration complete — ${storedKeys.length} key(s): [${storedKeys.join(', ')}]`);
}

/**
 * validate() — check which keys are usable.
 * Returns { anthropic: bool }.
 */
function validate() {
  const anthropic = !!getKey('ANTHROPIC_API_KEY');
  return { anthropic };
}

module.exports = {
  setKey,
  getKey,
  hasKey,
  deleteKey,
  getAllKeyNames,
  hydrate,
  validate,
};
