import sharp from "sharp";
import { readdirSync, statSync, mkdirSync, existsSync } from "fs";
import { join, parse } from "path";

const ROOT = new URL("..", import.meta.url).pathname.replace(/^\/([A-Z]:)/, "$1");
const PUBLIC = join(ROOT, "public");
const ASSETS = join(ROOT, "assets");

// Images to convert: [source, destDir, quality]
const targets = [
  // Root-level PNGs → public/
  [join(ROOT, "aethercloudagent.png"), PUBLIC, 80],
  [join(ROOT, "bluecloudagent.png"), PUBLIC, 80],
  [join(ROOT, "diamond agent.png"), PUBLIC, 80],
  [join(ROOT, "purple ghost glass.png"), PUBLIC, 80],
  [join(ROOT, "yellow ghost.png"), PUBLIC, 80],
  [join(ROOT, "Gemini_Generated_Image_a8kou8a8kou8a8ko.png"), PUBLIC, 80],
  [join(ROOT, "mcp buble .jpg"), PUBLIC, 80],
  // Assets PNGs
  [join(ASSETS, "earth_hires.png"), ASSETS, 85],
  [join(ASSETS, "earth_equirectangular.png"), ASSETS, 85],
  [join(ASSETS, "frame_01.png"), ASSETS, 80],
  [join(ASSETS, "frame_02.png"), ASSETS, 80],
  [join(ASSETS, "frame_03.png"), ASSETS, 80],
  [join(ASSETS, "frame_04.png"), ASSETS, 80],
  // Public poster
  [join(PUBLIC, "aether-cloud", "ball_poster_4k.jpg"), join(PUBLIC, "aether-cloud"), 82],
];

async function convert(src, destDir, quality) {
  const { name } = parse(src);
  const dest = join(destDir, `${name}.webp`);
  try {
    const info = await sharp(src)
      .webp({ quality, effort: 6 })
      .toFile(dest);
    const srcSize = statSync(src).size;
    const pct = ((1 - info.size / srcSize) * 100).toFixed(0);
    console.log(`  ${name}.webp  ${(srcSize / 1024).toFixed(0)}KB → ${(info.size / 1024).toFixed(0)}KB  (${pct}% smaller)`);
  } catch (e) {
    console.error(`  SKIP ${src}: ${e.message}`);
  }
}

console.log("Converting images to WebP...\n");
for (const [src, dest, q] of targets) {
  await convert(src, dest, q);
}
console.log("\nDone.");
