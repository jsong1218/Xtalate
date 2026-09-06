"use client";

import { useState } from "react";
import { LossIcon } from "@/components/loss/icons";

/**
 * The repair picker (v1.7 M66-S3, D257) — the pre-conversion step at `/f/[file_id]/convert` where
 * a user **asks for** repairs before committing the conversion.
 *
 * MASTER_SPEC Part 7 §6: "the Recovery UI *is* the repair UI's design system" — the added cards
 * render in the DecisionCard language (border + surface, the ⟳ mark, the machine code in a tinted
 * chip), but a repair card is structurally simpler than a recovery card: a repair has **no
 * choices** — the user already knows the operation and its parameters, so the card is a plain,
 * removable statement of what will be applied, never a radio group. Two load-bearing rules:
 *
 *  1. **The user's order is the applied order.** Cards are appended as added and removed in
 *     place, so the list IS the ordered `repairs` list the submit sends — wrap-then-center and
 *     center-then-wrap stay different requests, exactly as the CLI (D255) and the wire (D256)
 *     preserve order.
 *  2. **The closed set of four is enumerated, never extended.** The operation select offers
 *     exactly `wrap_into_cell`, `center`, `deduplicate`, `species_reorder` (D254); a fifth
 *     operation, a free-form transform, or an add/move/merge-atom control is out of scope for
 *     this version. An operation whose required parameters are incomplete cannot be added (the
 *     engine would reject it — a malformed repair is a request error, never a pause).
 *
 * The picker is a pure client assembly surface: it builds the wire shape
 * `{operation, parameters}` and hands it upward; the engine owns the outcome (an unknown
 * operation, a missing parameter, or a cell-less wrap all surface through the engine's own
 * error/block machinery on submit).
 */

/** One user-requested repair, in the wire shape `RepairSpec` carries (S2, D256). */
export interface RepairDraft {
  operation: string;
  parameters: Record<string, unknown>;
}

/** The closed set of four (D254) the picker offers — with the parameters each consumes. */
const REPAIR_OPERATIONS = [
  {
    operation: "wrap_into_cell",
    label: "Wrap into cell",
    description:
      "Fold every atom into the simulation cell (minimum-image convention). No parameters.",
  },
  {
    operation: "center",
    label: "Center the structure",
    description:
      "Translate a stated reference point of the structure to a stated target. Parameters: reference, target.",
  },
  {
    operation: "deduplicate",
    label: "Deduplicate atoms",
    description:
      "Remove atoms closer than a distance threshold (Å). Parameter: distance_threshold.",
  },
  {
    operation: "species_reorder",
    label: "Regroup atoms by element",
    description:
      "Group atoms by element in first-appearance order (the POSCAR-style ordering). No parameters.",
  },
] as const;

type Operation = (typeof REPAIR_OPERATIONS)[number]["operation"];

const CENTER_REFERENCES = ["centroid", "cell_center"] as const;
const CENTER_TARGETS = ["origin", "cell_center"] as const;

const operationLabel = (operation: string): string =>
  REPAIR_OPERATIONS.find((o) => o.operation === operation)?.label ?? operation;

/** Whether a draft carries every parameter the operation requires (the engine's own rules). */
function isComplete(operation: Operation, parameters: Record<string, unknown>): boolean {
  switch (operation) {
    case "wrap_into_cell":
    case "species_reorder":
      return true;
    case "center":
      return (
        CENTER_REFERENCES.includes(parameters.reference as (typeof CENTER_REFERENCES)[number]) &&
        CENTER_TARGETS.includes(parameters.target as (typeof CENTER_TARGETS)[number])
      );
    case "deduplicate":
      return (
        typeof parameters.distance_threshold === "number" && parameters.distance_threshold > 0
      );
  }
}

export function RepairPicker({
  repairs,
  onChange,
}: {
  /** The ordered list of added repairs — the exact list the submit sends (order is meaning). */
  repairs: RepairDraft[];
  onChange: (repairs: RepairDraft[]) => void;
}) {
  const [operation, setOperation] = useState<Operation>("wrap_into_cell");
  const [parameters, setParameters] = useState<Record<string, unknown>>({});
  const [dirty, setDirty] = useState(false);

  const complete = isComplete(operation, parameters);
  const showIncomplete = dirty && !complete;

  const add = () => {
    if (!complete) return;
    onChange([...repairs, { operation, parameters: { ...parameters } }]);
    // A fresh draft for the next addition — the previous one is now a card.
    setParameters({});
    setDirty(false);
  };

  const remove = (index: number) => {
    onChange(repairs.filter((_, i) => i !== index));
  };

  return (
    <section
      aria-label="Repair the structure before converting"
      data-testid="repair-picker"
      className="space-y-3 rounded-lg border border-line bg-surface p-4"
    >
      <div className="flex flex-wrap items-baseline gap-2">
        <LossIcon kind="repair" />
        <h3 className="text-base font-semibold text-strong">Repair</h3>
        <span className="text-sm text-muted">
          Transform the structure before conversion — applied in the order added, recorded in the
          report with the ⟳ “Modified on request” mark. Optional; nothing repairs unless you add it.
        </span>
      </div>

      {repairs.length > 0 ? (
        <ul className="space-y-2" data-testid="repair-list">
          {repairs.map((repair, index) => (
            <li
              key={`${repair.operation}-${index}`}
              data-testid="repair-card"
              className="flex items-start gap-3 rounded-md border border-line bg-raised px-3 py-2"
            >
              <LossIcon kind="repair" className="mt-0.5" />
              <div className="min-w-0 flex-1">
                <p className="text-sm font-medium text-strong">
                  {operationLabel(repair.operation)}{" "}
                  <code className="rounded bg-cb-repair-bg px-1.5 py-0.5 font-mono text-xs text-cb-repair">
                    {repair.operation}
                  </code>
                </p>
                {Object.keys(repair.parameters).length > 0 ? (
                  <p className="mt-0.5 font-mono text-xs text-muted">
                    {Object.entries(repair.parameters)
                      .map(([name, value]) => `${name} ${String(value)}`)
                      .join(" · ")}
                  </p>
                ) : null}
                <p className="text-xs text-faint">
                  Step {index + 1} of {repairs.length} — applied in the order shown
                </p>
              </div>
              <button
                type="button"
                aria-label={`Remove ${repair.operation} repair`}
                data-testid="repair-remove"
                onClick={() => remove(index)}
                className="rounded border border-line px-2 py-1 text-xs text-body hover:bg-well"
              >
                Remove
              </button>
            </li>
          ))}
        </ul>
      ) : null}

      <div className="space-y-2 rounded-md border border-line-soft bg-raised p-3">
        <div className="flex flex-wrap items-end gap-3">
          <label className="block">
            <span className="block text-xs font-medium text-muted">Operation</span>
            <select
              data-testid="repair-operation-select"
              value={operation}
              onChange={(e) => {
                const next = e.target.value as Operation;
                setOperation(next);
                setParameters({});
                setDirty(false);
              }}
              className="mt-1 rounded border border-line px-2 py-1 text-sm"
            >
              {REPAIR_OPERATIONS.map((o) => (
                <option key={o.operation} value={o.operation}>
                  {o.label}
                </option>
              ))}
            </select>
          </label>

          {operation === "center" ? (
            <>
              <label className="block">
                <span className="block text-xs font-medium text-muted">Reference</span>
                <select
                  data-testid="repair-center-reference"
                  value={String(parameters.reference ?? "")}
                  onChange={(e) =>
                    setParameters({ ...parameters, reference: e.target.value })
                  }
                  className="mt-1 rounded border border-line px-2 py-1 text-sm"
                >
                  <option value="" disabled>
                    Choose…
                  </option>
                  {CENTER_REFERENCES.map((r) => (
                    <option key={r} value={r}>
                      {r}
                    </option>
                  ))}
                </select>
              </label>
              <label className="block">
                <span className="block text-xs font-medium text-muted">Target</span>
                <select
                  data-testid="repair-center-target"
                  value={String(parameters.target ?? "")}
                  onChange={(e) => setParameters({ ...parameters, target: e.target.value })}
                  className="mt-1 rounded border border-line px-2 py-1 text-sm"
                >
                  <option value="" disabled>
                    Choose…
                  </option>
                  {CENTER_TARGETS.map((t) => (
                    <option key={t} value={t}>
                      {t}
                    </option>
                  ))}
                </select>
              </label>
            </>
          ) : null}

          {operation === "deduplicate" ? (
            <label className="block">
              <span className="block text-xs font-medium text-muted">
                distance_threshold (Å)
              </span>
              <input
                data-testid="repair-dedupe-threshold"
                type="number"
                step="any"
                min="0"
                value={
                  typeof parameters.distance_threshold === "number"
                    ? String(parameters.distance_threshold)
                    : ""
                }
                onChange={(e) => {
                  const raw = e.target.value;
                  setParameters({
                    ...parameters,
                    distance_threshold: raw === "" ? undefined : Number(raw),
                  });
                }}
                className="mt-1 w-28 rounded border border-line px-2 py-1 text-sm"
              />
            </label>
          ) : null}

          <button
            type="button"
            data-testid="repair-add"
            disabled={!complete}
            onClick={() => {
              setDirty(true);
              add();
            }}
            className="rounded-md border border-line px-3 py-1.5 text-sm text-body hover:bg-well disabled:cursor-not-allowed disabled:opacity-50"
          >
            Add repair
          </button>
        </div>

        {showIncomplete ? (
          <p role="alert" className="text-xs text-cb-repair">
            Complete the operation&rsquo;s required parameters to add it.
          </p>
        ) : null}

        <p className="text-xs text-faint">
          {REPAIR_OPERATIONS.find((o) => o.operation === operation)?.description}
        </p>
      </div>
    </section>
  );
}