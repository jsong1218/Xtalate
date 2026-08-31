import { afterEach, describe, expect, it, vi } from "vitest";
import {
  prefixedKey,
  readJson,
  readStorage,
  removeStorage,
  writeJson,
  writeStorage,
} from "./storage";
import { deletePreset, listPresets, savePreset } from "./presets";
import { listRecents, MAX_RECENTS, mergeRecents, pushRecent } from "./recents";

/**
 * The QoL persistence layer (S4, D246) — every read/write routes through the SSR-safe
 * `lib/prefs/storage.ts`, whose "try/catch around every read/write" rule is itself tested here:
 * a blocked `localStorage` (privacy mode, quota, `undefined` in SSR) must never throw, and a call
 * must fall back to its empty/default value. Then the two consumers (`presets.ts`, `recents.ts`)
 * prove the shape guards: a stale or hand-edited value is never trusted.
 */
afterEach(() => {
  vi.unstubAllGlobals();
  window.localStorage.clear();
});

describe("storage.ts (SSR-safe reads/writes)", () => {
  it("reads back what it wrote, namespaced under xtalate-", () => {
    expect(writeStorage(prefixedKey("k"), "v")).toBe(true);
    expect(readStorage(prefixedKey("k"))).toBe("v");
    expect(readStorage("k")).toBeNull(); // unprefixed names are never read
    removeStorage(prefixedKey("k"));
    expect(readStorage(prefixedKey("k"))).toBeNull();
  });

  it("is a no-op (not a throw) when localStorage is unavailable (SSR / disabled)", () => {
    // No storage at all — the same null-`localStorage` a pre-hydration SSR pass or a block would
    // see; every helper must fall back (never throw) and reads report `null`.
    vi.stubGlobal("localStorage", undefined);
    expect(readStorage(prefixedKey("k"))).toBeNull();
    expect(writeStorage(prefixedKey("k"), "v")).toBe(false);
    removeStorage(prefixedKey("k"));
    const isStr = (v: unknown): v is string => typeof v === "string";
    expect(readJson("k", isStr, "fallback")).toBe("fallback");
  });

  it("swallows a throwing localStorage (privacy mode / quota)", () => {
    // A localStorage whose every method throws on touch (blocked storage) — read/write fall back.
    const throwing = {
      getItem: () => {
        throw new Error("denied");
      },
      setItem: () => {
        throw new Error("quota");
      },
      removeItem: () => {
        throw new Error("quota");
      },
      clear: () => {
        throw new Error("quota");
      },
    };
    vi.stubGlobal("localStorage", throwing as unknown as Storage);
    expect(readStorage(prefixedKey("k"))).toBeNull();
    expect(writeStorage(prefixedKey("k"), "v")).toBe(false);
    removeStorage(prefixedKey("k"));
  });

  it("readJson validates shape and falls back on garbage JSON", () => {
    const isStr = (v: unknown): v is string => typeof v === "string";
    writeJson("val", "ok");
    expect(readJson("val", isStr, "fallback")).toBe("ok");
    writeJson("val", 42);
    expect(readJson("val", isStr, "fallback")).toBe("fallback");
    writeStorage(prefixedKey("val"), "{not json");
    expect(readJson("val", isStr, "fallback")).toBe("fallback");
  });
});

describe("presets.ts (named target+posture combos)", () => {
  function sample(target_format_id = "poscar", mode: "permissive" | "strict" = "strict") {
    return {
      name: "Print-ready POSCAR",
      target_format_id,
      target_format_name: "POSCAR",
      mode,
    };
  }

  it("saves and lists a preset", () => {
    const { presets, saved } = savePreset(sample());
    expect(saved).toBe(true);
    expect(listPresets()).toHaveLength(1);
    expect(presets[0].name).toBe("Print-ready POSCAR");
    expect(presets[0].target_format_id).toBe("poscar");
    expect(presets[0].mode).toBe("strict");
  });

  it("re-saving under the same name replaces and keeps the id (update semantics)", () => {
    const first = savePreset(sample());
    const again = savePreset({ ...sample(), mode: "permissive" });
    expect(listPresets()).toHaveLength(1);
    expect(again.presets[0].id).toBe(first.presets[0].id);
    expect(again.presets[0].mode).toBe("permissive");
  });

  it("deletes by id", () => {
    const { presets } = savePreset(sample());
    const next = deletePreset(presets[0].id);
    expect(next).toHaveLength(0);
    expect(listPresets()).toHaveLength(0);
  });

  it("caps the list and never trusts a stale, unshaped value", () => {
    writeStorage("xtalate-presets", JSON.stringify([{ bogus: true }]));
    expect(listPresets()).toEqual([]);
    for (let i = 0; i < MAX_RECENTS + 5; i += 1) savePreset(sample(`f${i}`));
    // MAX_PRESETS cap in presets.ts
    expect(listPresets().length).toBeLessThanOrEqual(12);
  });
});

describe("recents.ts (recent files, localStorage + seeded history)", () => {
  const at = (key: string, name = "a.extxyz", format = "extxyz") =>
    ({
      key,
      href: `/f/${key}`,
      filename: name,
      format_id: format,
      last_seen_at: "2026-08-30T00:00:00.000Z",
    } as const);

  it("pushes a recent to the front and de-duplicates by key", () => {
    pushRecent(at("file-a"));
    pushRecent(at("file-b"));
    pushRecent(at("file-a"));
    const recents = listRecents();
    expect(recents.map((r) => r.key)).toEqual(["file-a", "file-b"]);
    expect(recents[0].last_seen_at >= recents[1].last_seen_at).toBe(true);
  });

  it("caps at MAX_RECENTS", () => {
    for (let i = 0; i < MAX_RECENTS + 5; i += 1) pushRecent(at(`f${i}`));
    expect(listRecents().length).toBe(MAX_RECENTS);
  });

  it("merges persisted with a seeded history list, most-recent-first", () => {
    pushRecent(at("persisted"));
    const seeded = [at("persisted"), at("history")];
    const merged = mergeRecents(listRecents(), seeded);
    expect(merged.map((r) => r.key)).toEqual(["persisted", "history"]);
  });

  it("never trusts an unshaped stored value", () => {
    window.localStorage.setItem("xtalate-recents", JSON.stringify([{ nope: 1 }]));
    expect(listRecents()).toEqual([]);
  });
});