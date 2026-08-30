"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useMemo, useState } from "react";
import { ErrorEnvelope } from "@/components/ErrorEnvelope";
import { Inventory } from "@/components/Inventory";
import { StructureTab } from "@/components/StructureTab";
import { BackLink } from "@/components/shell/BackLink";
import { TargetPicker } from "@/components/TargetPicker";
import { useFileGeometry } from "@/lib/geometry/useGeometry";
import { apiClient } from "@/lib/api/client";
import { capabilitiesQuery } from "@/lib/api/queries";
import { toErrorEnvelope, useInspection } from "@/lib/api/useInspection";
import { armCompletionSignal } from "@/lib/notify/completionSignal";
import { useQuery } from "@tanstack/react-query";
import { writableTargets, type CapabilitiesMap } from "@/lib/capabilities/types";
import type { DiscoveryReport, ErrorEnvelope as ErrorEnvelopeModel } from "@/lib/report/types";

/**
 * The inspection results page (MASTER_SPEC Part 3 §6, Part 7 §2; slice M28-S2).
 *
 * Four regions over the Discovery Report the service returns: a file header (sniff format +
 * confidence, with a "Not the right format?" override that re-inspects), a structure summary, the
 * contents inventory (the ✓/○/✗ leaf-path answer, with any parse warnings banded above it), and the
 * target picker whose pre-flight overlay predicts what each target would carry, drop, or recover.
 *
 * The page is a thin presenter: every load-bearing decision — the presence→loss-kind mapping, the
 * capability intersection — lives in unit-tested modules (`components/Inventory`, `lib/preflight`).
 * Here we only wire data to them and route the Convert action to the conversion job (M29).
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

export default function FilePage() {
  const params = useParams<{ file_id: string }>();
  const router = useRouter();
  const fileId = params.file_id;

  const [override, setOverride] = useState<string | undefined>(undefined);
  const [submitError, setSubmitError] = useState<ErrorEnvelopeModel | null>(null);

  const inspection = useInspection(fileId, override);
  // The file's own geometry (M60-S1): the Structure tab renders it at the default frame
  // (frames=0:1), fed straight from `GET /v1/files/{file_id}/geometry` (D232).
  const fileGeometry = useFileGeometry(fileId);
  const capabilities = useQuery(capabilitiesQuery());
  const targets = useMemo(
    () => (capabilities.data ? writableTargets(capabilities.data as CapabilitiesMap) : []),
    [capabilities.data],
  );

  async function handleConvert(targetFormatId: string, mode: "permissive" | "strict") {
    setSubmitError(null);
    const { data, error } = await apiClient.POST("/v1/convert", {
      body: {
        file_id: fileId,
        target_format_id: targetFormatId,
        // v0.7 has the interactive recovery cards (M31), so the button now submits
        // allow_recovery: true: a conversion that needs a decision **pauses** (awaiting_recovery)
        // and the job page renders the decision cards, rather than refusing outright as v0.6 did
        // (D95, now lifted). Pausing to ask is the explicit-recovery path (P4); nothing is ever
        // defaulted, and an unanswered pause still expires to a refusal. Strict-mode loss likewise
        // refuses — recovery is about missing-required data, a separate axis from loss.
        options: {
          mode,
          acknowledge_loss: false,
          acknowledge_parse_warnings: false,
          allow_recovery: true,
          tolerance_profile: "default",
        },
      },
    });
    if (error || !data) {
      setSubmitError(toErrorEnvelope(error, "CONVERT_SUBMIT_FAILED", "Could not start the conversion."));
      return;
    }
    // Arm this job's completion signal (v1.1 M39-S4, C1): only a job the user just launched may
    // chime when it finishes, so a later refresh of — or a shared link to — the finished job page
    // stays silent. Armed here, on the submit that actually starts the job (after the POST
    // succeeded), and consumed by `useCompletionSignal` on the job's first terminal transition.
    armCompletionSignal(data.job_id);
    // `file_id` rides along in the query so the job — and, after it, the conversion record — can
    // offer "convert again with different choices". Neither the job envelope nor the conversion
    // record carries the source file id (Part 6 §3.2, §4.4), so the only honest way back to this
    // page is to hand it forward; without it those pages link to a fresh upload instead of
    // fabricating an id that would 404.
    router.push(`/convert/${data.job_id}?file_id=${encodeURIComponent(fileId)}`);
  }

  return (
    <main className="space-y-8">
      <BackLink href="/convert" label="Upload" />
      {inspection.status === "loading" ? (
        <p className="text-muted" role="status">
          Inspecting this file…
        </p>
      ) : inspection.status === "error" ? (
        <div className="space-y-4">
          <ErrorEnvelope envelope={inspection.error} />
          <Link href="/convert" className="text-muted underline">
            Upload a different file
          </Link>
        </div>
      ) : (
        <>
          <FileHeader report={inspection.report} override={override} onOverride={setOverride} />
          <StructureSummary report={inspection.report} />
          {/* The Structure tab (M60-S1, Part 7 §6): the file's geometry from the M59 endpoint.
              Additive — the panels above and below are untouched. A file that could not be
              inspected renders no viewer (the page's error branch, above). */}
          <StructureTab
            geometryState={fileGeometry}
            label={inspection.report.file.filename}
          />
          <Inventory report={inspection.report} />
          {submitError ? <ErrorEnvelope envelope={submitError} /> : null}
          {targets.length > 0 ? (
            <TargetPicker
              discovery={inspection.report}
              targets={targets}
              onConvert={handleConvert}
            />
          ) : null}
        </>
      )}
    </main>
  );
}
