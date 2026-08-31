"use client";

import Link from "next/link";
import { useInspection } from "@/lib/api/useInspection";
import { buttonClasses } from "@/components/ui/Button";
import { DataValue } from "@/components/ui/DataValue";

/**
 * The pinned source rail of the file-centric workspace (UI redesign S2, D244; design spec §3 D-R2).
 *
 * The file is the noun: on every tab of `/f/[file_id]` this rail keeps \"what did I start with\" in
 * view — filename, detected format + confidence, and the key counts — while the main column holds
 * the tab's surface. The facts come from the same inspection the Inspect tab renders (one fetch,
 * react-query-deduped), never a second wire call.
 *
 * The primary CTA is the guided spine (D-R5): it always points at the **next sensible step**, so a
 * first-timer who only clicks the big button walks Inspect → Convert → (the record) with no wizard.
 * The rail collapses to a top summary bar on narrow screens (the layout stacks it above the tabs) —
 * no horizontal page scroll.
 */
function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

function percent(confidence: number): string {
  return `${Math.round(confidence * 100)}%`;
}

export function SourceRail({ fileId }: { fileId: string }) {
  const inspection = useInspection(fileId);

  return (
    <aside
      aria-label="Source file"
      className="w-full shrink-0 rounded-lg border border-line bg-raised p-4 md:w-56"
    >
      {inspection.status === "ready" && inspection.report ? (
        <div className="space-y-3">
          <div className="space-y-1">
            <p className="text-xs font-semibold uppercase tracking-wide text-faint">Source</p>
            <p className="break-all text-sm font-semibold text-strong">
              {inspection.report.file.filename}
            </p>
            <p className="text-sm text-body">
              {inspection.report.format.format_name}{" "}
              <span className="text-faint">
                ({percent(inspection.report.format.confidence)} confidence)
              </span>
            </p>
          </div>
          <dl className="space-y-1 text-sm">
            <div className="flex items-baseline justify-between gap-2">
              <dt className="text-faint">Frames</dt>
              <dd>
                <DataValue>{inspection.report.structure.frame_count}</DataValue>
              </dd>
            </div>
            <div className="flex items-baseline justify-between gap-2">
              <dt className="text-faint">Atoms</dt>
              <dd>
                <DataValue>{inspection.report.structure.atom_count}</DataValue>
              </dd>
            </div>
            <div className="flex items-baseline justify-between gap-2">
              <dt className="text-faint">Size</dt>
              <dd>
                <DataValue>{formatBytes(inspection.report.file.size_bytes)}</DataValue>
              </dd>
            </div>
          </dl>
          <Link
            href={`/f/${fileId}/convert`}
            className={`${buttonClasses("primary", "md")} w-full`}
          >
            Convert →
          </Link>
          <Link href="/" className="block text-sm text-muted underline">
            Upload another file
          </Link>
        </div>
      ) : inspection.status === "loading" ? (
        <p role="status" className="text-sm text-muted">
          Loading source…
        </p>
      ) : (
        <p className="text-sm text-muted">Inspection unavailable.</p>
      )}
    </aside>
  );
}
