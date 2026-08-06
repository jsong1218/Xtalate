import { describe, expect, it } from "vitest";
import { formatGuide, type FormatGuide } from "./guide";
import realCaps from "@/lib/capabilities/__fixtures__/capabilities.json";
import type { CapabilitiesMap } from "@/lib/capabilities/types";

/**
 * The editorial File Format Guide (frontend redesign addendum §4.5). Two guarantees the format
 * pages lean on: every built-in format the running instance declares has a guide entry (so the
 * detail page never falls back for a shipped format), and a format the guide has never heard of —
 * a plugin — resolves to `null` so the page can show its honest "no extended guide" note instead of
 * a fabricated blank. The content quality guard keeps every entry from silently shipping empty.
 */
const builtInIds = Object.keys(realCaps as unknown as CapabilitiesMap);

function assertNonEmpty(guide: FormatGuide): void {
  expect(guide.summary.trim().length).toBeGreaterThan(0);
  expect(guide.context.trim().length).toBeGreaterThan(0);
  const lists: (keyof FormatGuide)[] = [
    "useCases",
    "commonSoftware",
    "stores",
    "advantages",
    "disadvantages",
    "workflows",
    "limitations",
  ];
  for (const key of lists) {
    const value = guide[key] as string[];
    expect(Array.isArray(value)).toBe(true);
    expect(value.length).toBeGreaterThan(0);
    for (const entry of value) expect(entry.trim().length).toBeGreaterThan(0);
  }
}

describe("formatGuide", () => {
  it("returns a complete guide for every built-in format the instance declares", () => {
    // The seven Phase-1 formats each carry editorial prose — no shipped format falls through.
    expect(builtInIds.length).toBeGreaterThanOrEqual(7);
    for (const id of builtInIds) {
      const guide = formatGuide(id);
      expect(guide, `expected a guide entry for built-in format "${id}"`).not.toBeNull();
      assertNonEmpty(guide as FormatGuide);
    }
  });

  it("returns null for a format id with no editorial entry (a plugin)", () => {
    expect(formatGuide("toyfmt")).toBeNull();
    expect(formatGuide("definitely_not_a_format")).toBeNull();
  });

  it("gives XYZ the plain-format prose a newcomer expects", () => {
    const xyz = formatGuide("xyz");
    expect(xyz).not.toBeNull();
    // Enough shape to prove it is the real editorial content, not a stub.
    expect(xyz!.summary.toLowerCase()).toContain("plain");
    expect(xyz!.commonSoftware.length).toBeGreaterThan(1);
    expect(xyz!.stores.some((s) => /position|coordinate/i.test(s))).toBe(true);
  });
});
