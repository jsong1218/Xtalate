import { readFileSync, readdirSync } from "node:fs";
import { join, relative } from "node:path";

import { describe, expect, it } from "vitest";

/**
 * Bundle route-split regression guard (v2.0 addendums; item 9).
 *
 * The Mol* WebGL runtime is heavy (hundreds of KB) and belongs only in the viewer's
 * dynamically-imported `ssr: false` chunk. `StructureViewer` pulls it via `dynamic(() =>
 * import("./StructureViewerMolstar"), { ssr: false })`, so no route that merely *links* to a viewer
 * (the landing page, the report page, the formats explorer) pays for it. That boundary is easy to
 * break by accident: a shared component adds a plain `import` of `molstarMount`, or someone turns
 * `StructureViewer`'s dynamic import into a static one, and suddenly the WebGL plugin lands in the
 * main bundle again. Nothing rebuilds to catch that on a unit-test run.
 *
 * This test enforces the split at the source level — deterministic, no build, no browser:
 *
 *  1. Only the two heavy geometry modules may *value*-import the Mol* runtime. `import type` is
 *     erased at compile time and pulls nothing into any bundle, so it stays allowed everywhere; the
 *     pure `mol-math/linear-algebra` module (no WebGL — it is what lets `cameraPose` be unit-tested
 *     without a canvas) is likewise exempt.
 *  2. `StructureViewer` must reach `StructureViewerMolstar` through a `dynamic(...)`/`ssr: false`
 *     boundary, never a static import.
 */

// Every module allowed to statically value-import Mol*. The two geometry modules pull the full
// runtime and are the dynamic-only leaves; `StructureLegend` is a deliberate, reviewed exception —
// it reuses Mol*'s element-color helpers so its swatches cannot drift from the rendered pixels, and
// those color/theme tables are small pure-data modules, not the WebGL plugin. `StructureViewerMolstar`
// (the ssr:false leaf) is permitted too but today reaches Mol* only through `molstarMount`, so it is
// not currently a value-importer. Pinning to the actual set is what makes ANY new importer fail
// review — the point of the guard.
const HEAVY_IMPORT_ALLOWLIST = [
  "components/StructureLegend.tsx",
  "lib/geometry/molstarLoader.ts",
  "lib/geometry/molstarMount.ts",
].sort();

// The WebGL plugin/canvas/representation runtime — the genuinely heavy part of Mol*. This must stay
// confined to the dynamic-only geometry modules; it may never appear in a statically-reachable
// component, or a non-viewer route pays for the whole 3D engine.
const WEBGL_RUNTIME_PREFIXES = [
  "molstar/lib/mol-plugin",
  "molstar/lib/mol-plugin-state",
  "molstar/lib/mol-canvas3d",
  "molstar/lib/mol-repr",
];
const WEBGL_RUNTIME_ALLOWLIST = ["lib/geometry/molstarMount.ts"].sort();

// The one Mol* subpath that is pure math (no WebGL), importable anywhere without breaking the split.
const LIGHT_MOLSTAR = "molstar/lib/mol-math/linear-algebra.js";

const ROOTS = ["app", "components", "lib"];

function sourceFiles(dir: string): string[] {
  const out: string[] = [];
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const full = join(dir, entry.name);
    if (entry.isDirectory()) {
      if (entry.name === "node_modules") continue;
      out.push(...sourceFiles(full));
    } else if (
      /\.(ts|tsx)$/.test(entry.name) &&
      !/\.(test|spec)\.(ts|tsx)$/.test(entry.name)
    ) {
      out.push(full);
    }
  }
  return out;
}

/** Value (non-type, non-light) import specifiers from `molstar/...` — the kind that ships bytes. */
function molstarValueImports(source: string): string[] {
  const importRe =
    /^\s*import\s+(type\s+)?(?:[^;]*?\sfrom\s+)?["'](molstar\/[^"']+)["']/gm;
  const out: string[] = [];
  for (const match of source.matchAll(importRe)) {
    const isTypeOnly = Boolean(match[1]);
    const specifier = match[2];
    if (isTypeOnly) continue; // erased at build — pulls nothing into any bundle
    if (specifier === LIGHT_MOLSTAR) continue; // pure math, no WebGL
    out.push(specifier);
  }
  return out;
}

describe("Mol* bundle route-split", () => {
  const files = ROOTS.flatMap((r) => sourceFiles(join(process.cwd(), r)));

  it("finds source files to scan (guards against a broken walk)", () => {
    expect(files.length).toBeGreaterThan(20);
  });

  it("restricts Mol* value-imports to the reviewed allowlist", () => {
    const importers = files
      .filter((f) => molstarValueImports(readFileSync(f, "utf8")).length > 0)
      .map((f) => relative(process.cwd(), f).replace(/\\/g, "/"))
      .sort();
    expect(importers).toEqual(HEAVY_IMPORT_ALLOWLIST);
  });

  it("confines the WebGL plugin/canvas/repr runtime to the dynamic-only geometry module", () => {
    const runtimeImporters = files
      .filter((f) =>
        molstarValueImports(readFileSync(f, "utf8")).some((spec) =>
          WEBGL_RUNTIME_PREFIXES.some((prefix) => spec.startsWith(prefix)),
        ),
      )
      .map((f) => relative(process.cwd(), f).replace(/\\/g, "/"))
      .sort();
    expect(runtimeImporters).toEqual(WEBGL_RUNTIME_ALLOWLIST);
  });

  it("keeps StructureViewer's Mol* view behind a dynamic ssr:false boundary", () => {
    const src = readFileSync(
      join(process.cwd(), "components/StructureViewer.tsx"),
      "utf8",
    );
    // Reached via dynamic import with SSR disabled...
    expect(src).toMatch(
      /dynamic\(\s*\(\)\s*=>\s*import\("\.\/StructureViewerMolstar"\)/,
    );
    expect(src).toMatch(/ssr:\s*false/);
    // ...and never via a static value import of the same module (a `import type` line is fine).
    expect(src).not.toMatch(
      /^\s*import\s+(?!type\b)[^;]*from\s+["']\.\/StructureViewerMolstar["']/m,
    );
  });
});
