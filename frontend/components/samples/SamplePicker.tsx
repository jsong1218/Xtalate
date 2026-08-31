"use client";

import { useState } from "react";
import type React from "react";

/**
 * "Start with a sample" (UI redesign S4, D246; design spec §6.3) — small per-format fixtures
 * vendored under `frontend/public/samples/` so a first-time visitor can try a conversion with one
 * click instead of hunting for a file. Each is a real, tiny structure; upstream, **the sample goes
 * through the normal upload path** (`onPick` hands the caller a `File`, and the caller runs the
 * same upload it runs for a dropped/selected file). There is **no special-case backend** — this is
 * a client-side `fetch` of a static asset, exactly the rule D-R6 / the slice plan set.
 *
 * `onPick` may be async (the caller can abort a transfer in flight); the buttons disable and show
 * "Loading…" while a fetch + upload is in flight so a double-click cannot start two transfers.
 */
export interface Sample {
  /** The vendored filename under `/samples/`. */
  file: string;
  /** The display title. */
  label: string;
  /** The short format tag shown beside the title. */
  formatTag: string;
  /** The content type handed to the `File` (informational — the backend sniffs the real type). */
  mimeType: string;
}

export const SAMPLES: Sample[] = [
  { file: "water.xyz", label: "A water molecule", formatTag: "XYZ", mimeType: "chemical/x-xyz" },
  { file: "diatomic.extxyz", label: "A celled diatomic", formatTag: "extXYZ", mimeType: "chemical/x-xyz" },
  { file: "nacl.poscar", label: "An NaCl crystal", formatTag: "POSCAR", mimeType: "application/octet-stream" },
];

export function SamplePicker({ onPick }: { onPick: (file: File) => void | Promise<void> }) {
  const [busy, setBusy] = useState<string | null>(null);

  async function pick(sample: Sample) {
    if (busy) return;
    setBusy(sample.file);
    try {
      const res = await fetch(`/samples/${sample.file}`);
      if (!res.ok) return;
      const blob = await res.blob();
      const file = new File([blob], sample.file, { type: sample.mimeType });
      await onPick(file);
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="space-y-1">
      <p className="text-sm font-medium text-strong" id="samples-heading">
        Or start with a sample
      </p>
      <ul
        aria-labelledby="samples-heading"
        className="flex flex-wrap gap-2"
        data-testid="sample-picker"
      >
        {SAMPLES.map((sample) => (
          <li key={sample.file}>
            <button
              type="button"
              disabled={busy !== null}
              onClick={() => pick(sample)}
              data-testid={`sample-${sample.file.replace(/\..*$/, "")}`}
              className="inline-flex items-center gap-2 rounded-md border border-line px-3 py-1.5 text-sm text-body transition-colors hover:bg-raised disabled:opacity-60 disabled:hover:bg-surface"
            >
              {busy === sample.file ? "Loading…" : sample.label}
              <span className="rounded bg-well px-1 py-0.5 font-mono text-xs text-muted">
                {sample.formatTag}
              </span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}