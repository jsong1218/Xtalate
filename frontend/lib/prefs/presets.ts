/**
 * Conversion **presets** — a named target-format + loss-posture combo you can re-apply in one click
 * (UI redesign S4, D246; D-R6 — client-side only, no backend table, no identity model).
 *
 * A preset captures exactly what a one-click re-convert can safely replay: **the target format and
 * the loss posture** (permissive vs strict — the `POST /v1/convert` `options` the Convert tab
 * already sends). It does **not** try to capture the interactive recovery decisions — those answer
 * questions about a *specific* file (which frame survives, what lattice) and cannot be replayed
 * blindly across files (P4: nothing is silently defaulted). So re-converting with a preset submits
 * `allow_recovery: true`, and if the new file still needs a decision the job **pauses** again and
 * asks — the same honest path as a fresh convert. A strict preset refuses rather than drop anything
 * unacknowledged, exactly as strict always does.
 *
 * Persistence is localStorage under `xtalate-presets`, written through the SSR-safe
 * {@link lib/prefs/storage.ts}. Every read is validated against the preset shape so a stale or
 * hand-edited value is never trusted; every write is best-effort and returns whether it landed.
 */
import { readJson, writeJson } from "./storage";

/** The convert-posture half of a preset — mirrors the Convert tab's two modes. */
export type PresetMode = "permissive" | "strict";

/** One saved preset: a target format plus a loss posture, named by the user. */
export interface ConversionPreset {
  id: string;
  /** The user-facing name, e.g. "POSCAR for print". */
  name: string;
  target_format_id: string;
  target_format_name: string;
  mode: PresetMode;
  /** ISO timestamp (when the preset was created) — a stable sort key, not user-visible. */
  created_at: string;
}

/** The storage key for the preset list. */
export const PRESETS_STORAGE_KEY = "presets";

/** The newest-first ordering of a server-independent recency list uses `created_at`. */
export const MAX_PRESETS = 12;

function isPresetMode(v: unknown): v is PresetMode {
  return v === "permissive" || v === "strict";
}

function isPreset(v: unknown): v is ConversionPreset {
  if (typeof v !== "object" || v === null) return false;
  const p = v as Record<string, unknown>;
  return (
    typeof p.id === "string" &&
    typeof p.name === "string" &&
    typeof p.target_format_id === "string" &&
    typeof p.target_format_name === "string" &&
    isPresetMode(p.mode) &&
    typeof p.created_at === "string"
  );
}

function isPresetList(v: unknown): v is ConversionPreset[] {
  return Array.isArray(v) && v.every(isPreset);
}

/** Read the saved presets (never throws; falls back to empty). */
export function listPresets(): ConversionPreset[] {
  return readJson<ConversionPreset[]>(PRESETS_STORAGE_KEY, isPresetList, []);
}

function dedupeById(presets: ConversionPreset[]): ConversionPreset[] {
  const seen = new Set<string>();
  const out: ConversionPreset[] = [];
  for (const p of presets) {
    if (seen.has(p.id)) continue;
    seen.add(p.id);
    out.push(p);
  }
  return out;
}

/**
 * Save a preset. An existing preset with the **same name** is replaced (names are the user's handle
 * on a preset — re-saving under a name means "update this one"), keeping its original id so a
 * previous `created_at` sort is stable. Returns the new list (or the unchanged list if storage was
 * blocked). Capped so the list can never grow unboundedly.
 */
export function savePreset(input: {
  name: string;
  target_format_id: string;
  target_format_name: string;
  mode: PresetMode;
}): { presets: ConversionPreset[]; saved: boolean } {
  const existing = listPresets().find((p) => p.name.trim().toLowerCase() === input.name.trim().toLowerCase());
  const now = new Date().toISOString();
  const preset: ConversionPreset = existing
    ? { ...existing, ...input, name: input.name.trim() }
    : {
        id: `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`,
        name: input.name.trim(),
        target_format_id: input.target_format_id,
        target_format_name: input.target_format_name,
        mode: input.mode,
        created_at: now,
      };
  const list = dedupeById([preset, ...listPresets().filter((p) => p.id !== preset.id)]).slice(0, MAX_PRESETS);
  const saved = writeJson(PRESETS_STORAGE_KEY, list);
  return { presets: list, saved };
}

/** Delete a preset by id; returns the resulting list (unchanged on storage failure). */
export function deletePreset(id: string): ConversionPreset[] {
  const list = listPresets().filter((p) => p.id !== id);
  writeJson(PRESETS_STORAGE_KEY, list);
  return list;
}

/** Look up one preset, validated (or `null`). */
export function getPreset(id: string): ConversionPreset | null {
  return listPresets().find((p) => p.id === id) ?? null;
}