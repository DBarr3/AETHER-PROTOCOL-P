/**
 * AetherCloud — Analysis Cache Store
 * Persistent storage for directory analysis summaries.
 * Entries are keyed by absolute path with a fingerprint for staleness detection.
 *
 * Aether Systems LLC — Patent Pending
 */

const Store = require('electron-store');

const analysisCache = new Store({
    name: 'aether-analysis-cache',
    schema: {
        entries: {
            type: 'object',
            default: {},
            additionalProperties: {
                type: 'object',
                properties: {
                    path:        { type: 'string' },
                    label:       { type: 'string' },
                    analyzedAt:  { type: 'string' },
                    fileCount:   { type: 'number' },
                    passes:      { type: 'number' },
                    summary:     { type: 'string' },
                    fileMap:     { type: 'array', items: { type: 'string' } },
                    fingerprint: { type: 'string' },
                },
            },
        },
    },
});

module.exports = analysisCache;
