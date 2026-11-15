import { describe, expect, it } from "vitest";
import config from "./tailwind.config";

/**
 * Pins the type tokens (redesign D-B6, reversing D-R7's system-only mono): each family starts at the
 * `next/font/local` CSS variable set on <html> by `app/fonts.ts`, keeps a system fallback chain, and
 * ends at the generic family so an unloaded font never leaves text unstyled. No URL or file ever
 * appears here — the font files are loaded by next/font, never by a CSS `url()`.
 */
describe("tailwind theme tokens", () => {
  const families = config.theme?.extend?.fontFamily as Record<string, string[]>;

  it.each([
    ["sans", "--font-sans", "sans-serif"],
    ["mono", "--font-mono", "monospace"],
    ["serif", "--font-serif", "serif"],
  ])("%s starts at var(%s) and ends at the generic %s", (key, variable, generic) => {
    const stack = families?.[key];
    expect(stack).toBeDefined();
    expect(stack[0]).toBe(`var(${variable})`);
    expect(stack[stack.length - 1]).toBe(generic);
    expect(stack.join(",")).not.toMatch(/http|url\(|\.woff/);
  });

  it("keeps the system mono fallback behind Plex Mono", () => {
    expect(families.mono).toContain("ui-monospace");
  });
});
