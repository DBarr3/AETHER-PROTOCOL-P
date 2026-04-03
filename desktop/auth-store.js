/**
 * AetherCloud — Encrypted Auth Store
 * Machine-bound persistent storage for session tokens and license key.
 *
 * Aether Systems LLC — Patent Pending
 */

const Store = require('electron-store');
const { machineIdSync } = require('node-machine-id');

const encKey = machineIdSync({ original: true });

const authStore = new Store({
    name: 'aether-cloud-auth',
    encryptionKey: encKey,
    schema: {
        sessionToken: { type: 'string' },
        userId: { type: 'string' },
        email: { type: 'string' },
        rememberMe: { type: 'boolean', default: true },
        lastLogin: { type: 'string' },
        serverUrl: { type: 'string' },
        licenseKey: { type: 'string' },
        plan: { type: 'string' },
        // NOTE: accessKey (password) is intentionally NOT stored — passwords are never persisted.
        // Session renewal is handled by redirecting to login on 401.
    },
});

module.exports = authStore;
