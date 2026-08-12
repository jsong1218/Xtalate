"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { Button } from "@/components/ui/Button";
import { LossIcon } from "@/components/loss/icons";
import { Row } from "@/components/report/Row";
import { unlockAudio } from "@/lib/notify/completionSignal";
import type { FormatCapabilities } from "@/lib/capabilities/types";
import { buildPreflightPreview, type PreflightItem, type PreflightPreview } from "@/lib/preflight";
import type { DiscoveryReport } from "@/lib/report/types";

/**
 * Target picker + pre-flight preview (MASTER_SPEC Part 3 §4.3, Part 7 §2; slice M28-S2).
 *
 * A grid of every write-capable format. Selecting one overlays the pre-flight preview — **will carry
 * / will drop / will need recovery** — computed client-side from the Discovery Report against that
 * target's write capabilities (`lib/preflight.ts`). This realizes **P5** in the UI: the user sees the
 * loss *before* committing bytes. It is labelled a prediction, because the binding account is the
 * Conversion Report the conversion itself returns; the preview is the fast, always-true skeleton.
 *
 * The mode toggle defaults to **permissive** (convert and report every loss). **strict** asks the
 * engine to refuse rather than drop anything unacknowledged — surfaced here so the choice is made
 * before submitting, but enforced by the engine, not simulated in the client.
 *
 * **Confirm before record (v1.1 M39-S4, B2).** Clicking "Convert to …" opens an explicit inline
 * confirm step (the recovery-wizard card idiom, not a modal) reusing this target's pre-flight
 * preview as its content, with a final **Convert** and a **Cancel**. `onConvert` — the caller's
 * `POST /v1/convert` — fires only on the final Convert; Cancel or navigating away posts nothing, so
 * an exploratory click never commits a record. The final Convert click also arms the WebAudio
 * context (`unlockAudio`) for the completion signal (C1) — the gesture the browser requires.
 */

const MODES: { value: "permissive" | "strict"; title: string; caption: string }[] = [
  {
    value: "permissive",
    title: "Permissive",
    caption: "Convert, and report every loss in full.",
  },
  {
    value: "strict",
    title: "Strict",
    caption: "Refuse the conversion if anything would be dropped without acknowledgement.",
  },
];

function PreflightColumn({
  title,
  items,
  kind,
  emptyLabel,
}: {
  title: string;
  items: PreflightItem[];
  kind: "preserved" | "removed" | "assumption";
  emptyLabel: string;
}) {
  return (
    <section aria-label={title} className="rounded-md border border-line">
      <h4 className="flex items-center gap-2 border-b border-line px-3 py-2 text-sm font-semibold text-strong">
        <LossIcon kind={kind} />
        {title}
        <span className="text-faint">({items.length})</span>
      </h4>
      {items.length === 0 ? (
        <p className="px-3 py-2 text-sm text-faint">{emptyLabel}</p>
      ) : (
        <ul className="divide-y divide-line-soft">
          {items.map((item) => (
            <Row
              key={item.path ?? item.scenario ?? item.label}
              kind={kind}
              label={item.label}
              detail={item.detail}
            />
          ))}
        </ul>
      )}
    </section>
  );
}

function PreflightOverlay({ preview }: { preview: PreflightPreview }) {
  return (
    <div className="space-y-3" data-testid="preflight-overlay">
      <p className="text-sm text-muted">
        A prediction of converting to <strong>{preview.targetFormatName}</strong>, from this file&rsquo;s
        contents and the format&rsquo;s capabilities. The conversion returns the binding report.
      </p>
      <div className="grid gap-3 md:grid-cols-3">
        <PreflightColumn
          title="Will carry"
          kind="preserved"
          items={preview.carry}
          emptyLabel="Nothing in this file maps to this format."
        />
        <PreflightColumn
          title="Will drop"
          kind="removed"
          items={preview.drop}
          emptyLabel="Nothing would be dropped."
        />
        <PreflightColumn
          title="Will need recovery"
          kind="assumption"
          items={preview.recover}
          emptyLabel="No recovery needed."
        />
      </div>
    </div>
  );
}

export function TargetPicker({
  discovery,
  targets,
  onConvert,
}: {
  discovery: DiscoveryReport;
  /** Write-capable formats (see `writableTargets`). */
  targets: FormatCapabilities[];
  /** Initiate the conversion — the page POSTs `/v1/convert` and routes to the job (M29). */
  onConvert: (targetFormatId: string, mode: "permissive" | "strict") => void;
}) {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [mode, setMode] = useState<"permissive" | "strict">("permissive");
  // The confirm step (B2): the target + mode snapshotted when the user clicked "Convert to …".
  // While non-null, the picker shows the confirm card instead of the mode toggle + submit button;
  // `onConvert` fires only from that card's final Convert.
  const [confirming, setConfirming] = useState<{
    target: FormatCapabilities;
    mode: "permissive" | "strict";
  } | null>(null);

  const selectedTarget = targets.find((t) => t.format_id === selectedId) ?? null;
  const preview = useMemo(
    () => (selectedTarget ? buildPreflightPreview(discovery, selectedTarget) : null),
    [discovery, selectedTarget],
  );

  const confirmingMode = MODES.find((m) => m.value === confirming?.mode) ?? null;
  const confirmConvertRef = useRef<HTMLButtonElement>(null);

  // The confirm step is a new step, not a swap under the pointer: move focus to its primary action
  // (the final Convert) so a keyboard user lands inside it instead of losing focus to <body>.
  useEffect(() => {
    if (confirming) confirmConvertRef.current?.focus();
  }, [confirming]);

  return (
    <div className="space-y-5">
      <div>
        <h3 className="text-sm font-semibold text-strong">Convert to</h3>
        <ul className="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-3 md:grid-cols-4" role="list">
          {targets.map((t) => {
            const active = t.format_id === selectedId;
            return (
              <li key={t.format_id}>
                <button
                  type="button"
                  aria-pressed={active}
                  onClick={() => {
                    // A new selection abandons any pending confirm — nothing was submitted.
                    setConfirming(null);
                    setSelectedId(t.format_id);
                  }}
                  className={`w-full rounded-md border px-3 py-2 text-left text-sm ${
                    active
                      ? "border-line-strong bg-inverse text-inverse-fg"
                      : "border-line text-strong hover:border-line-strong"
                  }`}
                >
                  {t.format_name}
                </button>
              </li>
            );
          })}
        </ul>
      </div>

      {preview && !confirming ? <PreflightOverlay preview={preview} /> : null}

      {/* The B2 confirm step — an inline card in the wizard's own design language (Part 7 §3.2),
          never a modal: the pre-flight preview already computed for this target is the confirm
          content, and the final Convert (which alone POSTs /v1/convert) sits beside a Cancel that
          simply returns to the picker. Nothing is recorded unless the user commits here. */}
      {confirming ? (
        <section
          aria-label={`Confirm conversion to ${confirming.target.format_name}`}
          data-testid="convert-confirm"
          className="space-y-4 rounded-lg border border-line-strong bg-surface p-4"
        >
          <div className="space-y-1">
            <h3 className="text-base font-semibold text-strong">
              Convert to {confirming.target.format_name}?
            </h3>
            <p className="text-sm text-muted">
              This starts the conversion and records it — nothing is submitted until you confirm.
            </p>
            {confirmingMode ? (
              <p className="text-xs text-faint">
                Mode: {confirmingMode.title} — {confirmingMode.caption}
              </p>
            ) : null}
          </div>

          {preview ? <PreflightOverlay preview={preview} /> : null}

          <div className="flex flex-wrap items-center gap-3">
            <Button
              ref={confirmConvertRef}
              onClick={() => {
                // The final Convert is the commit: the page POSTs /v1/convert and routes to the
                // job. It is also the user gesture that arms the WebAudio context for the
                // completion signal (C1) — called synchronously, before any await.
                unlockAudio();
                onConvert(confirming.target.format_id, confirming.mode);
              }}
            >
              Convert
            </Button>
            <button
              type="button"
              onClick={() => setConfirming(null)}
              className="rounded-md border border-line px-3 py-1.5 text-sm text-body hover:bg-raised"
            >
              Cancel
            </button>
          </div>
        </section>
      ) : null}

      {selectedTarget && !confirming ? (
        <div className="space-y-4 border-t border-line pt-4">
          <fieldset>
            <legend className="text-sm font-semibold text-strong">If information would be lost</legend>
            <div className="mt-2 grid gap-2 sm:grid-cols-2">
              {MODES.map((m) => (
                <label
                  key={m.value}
                  className={`flex cursor-pointer gap-2 rounded-md border px-3 py-2 ${
                    mode === m.value ? "border-line-strong" : "border-line"
                  }`}
                >
                  <input
                    type="radio"
                    name="conversion-mode"
                    value={m.value}
                    checked={mode === m.value}
                    onChange={() => setMode(m.value)}
                    className="mt-0.5"
                  />
                  <span>
                    <span className="block text-sm font-medium text-strong">{m.title}</span>
                    <span className="block text-sm text-muted">{m.caption}</span>
                  </span>
                </label>
              ))}
            </div>
          </fieldset>

          <Button onClick={() => setConfirming({ target: selectedTarget, mode })}>
            Convert to {selectedTarget.format_name}
          </Button>
        </div>
      ) : null}
    </div>
  );
}
