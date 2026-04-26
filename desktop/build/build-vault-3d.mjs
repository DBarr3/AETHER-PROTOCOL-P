// build-vault-3d.mjs — produces desktop/pages/vault-graph-3d/vendor/v3d-bundle.iife.js
//
// Bundles three.js + 3d-force-graph + three-spritetext into one IIFE so that
// all three packages share THE SAME Three.js instance. Without this, the
// renderer sees two separate Three.js classes (one bundled inside the
// 3d-force-graph UMD, one from the standalone three.min.js) and silently
// drops textures created with the "wrong" Three across the boundary.
//
// Run:  node build/build-vault-3d.mjs
// Or:   npm run build:vault-3d  (after package.json adds the script)
//
// Replaces these three vendor files with one:
//   vendor/three.min.js              (~670 KB)
//   vendor/3d-force-graph.min.js     (~1.3 MB)
//   vendor/three-spritetext.min.js   (~9 KB)
//   →
//   vendor/v3d-bundle.iife.js        (one self-contained IIFE, ~2 MB minified)

import { build } from "esbuild";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const repo = resolve(here, "..");

await build({
  entryPoints: [resolve(repo, "pages/vault-graph-3d/vendor/_bundle-entry.mjs")],
  bundle: true,
  minify: true,
  format: "iife",
  platform: "browser",
  target: ["chrome120"], // Electron 41 ships with Chromium >= 120
  outfile: resolve(repo, "pages/vault-graph-3d/vendor/v3d-bundle.iife.js"),
  resolveExtensions: [".mjs", ".js", ".json"],
  loader: { ".js": "js", ".mjs": "js" },
  legalComments: "none",
  logLevel: "info",
});

console.log("\n[v3d] bundle built -> pages/vault-graph-3d/vendor/v3d-bundle.iife.js");
