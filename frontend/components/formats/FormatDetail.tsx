import { CapabilityGlyph } from "./capabilityGlyph";
import { fieldLabel, type FormatRow } from "@/lib/capabilities/matrix";
import type { FormatCapabilities } from "@/lib/capabilities/types";

/**
 * One format's capability declaration in full (MASTER_SPEC Part 7 §2.7; slice M33-S1) — the detail
 * behind a grid row. It renders exactly what `GET /v1/capabilities` sends for this format: its read
 * and/or write declarations field-by-field, the `required_fields` framed as the recovery scenarios
 * they foreshadow ("converting into this format requires…", a preview of the M31 wizard), the
 * `max_frames` limit in plain words, and the `lossy_notes` verbatim. A format that declares only one
 * direction shows only that direction — nothing is fabricated for a direction the registry omitted.
 */

/** The frame limit as a sentence — `null` is unlimited, `1` is a single structure. */
function frameLimit(maxFrames: number | null): string {
  if (maxFrames === null) return "Holds any number of frames (a trajectory).";
  if (maxFrames === 1) return "Holds a single structure (one frame).";
  return `Holds up to ${maxFrames} frames.`;
}

function FieldRows({ caps }: { caps: FormatCapabilities }) {
  const direction = caps.direction;
  const paths = Object.keys(caps.fields).sort((a, b) => fieldLabel(a).localeCompare(fieldLabel(b)));
  return (
    <ul className="divide-y divide-slate-100 text-sm">
      {paths.map((path) => {
        const field = caps.fields[path];
        return (
          <li key={path} className="flex flex-wrap items-baseline gap-x-3 gap-y-1 py-2">
            <span className="min-w-[14rem] font-medium text-slate-900">{fieldLabel(path)}</span>
            <CapabilityGlyph direction={direction} level={field.level} />
            {field.notes ? <span className="text-slate-600">{field.notes}</span> : null}
          </li>
        );
      })}
    </ul>
  );
}

function DirectionSection({ caps, title }: { caps: FormatCapabilities; title: string }) {
  return (
    <section className="space-y-3">
      <h2 className="text-lg font-semibold text-slate-900">{title}</h2>
      <p className="text-sm text-slate-600">{frameLimit(caps.max_frames)}</p>
      <FieldRows caps={caps} />
      {caps.lossy_notes.length > 0 ? (
        <div className="space-y-1 rounded-md border border-slate-200 bg-slate-50 p-3 text-sm text-slate-700">
          <p className="font-medium text-slate-900">On writing this format:</p>
          <ul className="list-disc space-y-1 pl-5">
            {caps.lossy_notes.map((note) => (
              <li key={note}>{note}</li>
            ))}
          </ul>
        </div>
      ) : null}
    </section>
  );
}

/**
 * The `required_fields` block — the same fields the Recovery Workflow will demand a value for when
 * they are absent (P4, the M31 cards). Framing it as "converting into X requires…" here is a
 * deliberate foreshadow: the reader meets the requirement on the format's own page before they ever
 * hit the wizard. Rendered only for the write side, and only when the format declares requirements.
 */
function RequiredFields({ caps }: { caps: FormatCapabilities }) {
  if (caps.required_fields.length === 0) return null;
  return (
    <section
      aria-label={`Fields required to write ${caps.format_name}`}
      className="space-y-2 rounded-md border border-cb-assumption/40 bg-cb-assumption-bg p-4"
    >
      <p className="text-sm font-medium text-slate-900">
        Converting into {caps.format_name} requires these fields — if a source lacks one, the
        conversion pauses to recover it explicitly:
      </p>
      <ul className="list-disc space-y-1 pl-5 text-sm text-slate-700">
        {caps.required_fields.map((path) => (
          <li key={path}>{fieldLabel(path)}</li>
        ))}
      </ul>
    </section>
  );
}

export function FormatDetail({ format }: { format: FormatRow }) {
  return (
    <article className="space-y-8">
      <header className="space-y-1">
        <h1 className="text-2xl font-semibold tracking-tight">{format.format_name}</h1>
        <p className="font-mono text-xs text-slate-400">{format.format_id}</p>
      </header>

      {format.write ? <RequiredFields caps={format.write} /> : null}
      {format.read ? <DirectionSection caps={format.read} title="Reading this format" /> : null}
      {format.write ? <DirectionSection caps={format.write} title="Writing this format" /> : null}
    </article>
  );
}
