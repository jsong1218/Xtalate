import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

/**
 * The error-reference link-check (MASTER_SPEC Part 6 §6; slice M34-S1) — the docs analogue of the
 * plain-language mapping-coverage lint.
 *
 * Since v0.5 every error envelope carries `documentation_url = {docs_base_url}#{code.lower()}`, and
 * the UI renders it as a clickable link (`ErrorEnvelope.tsx`). This lint reads the committed
 * `docs/error_codes.json` — exported from the backend's own `ERROR_CODES` registry by
 * `python -m backend.error_codes`, and drift-guarded against the actual raise sites in Python — and
 * fails if any code lacks a `## CODE` section in `docs/errors.md`. The heading text *is* the code, so
 * `rehype-slug` renders it on the `/docs/errors` page at the anchor `code.lower()` — exactly what the
 * envelope points at. A new backend error code therefore fails CI here rather than shipping a
 * `documentation_url` that resolves to nothing.
 */
const docsDir = resolve(process.cwd(), "..", "docs");
const errorCodes = JSON.parse(readFileSync(resolve(docsDir, "error_codes.json"), "utf-8")) as {
  codes: { code: string; http_status: number | null; summary: string }[];
};
const errorsMarkdown = readFileSync(resolve(docsDir, "errors.md"), "utf-8");

/** Does `errors.md` carry a Markdown heading whose text is exactly `code`? */
function hasSection(code: string): boolean {
  return new RegExp(`^#{2,}\\s+${code}\\s*$`, "m").test(errorsMarkdown);
}

describe("error-code reference coverage", () => {
  it("has a sanity floor of codes to check", () => {
    expect(errorCodes.codes.length).toBeGreaterThan(0);
  });

  it.each(errorCodes.codes.map((c) => c.code))(
    "error code %s has a reference section in docs/errors.md",
    (code) => {
      expect(hasSection(code), `add a "## ${code}" section to docs/errors.md`).toBe(true);
    },
  );
});
