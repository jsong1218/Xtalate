#!/usr/bin/env node
// The bundle-size gate (redesign §11). Dependency-free on purpose: reads `.next/app-build-manifest.json`,
// gzips (node:zlib) the deduplicated JS files of the bench-shell entries, sums the committed woff2
// fonts, and compares both to the limits in `size-budget.json`. Run after `next build` (`npm run size`).
// Exit codes: 0 within budget, 1 over budget, 2 no build / bad input.
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, resolve } from "node:path";
import { gzipSync } from "node:zlib";

const args = process.argv.slice(2);
function opt(name, fallback) {
  const i = args.indexOf(name);
  return i >= 0 && args[i + 1] ? args[i + 1] : fallback;
}

const root = resolve(opt("--root", process.cwd()));
const limitsPath = resolve(opt("--limits", join(root, "size-budget.json")));

let limits;
try {
  limits = JSON.parse(readFileSync(limitsPath, "utf8"));
} catch (e) {
  console.error(`size-budget: cannot read limits file ${limitsPath}: ${e.message}`);
  process.exit(2);
}

const manifestPath = join(root, ".next", "app-build-manifest.json");
let manifest;
try {
  manifest = JSON.parse(readFileSync(manifestPath, "utf8"));
} catch {
  console.error(`size-budget: ${manifestPath} not found — run \`next build\` first`);
  process.exit(2);
}

const files = new Set();
for (const entry of limits.shellEntries) {
  const list = manifest.pages?.[entry];
  if (!list) {
    console.error(`size-budget: entry ${entry} missing from app-build-manifest.json`);
    process.exit(2);
  }
  for (const f of list) if (f.endsWith(".js")) files.add(f);
}

const kb = (n) => `${(n / 1024).toFixed(1)} kB`;
let shellTotal = 0;
console.log("bench shell JS (gzip):");
for (const f of [...files].sort()) {
  const gz = gzipSync(readFileSync(join(root, ".next", f))).length;
  shellTotal += gz;
  console.log(`  ${kb(gz).padStart(10)}  ${f}`);
}

let fontTotal = 0;
const fontsDir = join(root, limits.fontsDir);
for (const f of readdirSync(fontsDir)) {
  if (f.endsWith(".woff2")) fontTotal += statSync(join(fontsDir, f)).size;
}

const shellOk = shellTotal <= limits.shellGzipBytes;
const fontsOk = fontTotal <= limits.fontsBytes;
console.log(`shell JS ${kb(shellTotal)} / ${kb(limits.shellGzipBytes)} ${shellOk ? "ok" : "OVER"}`);
console.log(`fonts ${kb(fontTotal)} / ${kb(limits.fontsBytes)} ${fontsOk ? "ok" : "OVER"}`);
process.exit(shellOk && fontsOk ? 0 : 1);
