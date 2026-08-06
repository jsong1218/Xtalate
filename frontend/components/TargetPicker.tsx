"use client";

import { useMemo, useState } from "react";
import { LossIcon } from "@/components/loss/icons";
import { Row } from "@/components/report/Row";
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

  const selectedTarget = targets.find((t) => t.format_id === selectedId) ?? null;
  const preview = useMemo(
    () => (selectedTarget ? buildPreflightPreview(discovery, selectedTarget) : null),
    [discovery, selectedTarget],
  );

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
                  onClick={() => setSelectedId(t.format_id)}
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

      {preview ? <PreflightOverlay preview={preview} /> : null}

      {selectedTarget ? (
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

          <button
            type="button"
            onClick={() => onConvert(selectedTarget.format_id, mode)}
            className="rounded-md bg-inverse px-4 py-2 font-medium text-inverse-fg"
          >
            Convert to {selectedTarget.format_name}
          </button>
        </div>
      ) : null}
    </div>
  );
}
