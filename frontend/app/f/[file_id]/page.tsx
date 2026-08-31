"use client";

import { useMemo, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { ErrorEnvelope } from "@/components/ErrorEnvelope";
import { Inventory } from "@/components/Inventory";
import { useInspection } from "@/lib/api/useInspection";
import type { DiscoveryReport } from "@/lib/report/types";

/**
 * The workspace's Inspect tab (UI redesign S2, D244) — today's `/files/[file_id]` discovery panels,
 * moved, not rewritten (design spec §3, D-R1): the file header (detected format + confidence with
 * the \"Not the right format?\" override), the structure summary, and the contents inventory (the
 * ✓/○/✗ leaf-path answer with parse warnings banded above it).
 *
 * The target picker now lives on the Convert tab (where the job + recovery wizard live), and the
 * structure renders on the Structure tab — the rail and the tabs replace the old single-page
 * layout, so each surface owns one job. The guided-spine CTA in the rail advances Inspect → Convert.
 */
function percent(confidence: number): string {
  return `${Math.round(confidence * 100)}%`;
}

function FileHeader({
  report,
  override,
  onOverride,
}: {
  report: DiscoveryReport;
  override: string | undefined;
  onOverride: (formatId: string | undefined) => void;
}) {
  const detected = report.format.format_id;
  // Candidate formats to offer for a manual override — the detected one plus every sniff candidate.
  const candidates = useMemo(() => {
    const ids = new Set<string>([detected]);
    for (const ev of report.format.sniff_evidence ?? []) ids.add(ev.format_id);
    return [...ids];
  }, [detected, report.format.sniff_evidence]);

  return (
    <header className="space-y-2">
      <h1 className="break-all text-2xl font-semibold tracking-tight">{report.file.filename}</h1>
      <p className="text-sm text-muted">
        Detected <strong className="text-strong">{report.format.format_name}</strong>{" "}
        {report.format.overridden ? (
          <span className="text-faint">(format set manually)</span>
        ) : (
          <span className="text-faint">
            ({percent(report.format.confidence)} confidence
            {report.format.ambiguous ? ", ambiguous" : ""})
          </span>
        )}
      </p>
      <p className="font-mono text-xs text-faint">sha256 {report.file.sha256.slice(0, 12)}…</p>
      <details className="text-sm">
        <summary className="cursor-pointer text-muted underline">Not the right format?</summary>
        <label className="mt-2 flex flex-wrap items-center gap-2">
          <span className="text-muted">Read this file as</span>
          <select
            value={override ?? detected}
            onChange={(e) => onOverride(e.target.value === detected ? undefined : e.target.value)}
            className="rounded-md border border-line px-2 py-1"
          >
            {candidates.map((id) => (
              <option key={id} value={id}>
                {id}
              </option>
            ))}
          </select>
        </label>
      </details>
    </header>
  );
}

function StructureSummary({ report }: { report: DiscoveryReport }) {
  const { frame_count, atom_count, species } = report.structure;
  return (
    <section aria-label="Structure summary" className="flex flex-wrap gap-x-8 gap-y-2 text-sm">
      <div>
        <div className="text-faint">Frames</div>
        <div className="font-medium text-strong">{frame_count}</div>
      </div>
      <div>
        <div className="text-faint">Atoms</div>
        <div className="font-medium text-strong">{atom_count}</div>
      </div>
      <div className="min-w-0">
        <div className="text-faint">Species</div>
        <div className="font-medium text-strong">{species.join(", ") || "—"}</div>
      </div>
    </section>
  );
}

export default function InspectTabPage() {
  const params = useParams<{ file_id: string }>();
  const fileId = params.file_id;

  const [override, setOverride] = useState<string | undefined>(undefined);
  const inspection = useInspection(fileId, override);

  return (
    <main className="space-y-8">
      {inspection.status === "loading" ? (
        <p className="text-muted" role="status">
          Inspecting this file…
        </p>
      ) : inspection.status === "error" ? (
        <div className="space-y-4">
          <ErrorEnvelope envelope={inspection.error} />
          <Link href="/" className="text-muted underline">
            Upload a different file
          </Link>
        </div>
      ) : (
        <>
          <FileHeader report={inspection.report} override={override} onOverride={setOverride} />
          <StructureSummary report={inspection.report} />
          <Inventory report={inspection.report} />
        </>
      )}
    </main>
  );
}
