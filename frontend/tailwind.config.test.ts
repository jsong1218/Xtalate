import { describe, expect, it } from "vitest";
import config from "./tailwind.config";

/**
 * Pins the monospace type token (UI redesign S1, D243): values, counts, and identifiers render in
 * `font-mono` across the app, so the family is defined once in tailwind.config.ts and never as a
 * bespoke stack at a call site. The stack is system families only — no web font (the self-host stays
 * lean and the CSP stays simple; D-R7), and the list ends at the generic `monospace` fallback.
 */
describe("tailwind theme tokens", () => {
  it("pins a monospace family with a system fallback and no web font", () => {
    const mono = (config.theme?.extend?.fontFamily as Record<string, string[]>)?.mono;
    expect(mono).toBeDefined();
    expect(mono).toContain("ui-monospace");
    expect(mono.join(",")).toMatch(/monospace$/); // ends at the generic family
    // No web-font import: the stack is system families only.
    expect(mono.join(",")).not.toMatch(/http|url\(|\.woff/);
  });
});
