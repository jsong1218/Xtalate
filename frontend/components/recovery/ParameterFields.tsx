"use client";

import { useId, useState } from "react";
import { uploadFile } from "@/lib/api/upload";
import type { RecoveryOption } from "@/lib/report/types";

/**
 * The parameter widgets for a recovery choice (MASTER_SPEC Part 7 §3.1, deliverable 4; slice M31-S1).
 *
 * Widgets are driven by the option's `parameters_schema`, whose keys are the engine's own parameter
 * names — so a first-party choice gets a purpose-built control and a future plugin scenario gets a
 * generic-but-functional field rather than a blank card (P6). Each field is labelled with the
 * parameter name (the machine token, so a reader can match the recorded `parameters`) and the
 * engine's own description of it, rendered verbatim.
 *
 * The value model is the engine's: `lattice` is a 3×3 number grid, `symbols`/`masses` are lists,
 * scalars are numbers, and `reference` is a `file_id` obtained by uploading a second structure. The
 * card gates on completeness (`lib/recovery/choices.ts`) before any of it is previewed or submitted,
 * so a half-filled grid never leaves the browser.
 */

const NUMBER_PARAMS = new Set(["padding_ang", "temperature_K", "frame_index", "seed"]);
const INTEGER_PARAMS = new Set(["frame_index", "seed"]);

function LatticeGrid({
  value,
  onSet,
}: {
  value: unknown;
  onSet: (grid: number[][]) => void;
}) {
  const grid: number[][] =
    Array.isArray(value) && value.length === 3
      ? (value as number[][])
      : [
          [NaN, NaN, NaN],
          [NaN, NaN, NaN],
          [NaN, NaN, NaN],
        ];
  const update = (r: number, c: number, raw: string) => {
    const next = grid.map((row) => [...row]);
    next[r][c] = raw === "" ? NaN : Number(raw);
    onSet(next);
  };
  return (
    <fieldset className="space-y-1">
      <legend className="text-xs font-medium text-slate-600">lattice — row vectors (Å)</legend>
      <div className="grid grid-cols-3 gap-1" style={{ maxWidth: "18rem" }}>
        {grid.map((row, r) =>
          row.map((cell, c) => (
            <input
              // A fixed 3×3, so index keys are stable and correct here.
              key={`${r}-${c}`}
              data-testid="lattice-cell"
              aria-label={`lattice row ${r + 1} column ${c + 1}`}
              type="number"
              step="any"
              value={Number.isFinite(cell) ? String(cell) : ""}
              onChange={(e) => update(r, c, e.target.value)}
              className="w-full rounded border border-slate-300 px-1.5 py-1 text-sm"
            />
          )),
        )}
      </div>
    </fieldset>
  );
}

function ListField({
  name,
  description,
  numeric,
  value,
  onSet,
}: {
  name: string;
  description: string;
  numeric: boolean;
  value: unknown;
  onSet: (list: (string | number)[]) => void;
}) {
  const id = useId();
  const text = Array.isArray(value) ? value.join(" ") : "";
  return (
    <div className="space-y-1">
      <label htmlFor={id} className="block text-xs font-medium text-slate-600">
        {name} <span className="font-normal text-slate-500">({description})</span>
      </label>
      <input
        id={id}
        type="text"
        defaultValue={text}
        onChange={(e) => {
          const tokens = e.target.value.split(/[\s,]+/).filter(Boolean);
          onSet(numeric ? tokens.map(Number) : tokens);
        }}
        className="w-full rounded border border-slate-300 px-2 py-1 text-sm"
      />
    </div>
  );
}

function UploadReferenceField({
  name,
  description,
  onSet,
}: {
  name: string;
  description: string;
  onSet: (fileId: string | undefined) => void;
}) {
  const id = useId();
  const [status, setStatus] = useState<string | null>(null);
  return (
    <div className="space-y-1">
      <label htmlFor={id} className="block text-xs font-medium text-slate-600">
        {name} <span className="font-normal text-slate-500">({description})</span>
      </label>
      <input
        id={id}
        type="file"
        onChange={async (e) => {
          const file = e.target.files?.[0];
          if (!file) return;
          setStatus("Uploading…");
          onSet(undefined);
          const result = await uploadFile(file);
          if (result.ok) {
            setStatus(`Using ${file.name}`);
            onSet(result.data.file_id);
          } else {
            setStatus(result.error.error.message);
          }
        }}
        className="block w-full text-sm text-slate-700"
      />
      {status ? <p className="text-xs text-slate-500">{status}</p> : null}
    </div>
  );
}

function ScalarField({
  name,
  description,
  value,
  onSet,
}: {
  name: string;
  description: string;
  value: unknown;
  onSet: (value: number | string | undefined) => void;
}) {
  const id = useId();
  const numeric = NUMBER_PARAMS.has(name);
  return (
    <div className="space-y-1">
      <label htmlFor={id} className="block text-xs font-medium text-slate-600">
        {name} <span className="font-normal text-slate-500">({description})</span>
      </label>
      <input
        id={id}
        type={numeric ? "number" : "text"}
        step={numeric ? (INTEGER_PARAMS.has(name) ? "1" : "any") : undefined}
        value={typeof value === "number" || typeof value === "string" ? String(value) : ""}
        onChange={(e) => {
          const raw = e.target.value;
          if (raw === "") return onSet(undefined);
          onSet(numeric ? Number(raw) : raw);
        }}
        className="w-full rounded border border-slate-300 px-2 py-1 text-sm"
      />
    </div>
  );
}

export function ParameterFields({
  option,
  parameters,
  onChange,
}: {
  option: RecoveryOption;
  parameters: Record<string, unknown>;
  onChange: (parameters: Record<string, unknown>) => void;
}) {
  const schema = option.parameters_schema ?? {};
  const set = (name: string, value: unknown) => {
    const next = { ...parameters };
    if (value === undefined) delete next[name];
    else next[name] = value;
    onChange(next);
  };

  return (
    <div className="space-y-2">
      {Object.entries(schema).map(([name, description]) => {
        if (name === "lattice") {
          return (
            <LatticeGrid key={name} value={parameters[name]} onSet={(g) => set(name, g)} />
          );
        }
        if (name === "symbols" || name === "masses") {
          return (
            <ListField
              key={name}
              name={name}
              description={description}
              numeric={name === "masses"}
              value={parameters[name]}
              onSet={(list) => set(name, list)}
            />
          );
        }
        if (name === "reference") {
          return (
            <UploadReferenceField
              key={name}
              name={name}
              description={description}
              onSet={(id) => set(name, id)}
            />
          );
        }
        return (
          <ScalarField
            key={name}
            name={name}
            description={description}
            value={parameters[name]}
            onSet={(v) => set(name, v)}
          />
        );
      })}
    </div>
  );
}
