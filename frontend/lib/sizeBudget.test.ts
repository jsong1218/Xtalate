import { spawnSync } from "node:child_process";
import { mkdirSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { describe, expect, it } from "vitest";

/**
 * The bundle-size gate (redesign §11): the bench shell's JS must stay ≤ 250 kB gzipped excluding
 * dynamic chunks, and the self-hosted fonts ≤ 160 kB. `scripts/size-budget.mjs` reads the committed
 * limits and the `.next` build manifest; this test runs it against a synthetic build so the gate
 * itself is verified without a real `next build`.
 */
const SCRIPT = resolve(process.cwd(), "scripts/size-budget.mjs");

function fakeBuild(opts: { chunkBytes: number; fontBytes: number }) {
  const root = mkdtempSync(join(tmpdir(), "size-budget-"));
  mkdirSync(join(root, ".next/static/chunks"), { recursive: true });
  mkdirSync(join(root, ".next/static/css"), { recursive: true });
  mkdirSync(join(root, "app/fonts"), { recursive: true });
  // Random bytes do not compress, so gzip size ≈ raw size and the assertions stay predictable.
  const noise = (n: number) => Buffer.from(Array.from({ length: n }, () => Math.floor(Math.random() * 256)));
  writeFileSync(join(root, ".next/static/chunks/shared.js"), noise(opts.chunkBytes));
  writeFileSync(join(root, ".next/static/chunks/page.js"), noise(opts.chunkBytes));
  writeFileSync(join(root, ".next/static/css/layout.css"), "body{}");
  writeFileSync(
    join(root, ".next/app-build-manifest.json"),
    JSON.stringify({
      pages: {
        "/layout": ["static/chunks/shared.js", "static/css/layout.css"],
        "/page": ["static/chunks/shared.js", "static/chunks/page.js"],
        "/f/[file_id]/structure/page": ["static/chunks/molstar.js"],
      },
    }),
  );
  writeFileSync(join(root, "app/fonts/A-Latin1.woff2"), noise(opts.fontBytes));
  return root;
}

function run(root: string, limits: object) {
  const limitsPath = join(root, "limits.json");
  writeFileSync(limitsPath, JSON.stringify(limits));
  return spawnSync(process.execPath, [SCRIPT, "--root", root, "--limits", limitsPath], { encoding: "utf8" });
}

const base = { shellEntries: ["/layout", "/page"], fontsDir: "app/fonts" };

describe("scripts/size-budget.mjs", () => {
  it("passes when the deduplicated shell JS and fonts are within budget", () => {
    const root = fakeBuild({ chunkBytes: 1000, fontBytes: 500 });
    const r = run(root, { ...base, shellGzipBytes: 2500, fontsBytes: 600 });
    expect(r.stderr).toBe("");
    expect(r.status).toBe(0);
    expect(r.stdout).toContain("static/chunks/shared.js");
    expect(r.stdout).not.toContain("molstar.js"); // not a shell entry
    expect(r.stdout).not.toContain("layout.css"); // JS only
  });

  it("fails when the shell JS is over budget", () => {
    const root = fakeBuild({ chunkBytes: 1000, fontBytes: 500 });
    const r = run(root, { ...base, shellGzipBytes: 1500, fontsBytes: 600 });
    expect(r.status).toBe(1);
    expect(r.stdout).toMatch(/shell JS .* OVER/);
  });

  it("fails when the fonts are over budget", () => {
    const root = fakeBuild({ chunkBytes: 100, fontBytes: 500 });
    const r = run(root, { ...base, shellGzipBytes: 2500, fontsBytes: 400 });
    expect(r.status).toBe(1);
    expect(r.stdout).toMatch(/fonts .* OVER/);
  });

  it("exits 2 with a clear message when there is no build", () => {
    const root = mkdtempSync(join(tmpdir(), "size-budget-nobuild-"));
    const r = run(root, { ...base, shellGzipBytes: 1, fontsBytes: 1 });
    expect(r.status).toBe(2);
    expect(r.stderr).toContain("app-build-manifest.json");
  });
});
