// vector-index.js
// Off-heap HNSW index per repo. Embeddings live in native memory
// (hnswlib-node), NEVER on the JS heap. This is the contract that
// keeps the renderer under its 1.2 GB memory budget.
//
// Per-repo on-disk layout (under app.getPath('userData')/aether-galaxy):
//   <repoId>.bin       — hnswlib binary index
//   <repoId>.meta.json — { repoId, dim, files: [{fileId, path, label}], builtAt }
//
// Index is loaded lazily — first call to searchRepo/getMeta materializes it.
// Use closeRepo(id) to drop a repo from memory (file stays on disk).

const fs = require('node:fs');
const path = require('node:path');
const { HierarchicalNSW } = require('hnswlib-node');
const { StubEmbedder, DIM } = require('./embedder');

const DEFAULT_DIM = DIM;
const SPACE = 'cosine'; // L2-normalized vectors, cosine = inner product distance
const M = 16;           // HNSW graph degree
const EF_CONSTRUCTION = 200;

class VectorIndex {
  /**
   * @param {object} opts
   * @param {string} opts.dataDir absolute path under userData
   * @param {object} [opts.embedder] anything with .embed(text) -> Float32Array
   * @param {(repoId: string, fileId: string, max: number) => Promise<string>} [opts.fileReader]
   *   optional injection for readFileSlice — defaults to fs.readFile of meta.path
   */
  constructor(opts) {
    if (!opts || !opts.dataDir) throw new Error('VectorIndex: dataDir required');
    this.dataDir = opts.dataDir;
    this.dim = (opts.embedder && opts.embedder.dim) || DEFAULT_DIM;
    this.embedder = opts.embedder || new StubEmbedder();
    this.fileReader = opts.fileReader || null;
    /** @type {Map<string, { idx: HierarchicalNSW, meta: { repoId, dim, files, builtAt } }>} */
    this.openIndexes = new Map();
    fs.mkdirSync(this.dataDir, { recursive: true });
  }

  // ─── public API ────────────────────────────────────────────────────

  /** Embed a query string into a Float32Array. */
  async embed(text) {
    return this.embedder.embed(text);
  }

  /** Lists repos that have been indexed (have a meta.json on disk). */
  async listRepos() {
    const entries = await fs.promises.readdir(this.dataDir, { withFileTypes: true });
    return entries
      .filter(e => e.isFile() && e.name.endsWith('.meta.json'))
      .map(e => e.name.replace(/\.meta\.json$/, ''));
  }

  /**
   * Index a repo's files. files = [{ fileId, path, text }]. Vectors are
   * computed via the embedder. Overwrites any existing index for repoId.
   */
  async indexRepo(repoId, files) {
    if (!repoId) throw new Error('indexRepo: repoId required');
    const max = Math.max(files.length, 16);
    const idx = new HierarchicalNSW(SPACE, this.dim);
    idx.initIndex(max, M, EF_CONSTRUCTION, 100);
    const meta = { repoId, dim: this.dim, files: [], builtAt: Date.now() };

    for (let i = 0; i < files.length; i++) {
      const f = files[i];
      const v = await this.embedder.embed(f.text || f.path || '');
      idx.addPoint(Array.from(v), i);
      meta.files.push({ fileId: f.fileId, path: f.path, label: i });
    }

    const binPath = this._binPath(repoId);
    const metaPath = this._metaPath(repoId);
    idx.writeIndexSync(binPath);
    await fs.promises.writeFile(metaPath, JSON.stringify(meta), 'utf8');
    this.openIndexes.set(repoId, { idx, meta });
    return { fileCount: meta.files.length };
  }

  /**
   * Search a repo. Returns ranked VectorHit[] (fileId, path, score, snippetPreview).
   * `embedding` should be a Float32Array of length `this.dim`.
   */
  async searchRepo(repoId, embedding, k) {
    const open = await this._openRepo(repoId);
    if (!open) return [];
    const limit = Math.min(k || 10, open.meta.files.length);
    if (limit <= 0) return [];
    const result = open.idx.searchKnn(Array.from(embedding), limit);
    const hits = [];
    for (let i = 0; i < result.neighbors.length; i++) {
      const label = result.neighbors[i];
      const distance = result.distances[i];
      const fileMeta = open.meta.files[label];
      if (!fileMeta) continue;
      // cosine distance ∈ [0, 2]; convert to similarity score ∈ [0, 1]
      const score = Math.max(0, 1 - distance / 2);
      hits.push({
        fileId: fileMeta.fileId,
        path: fileMeta.path,
        score,
        snippetPreview: undefined, // populated lazily via readFileSlice
      });
    }
    return hits;
  }

  /**
   * Read a file slice. Default implementation reads meta.path from disk.
   * Pass an `opts.fileReader` to the constructor for custom resolution
   * (e.g. when files live in a remote repo or sandboxed area).
   */
  async readFileSlice(repoId, fileId, maxBytes) {
    const open = await this._openRepo(repoId);
    if (!open) return '';
    if (this.fileReader) return this.fileReader(repoId, fileId, maxBytes);
    const fileMeta = open.meta.files.find(f => f.fileId === fileId);
    if (!fileMeta || !fileMeta.path) return '';
    try {
      const fh = await fs.promises.open(fileMeta.path, 'r');
      try {
        const buf = Buffer.alloc(Math.min(maxBytes, 1024 * 1024));
        const { bytesRead } = await fh.read(buf, 0, buf.length, 0);
        return buf.subarray(0, bytesRead).toString('utf8');
      } finally {
        await fh.close();
      }
    } catch {
      return '';
    }
  }

  /** Drop a repo from in-memory cache (file on disk preserved). */
  closeRepo(repoId) {
    this.openIndexes.delete(repoId);
  }

  /** Has this repo been indexed (meta.json present)? */
  hasRepo(repoId) {
    return fs.existsSync(this._metaPath(repoId));
  }

  // ─── internals ─────────────────────────────────────────────────────

  async _openRepo(repoId) {
    const cached = this.openIndexes.get(repoId);
    if (cached) return cached;
    const binPath = this._binPath(repoId);
    const metaPath = this._metaPath(repoId);
    if (!fs.existsSync(binPath) || !fs.existsSync(metaPath)) return null;
    const meta = JSON.parse(await fs.promises.readFile(metaPath, 'utf8'));
    const idx = new HierarchicalNSW(SPACE, meta.dim || this.dim);
    idx.readIndexSync(binPath);
    const entry = { idx, meta };
    this.openIndexes.set(repoId, entry);
    return entry;
  }

  _binPath(repoId) {
    return path.join(this.dataDir, `${this._sanitize(repoId)}.bin`);
  }
  _metaPath(repoId) {
    return path.join(this.dataDir, `${this._sanitize(repoId)}.meta.json`);
  }
  _sanitize(s) {
    return String(s).replace(/[^\w.-]+/g, '_');
  }
}

module.exports = { VectorIndex, DEFAULT_DIM };
