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

  it("pins the 11–24 px type scale", () => {
    const sizes = config.theme?.extend?.fontSize as Record<string, [string, { lineHeight: string }]>;
    expect(Object.keys(sizes)).toEqual(["xs2", "xs", "sm", "base", "md", "lg", "xl"]);
    expect(Object.values(sizes).map(([px]) => px)).toEqual([
      "11px", "12px", "13px", "14px", "16px", "20px", "24px",
    ]);
  });

  it("limits radii to 2/4/6 px plus full for dots", () => {
    const radii = config.theme?.borderRadius as Record<string, string>;
    expect(Object.keys(radii).sort()).toEqual(["DEFAULT", "full", "md", "none", "sm"]);
    expect(radii.sm).toBe("var(--radius-1)");
    expect(radii.DEFAULT).toBe("var(--radius-2)");
    expect(radii.md).toBe("var(--radius-3)");
  });
});
