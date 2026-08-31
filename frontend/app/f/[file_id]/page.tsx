"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { ErrorEnvelope } from "@/components/ErrorEnvelope";
import { Inventory } from "@/components/Inventory";
import { useInspection } from "@/lib/api/useInspection";
import { pushRecent } from "@/lib/prefs/recents";
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
  // A stable "ready" handle so the render's `.report` access is explicitly narrowed to the state
  // that actually carries it (the status-union ternary narrows the error/loading branches cleanly;
  // this makes the ready branch unambiguous).
  const readyReport = inspection.status === "ready" ? inspection : null;

  // Record this file as a recent (UI redesign S4, D246, D-R6): the recents strip + the command
  // palette read the same localStorage list, so a file you opened seconds ago is one click away.
  // Keyed by fileId so a re-render of the cached inspection never duplicates the entry.
  const pushedFor = useRef<string | null>(null);
  useEffect(() => {
    if (!readyReport || pushedFor.current === fileId) return;
    pushedFor.current = fileId;
    const report = readyReport.report;
    pushRecent({
      key: fileId,
      href: `/f/${fileId}`,
      filename: report.file.filename ?? fileId,
      format_id: report.format.format_id,
      last_seen_at: new Date().toISOString(),
    });
    // Depends on the narrowed `readyReport` (null until a successful inspection lands); never on
    // `inspection.report` directly, which does not exist in the loading/error states.
  }, [readyReport, fileId]);

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
      ) : readyReport ? (
        <>
          <FileHeader report={readyReport.report} override={override} onOverride={setOverride} />
          <StructureSummary report={readyReport.report} />
          <Inventory report={readyReport.report} />
        </>
      ) : null}
    </main>
  );
}
