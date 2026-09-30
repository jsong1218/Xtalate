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
 *
 * v2.0 addendums Task 12 (design spec §"Empty state (demo front door)") folded this into the
 * workbench empty state as the "Try a sample" region and restyled the pills as a tile grid. The
 * tiles carry **no emojis** — the design explicitly rejected emoji glyphs here (they render
 * inconsistently across OS/browser font stacks and read as decoration, not information). Each tile
 * pairs a monochrome inline-SVG crystal-outline glyph (decorative, `aria-hidden`, `currentColor` so
 * it themes for free — same pattern as `components/shell/BackLink.tsx`'s arrow) with the plain-text
 * label and the existing monospace format badge, which is the actual accessible identifier.
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

/**
 * A plain monochrome crystal-outline glyph — never an emoji, never a filled/photographic icon.
 * Purely decorative (`aria-hidden`): the accessible identity of each tile is its text label plus
 * the format badge, exactly as before this restyle.
 */
function CrystalGlyph() {
  return (
    <svg
      width="20"
      height="20"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinejoin="round"
      strokeLinecap="round"
      aria-hidden="true"
      className="shrink-0 text-faint"
    >
      <path d="M12 2 L20 9 L17 22 L7 22 L4 9 Z" />
      <path d="M12 2 L12 22 M4 9 L20 9 M7 22 L9.5 9 M17 22 L14.5 9" />
    </svg>
  );
}

export function SamplePicker({ onPick }: { onPick: (file: File) => void | Promise<void> }) {
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function pick(sample: Sample) {
    if (busy) return;
    setBusy(sample.file);
    setError(null);
    try {
      const res = await fetch(`/samples/${sample.file}`);
      if (!res.ok) {
        setError(`Could not load the ${sample.label} sample (HTTP ${res.status}).`);
        return;
      }
      const blob = await res.blob();
      const file = new File([blob], sample.file, { type: sample.mimeType });
      await onPick(file);
    } catch {
      setError(`Could not load the ${sample.label} sample.`);
    } finally {
      setBusy(null);
    }
  }

  return (
    // `aria-label` names this a "region" landmark ("Try a sample") — the exact phrase the design
    // spec (§"Empty state") uses, so the landing's empty state and any test that looks for that
    // region find the same words.
    <section aria-label="Try a sample" className="space-y-2">
      <p className="text-sm font-medium text-strong" id="samples-heading">
        Try a sample
      </p>
      <ul
        aria-labelledby="samples-heading"
        className="grid grid-cols-1 gap-2 sm:grid-cols-3"
        data-testid="sample-picker"
      >
        {SAMPLES.map((sample) => (
          <li key={sample.file}>
            <button
              type="button"
              disabled={busy !== null}
              onClick={() => pick(sample)}
              data-testid={`sample-${sample.file.replace(/\..*$/, "")}`}
              className="flex w-full items-center gap-3 rounded-md border border-line px-3 py-2.5 text-left text-sm text-body transition-colors hover:bg-raised disabled:opacity-60 disabled:hover:bg-surface"
            >
              <CrystalGlyph />
              <span className="min-w-0 flex-1">
                <span className="block truncate">
                  {busy === sample.file ? "Loading…" : sample.label}
                </span>
                <span className="mt-0.5 inline-block rounded bg-well px-1 py-0.5 font-mono text-xs text-muted">
                  {sample.formatTag}
                </span>
              </span>
            </button>
          </li>
        ))}
      </ul>
      {error ? (
        <p role="alert" className="text-xs text-cb-fail">
          {error}
        </p>
      ) : null}
    </section>
  );
}
