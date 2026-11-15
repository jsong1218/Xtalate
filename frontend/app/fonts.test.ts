import { existsSync, readFileSync, statSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

/**
 * Guards the self-hosted type system (redesign D-B6, reversing D-R7): IBM Plex Sans/Mono/Serif are
 * loaded with `next/font/local` from files committed under `app/fonts/`, Latin subset only, two
 * weights each, swapped in on load. `next/font/local` is a build-time loader, so (like
 * `globals.contrast.test.ts`) this reads the *source* of `app/fonts.ts` instead of importing it.
 * The byte budget is the spec §11 ceiling: fonts ≤ 160 kB of woff2.
 */
const root = process.cwd();
const src = readFileSync(resolve(root, "app/fonts.ts"), "utf8");

describe("app/fonts.ts — Plex via next/font/local", () => {
  it("exposes the three families as the CSS variables Tailwind aliases", () => {
    for (const v of ["--font-sans", "--font-mono", "--font-serif"]) {
      expect(src, `variable ${v}`).toContain(`variable: "${v}"`);
    }
  });

  it("references exactly six committed Latin1 woff2 files, within the 160 kB budget", () => {
    const refs = [...src.matchAll(/path:\s*"\.\/fonts\/([^"]+)"/g)].map((m) => m[1]);
    expect(refs).toHaveLength(6);
    let total = 0;
    for (const file of refs) {
      expect(file).toMatch(/^IBMPlex(Sans|Mono|Serif)-(Regular|Medium|SemiBold)-Latin1\.woff2$/);
      const abs = resolve(root, "app/fonts", file);
      expect(existsSync(abs), `${file} is committed`).toBe(true);
      total += statSync(abs).size;
    }
    expect(total).toBeLessThanOrEqual(160 * 1024);
  });

  it("swaps the fonts in rather than blocking text", () => {
    expect(src.match(/display:\s*"swap"/g)).toHaveLength(3);
  });

  it("ships the OFL licence beside the files", () => {
    const licence = readFileSync(resolve(root, "app/fonts/LICENSE-OFL.txt"), "utf8");
    expect(licence).toMatch(/SIL Open Font License/i);
  });
});
