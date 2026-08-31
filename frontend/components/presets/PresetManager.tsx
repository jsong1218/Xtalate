"use client";

import { useState } from "react";
import {
  deletePreset,
  listPresets,
  savePreset,
  type ConversionPreset,
} from "@/lib/prefs/presets";

/**
 * Saved-conversion **presets** (UI redesign S4, D246; design spec §6.4) — a named target-format +
 * loss-posture combo you can re-apply in one click. It lives on the Convert tab beside the target
 * picker: the picker reports its current selection upward, this remembers it under a name, and a
 * saved preset re-converts with {@link lib/prefs/presets} semantics — replaying the target and the
 * posture, and letting a plenty-file's *recovery* decisions still pause and ask (P4: never
 * defaulted). All persistence is localStorage (D-R6).
 */
export function PresetManager({
  currentSelection,
  targetName,
  onConvert,
}: {
  /** The picker's live selection: (target_format_id, mode) — saved when the user names it. */
  currentSelection: { target: string; mode: "permissive" | "strict" } | null;
  /** The display name of the currently selected target (for the save button / saved chips). */
  targetName: string | null;
  /** Begin a conversion for a target + mode — the Convert tab's `handleConvert`. */
  onConvert: (target: string, mode: "permissive" | "strict") => void | Promise<void>;
}) {
  const [presets, setPresets] = useState<ConversionPreset[]>(() => listPresets());
  const [name, setName] = useState("");
  const [saveMsg, setSaveMsg] = useState<string | null>(null);

  function handleSave() {
    const trimmed = name.trim();
    if (!trimmed || !currentSelection) return;
    const { presets: next, saved } = savePreset({
      name: trimmed,
      target_format_id: currentSelection.target,
      target_format_name: targetName ?? currentSelection.target,
      mode: currentSelection.mode,
    });
    setPresets(next);
    setSaveMsg(saved ? `Saved “${trimmed}”.` : "Could not save (storage unavailable).");
    setName("");
    window.setTimeout(() => setSaveMsg(null), 2000);
  }

  function handleDelete(id: string) {
    setPresets(deletePreset(id));
  }

  if (presets.length === 0 && !currentSelection) {
    return null;
  }

  return (
    <section aria-label="Saved presets" className="space-y-3 rounded-lg border border-line p-4">
      <div className="space-y-1">
        <h3 className="text-sm font-semibold text-strong">Saved presets</h3>
        <p className="text-sm text-muted">
          A preset remembers a target format and the loss posture (permissive / strict), stored in
          this browser. If a file still needs a recovery decision, re-converting with a preset pauses
          and asks you the same way a fresh convert does.
        </p>
      </div>

      {/* Save the current selection under a name. */}
      <div className="flex flex-wrap items-center gap-2">
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") handleSave();
          }}
          aria-label="Preset name"
          disabled={!currentSelection}
          placeholder={currentSelection ? `Save current as…` : "Select a target to save a preset"}
          className="rounded-md border border-line px-3 py-1.5 text-sm disabled:opacity-60"
        />
        <button
          type="button"
          disabled={!currentSelection || !name.trim()}
          onClick={handleSave}
          className="rounded-md border border-line px-3 py-1.5 text-sm text-body hover:bg-raised disabled:opacity-60"
        >
          Save preset
        </button>
        {saveMsg ? (
          <span role="status" className="text-sm text-muted">
            {saveMsg}
          </span>
        ) : null}
      </div>

      {presets.length > 0 ? (
        <ul className="space-y-2" data-testid="preset-list">
          {presets.map((preset) => (
            <li
              key={preset.id}
              className="flex flex-wrap items-center gap-2 rounded-md border border-line px-3 py-2"
            >
              <div className="min-w-0 flex-1">
                <span className="font-medium text-strong">{preset.name}</span>
                <span className="ml-2 text-sm text-muted">
                  → {preset.target_format_name}
                  <span className="rounded bg-well px-1 py-0.5 font-mono text-xs text-muted">
                    {preset.mode}
                  </span>
                </span>
              </div>
              <button
                type="button"
                onClick={() => onConvert(preset.target_format_id, preset.mode)}
                className="rounded-md border border-line px-3 py-1 text-sm text-body hover:bg-raised"
              >
                Re-convert
              </button>
              <button
                type="button"
                aria-label={`Delete preset ${preset.name}`}
                onClick={() => handleDelete(preset.id)}
                className="rounded-md border border-line px-2 py-1 text-sm text-faint hover:bg-raised"
              >
                ✕
              </button>
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-sm text-faint">No presets saved yet.</p>
      )}
    </section>
  );
}