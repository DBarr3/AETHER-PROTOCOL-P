// galaxy/layout-worker.js
// ─────────────────────────────────────────────────────────────────────
// Web Worker — 3D force-directed layout for the Vault single-tier view.
//
// Architecture constants (must match galaxy-app.js):
//   R_PROJECT  = 60   — file orbit radius per project
//   MIN_SEP    = 240  — hard floor between project centers (4× R_PROJECT)
//   TYPICAL    = 320  — target pairwise distance
//
// Why a worker: even at ~200 projects, a stable force simulation runs
// 400+ ticks; doing it on the main thread janks the camera fly and
// the OrbitControls feel. Workers are isolated; the result is a one-shot
// postMessage with the final positions.
//
// Why an inline force algorithm (no d3-force-3d): Electron renderers
// loaded via file:// can't reach esm.sh (mixed-origin CSP) and bundling
// d3 into a worker chunk would mean another esbuild pass. The math here
// is small — four forces (charge, link, center, collide) + Verlet
// integration — and produces a perfectly readable layout for the 5–200
// project regime we're optimizing for.
//
// Protocol:
//   postMessage({ projects: ProjectMeta[], iterations?: number })
//   ← onmessage: { ok, positions: [{ id, x, y, z }, ...], elapsedMs, count }
//   on error:    { ok: false, error: string }
//
// ProjectMeta — duck-typed; we only read .id, .name, .path:
//   { id: string, name: string, path?: string, ... }
// ─────────────────────────────────────────────────────────────────────

"use strict";

// Common-word stoplist — excluded from name/path tokens so two unrelated
// projects don't cluster just because both have "src" or "test" in them.
const STOP = new Set([
  "src", "app", "test", "tests", "docs", "doc",
  "node_modules", "dist", "build", "out", "lib",
  "bin", "tmp", "temp", "vendor", "third_party",
  "the", "and", "for", "with",
]);

function tokenize(s) {
  if (!s) return new Set();
  const out = new Set();
  for (const t of String(s).toLowerCase().split(/[^a-z0-9]+/)) {
    if (t.length >= 3 && !STOP.has(t)) out.add(t);
  }
  return out;
}

// Build link list from name/path token overlap. Edge weight = number of
// shared tokens. The simulation interprets weight as "stronger pull,
// shorter rest length" so similarly-named projects pack tighter.
function buildLinks(projects) {
  const tokens = projects.map(p => tokenize((p.name || "") + " " + (p.path || "")));
  const links = [];
  for (let i = 0; i < projects.length; i++) {
    for (let j = i + 1; j < projects.length; j++) {
      let overlap = 0;
      for (const t of tokens[i]) if (tokens[j].has(t)) overlap++;
      if (overlap > 0) {
        links.push({ source: i, target: j, weight: overlap });
      }
    }
  }
  return links;
}

// Deterministic seeded RNG (mulberry32) — same input → same layout, so
// re-entering Vault mode doesn't re-shuffle the universe.
function mulberry32(seed) {
  let a = seed >>> 0;
  return function () {
    a |= 0; a = (a + 0x6D2B79F5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function seedFromProjects(projects) {
  let h = 0x811c9dc5;
  for (const p of projects) {
    const s = String(p.id || "");
    for (let i = 0; i < s.length; i++) {
      h = Math.imul(h ^ s.charCodeAt(i), 0x01000193);
    }
  }
  return h >>> 0;
}

function simulate(projects, iterations) {
  const n = projects.length;
  if (n === 0) return [];
  const rand = mulberry32(seedFromProjects(projects));
  const links = buildLinks(projects);

  // ── Architecture constants ─────────────────────────────────────────
  const MIN_SEP  = 240;    // hard floor between project centers
  const TYPICAL  = 320;    // target pairwise distance

  // Initial random positions — large enough that bodies don't start on
  // top of each other. Scaled for the wider universe.
  const SPREAD = 200;
  const x = new Float32Array(n);
  const y = new Float32Array(n);
  const z = new Float32Array(n);
  const vx = new Float32Array(n);
  const vy = new Float32Array(n);
  const vz = new Float32Array(n);
  for (let i = 0; i < n; i++) {
    x[i] = (rand() - 0.5) * SPREAD;
    y[i] = (rand() - 0.5) * SPREAD;
    z[i] = (rand() - 0.5) * SPREAD;
  }

  // Force constants — tuned for the single-tier vault architecture.
  // Produces the "constellations separated by clear breathing room" feel.
  const CHARGE         = -600;   // node-node repulsion (Coulomb-like)
  const CHARGE_SOFT    = 1.0;    // softening to avoid singularities at r→0
  const LINK_STIFF     = 0.04;   // spring constant for token-overlap links
  const CENTER_PULL    = 0.006;  // toward (0,0,0) — keeps the universe finite
  const VELOCITY_DECAY = 0.75;   // damping per tick (1 - friction)
  const ALPHA_INITIAL  = 1.0;
  const ALPHA_DECAY    = 0.018;  // exponential cool-down
  const MAX_VELOCITY   = 25;

  const ITER = Math.max(100, iterations || 400);
  let alpha = ALPHA_INITIAL;

  for (let step = 0; step < ITER; step++) {
    // ── Charge force: every pair repels ──────────────────────────────
    for (let i = 0; i < n; i++) {
      for (let j = i + 1; j < n; j++) {
        const dx = x[i] - x[j];
        const dy = y[i] - y[j];
        const dz = z[i] - z[j];
        const r2 = dx * dx + dy * dy + dz * dz + CHARGE_SOFT;
        const r = Math.sqrt(r2);
        const f = (CHARGE * alpha) / (r2 * r);
        vx[i] += dx * f; vy[i] += dy * f; vz[i] += dz * f;
        vx[j] -= dx * f; vy[j] -= dy * f; vz[j] -= dz * f;
      }
    }

    // ── Link force: token-overlap pairs attracted toward rest length
    for (const l of links) {
      const i = l.source, j = l.target;
      const dx = x[j] - x[i];
      const dy = y[j] - y[i];
      const dz = z[j] - z[i];
      const r = Math.sqrt(dx * dx + dy * dy + dz * dz) + 1e-6;
      // Stronger overlap → shorter rest length (pulls them closer).
      // Base rest length is TYPICAL; strong overlap shortens it.
      const restLen = TYPICAL / (1 + l.weight * 0.5);
      const k = LINK_STIFF * alpha;
      const force = k * (r - restLen) / r;
      vx[i] += dx * force; vy[i] += dy * force; vz[i] += dz * force;
      vx[j] -= dx * force; vy[j] -= dy * force; vz[j] -= dz * force;
    }

    // ── Centering force: weak constant pull toward origin ────────────
    for (let i = 0; i < n; i++) {
      vx[i] -= x[i] * CENTER_PULL * alpha;
      vy[i] -= y[i] * CENTER_PULL * alpha;
      vz[i] -= z[i] * CENTER_PULL * alpha;
    }

    // ── Integrate + damp + clamp velocity ────────────────────────────
    for (let i = 0; i < n; i++) {
      vx[i] *= VELOCITY_DECAY;
      vy[i] *= VELOCITY_DECAY;
      vz[i] *= VELOCITY_DECAY;
      const v2 = vx[i] * vx[i] + vy[i] * vy[i] + vz[i] * vz[i];
      if (v2 > MAX_VELOCITY * MAX_VELOCITY) {
        const s = MAX_VELOCITY / Math.sqrt(v2);
        vx[i] *= s; vy[i] *= s; vz[i] *= s;
      }
      x[i] += vx[i];
      y[i] += vy[i];
      z[i] += vz[i];
    }

    // ── Collision enforcement: hard floor at MIN_SEP ─────────────────
    // Any pair closer than MIN_SEP is pushed apart symmetrically.
    // Applied as a position correction (not velocity), same as d3-force
    // forceCollide. This ensures file orbits never visually overlap.
    for (let i = 0; i < n; i++) {
      for (let j = i + 1; j < n; j++) {
        const dx = x[i] - x[j];
        const dy = y[i] - y[j];
        const dz = z[i] - z[j];
        const dist = Math.sqrt(dx * dx + dy * dy + dz * dz);
        if (dist < MIN_SEP && dist > 0.001) {
          const push = (MIN_SEP - dist) / dist * 0.5;
          x[i] += dx * push; y[i] += dy * push; z[i] += dz * push;
          x[j] -= dx * push; y[j] -= dy * push; z[j] -= dz * push;
        }
      }
    }

    alpha = Math.max(0, alpha - ALPHA_DECAY);
    if (alpha === 0) break;
  }

  const out = new Array(n);
  for (let i = 0; i < n; i++) {
    out[i] = { id: projects[i].id, x: x[i], y: y[i], z: z[i] };
  }
  return out;
}

self.onmessage = function (e) {
  const t0 = (typeof performance !== "undefined" && performance.now) ? performance.now() : Date.now();
  const data = e.data || {};
  const projects = Array.isArray(data.projects) ? data.projects : [];
  try {
    const positions = simulate(projects, data.iterations);
    const t1 = (typeof performance !== "undefined" && performance.now) ? performance.now() : Date.now();
    self.postMessage({ ok: true, positions, elapsedMs: t1 - t0, count: projects.length });
  } catch (err) {
    self.postMessage({ ok: false, error: String(err && err.message || err) });
  }
};
