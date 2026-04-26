// embedder.js
// Pluggable embedding adapter. Default: deterministic hash-based pseudo-embedding
// (no API call, no model download — lets the entire Galaxy pipeline work
// end-to-end without committing to an embedding provider).
//
// To swap to a real model:
//   const { OpenAIEmbedder } = require('./embedder-openai'); // when added
//   const embedder = new OpenAIEmbedder({ apiKey: process.env.OPENAI_API_KEY });
//
// All embedders return Float32Array of fixed `dim` length.

const DIM = 384; // matches sentence-transformers/all-MiniLM-L6-v2 (common default)

class StubEmbedder {
  constructor() { this.dim = DIM; this.kind = 'stub'; }

  /** Deterministic pseudo-random vector keyed on the text. */
  async embed(text) {
    const out = new Float32Array(DIM);
    if (!text) return out;
    // Mix the text into a 32-bit seed (fnv1a-ish), then expand.
    let h = 2166136261 >>> 0;
    for (let i = 0; i < text.length; i++) {
      h ^= text.charCodeAt(i);
      h = Math.imul(h, 16777619) >>> 0;
    }
    // mulberry32 PRNG seeded by h, projected to [-1, 1]
    let s = h;
    for (let i = 0; i < DIM; i++) {
      s = (s + 0x6D2B79F5) >>> 0;
      let t = s;
      t = Math.imul(t ^ (t >>> 15), t | 1);
      t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
      const r = ((t ^ (t >>> 14)) >>> 0) / 4294967295;
      out[i] = r * 2 - 1;
    }
    // L2-normalize for cosine-style HNSW
    let norm = 0;
    for (let i = 0; i < DIM; i++) norm += out[i] * out[i];
    norm = Math.sqrt(norm) || 1;
    for (let i = 0; i < DIM; i++) out[i] /= norm;
    return out;
  }
}

module.exports = { StubEmbedder, DIM };
