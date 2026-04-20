#!/usr/bin/env node
// Generate hero imagery via Kie AI's Nano Banana 2 model.
//
// Usage:
//   cd website
//   node scripts/generate-images.mjs             # all prompts
//   node scripts/generate-images.mjs home demo   # subset by key
//
// Reads KIE_API_KEY from website/.env (not committed).

import fs from "node:fs/promises";
import fssync from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const projectRoot = path.resolve(__dirname, "..");
const envPath = path.join(projectRoot, ".env");
const outDir = path.join(projectRoot, "src", "assets", "hero");

const BASE = "https://api.kie.ai/api/v1/jobs";
const MODEL = "nano-banana-2";
const ASPECT = "16:9";
const RESOLUTION = "2K";
const FORMAT = "jpg";

// -------- prompt manifest (edit freely) --------
const prompts = {
  home: `Cinematic ultra-wide shot of a cyan quantum lattice dissolving into a
black void, glowing fiber threads, volumetric haze, dramatic rim lighting,
ultra-dark negative space, hyper-detailed editorial tech photography,
#040507 background with #00d4ff accents, shallow depth of field`,

  demo: `Abstract holographic terminal interface floating in darkness,
green cursor trails, thin cyan grid projection, floating metadata glyphs,
long depth of field, editorial tech photography, pure black background,
#00d4ff and #00ff88 accents only`,

  pricing: `Three obsidian monoliths standing on a polished black plane,
glowing cyan crystalline veins running through them, long hard shadows,
high contrast minimalist editorial product photography, pure black background,
#00d4ff accent`,

  documentation: `Architectural blueprint of a quantum circuit rendered in
thin cyan lines on pure black, orthographic schematic, minimalist technical
drawing aesthetic, subtle grain, #040507 background with #00d4ff strokes`,

  blog: `Dark newsroom wall made of glowing cyan text fragments and code
snippets as volumetric light, dramatic chiaroscuro, editorial cinematic
photography, deep black background, #00d4ff highlights`,

  "blog-post": `Macro shot of a single cyan light ray refracting through dark
obsidian glass into a spectrum, extreme negative space, hyper-detailed
editorial photography, pure black background, #00d4ff and faint #d4a017
highlights`,

  "protocol-family": `Three distinct cyan geometric constellations suspended
in deep black space, each a different lattice pattern, connected by faint
glowing threads, cinematic editorial photography, #040507 background, sharp
#00d4ff highlights`,

  "aether-cloud": `A floating obsidian cloud made of interlocking cyan
geometric shards, suspended over a polished black plane, volumetric haze,
cinematic wide shot, editorial tech photography, pure black background,
#00d4ff accents`,

  contact: `A single cyan signal flare rising from pure black space, thin
vertical beam, subtle grid imprint in the void, minimalist editorial,
#040507 background, sharp #00d4ff accent`,
};
// ------------------------------------------------

async function loadApiKey() {
  try {
    const raw = await fs.readFile(envPath, "utf8");
    for (const line of raw.split(/\r?\n/)) {
      const [k, ...rest] = line.split("=");
      if (k?.trim() === "KIE_API_KEY") {
        return rest.join("=").trim();
      }
    }
  } catch {}
  if (process.env.KIE_API_KEY) return process.env.KIE_API_KEY;
  throw new Error(
    "KIE_API_KEY not found in website/.env or process.env. Add it and retry."
  );
}

async function submit(apiKey, prompt) {
  const res = await fetch(`${BASE}/createTask`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${apiKey}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      model: MODEL,
      input: {
        prompt: prompt.replace(/\s+/g, " ").trim(),
        aspect_ratio: ASPECT,
        resolution: RESOLUTION,
        output_format: FORMAT,
      },
    }),
  });
  const json = await res.json();
  if (json.code !== 200 || !json.data?.taskId) {
    throw new Error(
      `createTask failed: ${json.msg ?? res.status} :: ${JSON.stringify(json)}`
    );
  }
  return json.data.taskId;
}

async function poll(apiKey, taskId, { timeoutMs = 5 * 60_000, intervalMs = 5000 } = {}) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const res = await fetch(`${BASE}/recordInfo?taskId=${taskId}`, {
      headers: { Authorization: `Bearer ${apiKey}` },
    });
    const json = await res.json();
    const state = json.data?.state;
    if (state === "success") {
      const resultJson = JSON.parse(json.data.resultJson || "{}");
      const url = resultJson.resultUrls?.[0];
      if (!url) throw new Error(`success but no resultUrls for ${taskId}`);
      return url;
    }
    if (state === "fail") {
      throw new Error(
        `task ${taskId} failed :: ${json.data?.failMsg ?? "unknown"}`
      );
    }
    process.stdout.write(".");
    await new Promise((r) => setTimeout(r, intervalMs));
  }
  throw new Error(`timeout waiting for ${taskId}`);
}

async function download(url, destPath) {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`download failed: ${res.status} ${url}`);
  const buf = Buffer.from(await res.arrayBuffer());
  await fs.writeFile(destPath, buf);
  return buf.length;
}

async function main() {
  const apiKey = await loadApiKey();
  await fs.mkdir(outDir, { recursive: true });

  const keys = process.argv.slice(2);
  const selected = keys.length
    ? keys.filter((k) => k in prompts)
    : Object.keys(prompts);

  if (!selected.length) {
    console.error("No matching prompt keys. Available:", Object.keys(prompts));
    process.exit(1);
  }

  console.log(`[aether] generating ${selected.length} hero(s) via ${MODEL}`);

  const failures = [];
  for (const key of selected) {
    const outPath = path.join(outDir, `${key}.jpg`);
    if (fssync.existsSync(outPath) && !process.env.FORCE) {
      console.log(`[skip] ${key} — already exists (set FORCE=1 to overwrite)`);
      continue;
    }
    try {
      console.log(`\n[gen ] ${key}`);
      const taskId = await submit(apiKey, prompts[key]);
      console.log(`[task] ${taskId}`);
      const url = await poll(apiKey, taskId);
      console.log(`\n[dl  ] ${url}`);
      const bytes = await download(url, outPath);
      console.log(`[ok  ] ${outPath} (${(bytes / 1024).toFixed(0)} KB)`);
    } catch (err) {
      console.error(`[fail] ${key} :: ${err.message}`);
      failures.push(key);
    }
  }

  if (failures.length) {
    console.error(`\n[done] ${failures.length} failed: ${failures.join(", ")}`);
    process.exit(2);
  }
  console.log("\n[done] all heroes generated");
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
