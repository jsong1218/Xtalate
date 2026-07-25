"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useMemo, useState } from "react";
import { ErrorEnvelope } from "@/components/ErrorEnvelope";
import { Inventory } from "@/components/Inventory";
import { TargetPicker } from "@/components/TargetPicker";
import { apiClient } from "@/lib/api/client";
import { capabilitiesQuery } from "@/lib/api/queries";
import { toErrorEnvelope, useInspection } from "@/lib/api/useInspection";
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
      <p className="text-sm text-slate-600">
        Detected <strong className="text-slate-900">{report.format.format_name}</strong>{" "}
        {report.format.overridden ? (
          <span className="text-slate-500">(format set manually)</span>
        ) : (
          <span className="text-slate-500">
            ({percent(report.format.confidence)} confidence
            {report.format.ambiguous ? ", ambiguous" : ""})
          </span>
        )}
      </p>
      <p className="font-mono text-xs text-slate-400">sha256 {report.file.sha256.slice(0, 12)}…</p>
      <details className="text-sm">
        <summary className="cursor-pointer text-slate-600 underline">Not the right format?</summary>
        <label className="mt-2 flex flex-wrap items-center gap-2">
          <span className="text-slate-600">Read this file as</span>
          <select
            value={override ?? detected}
            onChange={(e) => onOverride(e.target.value === detected ? undefined : e.target.value)}
            className="rounded-md border border-slate-300 px-2 py-1"
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
        <div className="text-slate-500">Frames</div>
        <div className="font-medium text-slate-900">{frame_count}</div>
      </div>
      <div>
        <div className="text-slate-500">Atoms</div>
        <div className="font-medium text-slate-900">{atom_count}</div>
      </div>
      <div className="min-w-0">
        <div className="text-slate-500">Species</div>
        <div className="font-medium text-slate-900">{species.join(", ") || "—"}</div>
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
        // v0.6 has no interactive recovery yet (M29): submit with defaults so a conversion needing
        // recovery pauses and honestly expires to a refusal, and strict loss refuses — never a
        // silent default. Acknowledgement and recovery choices arrive with the flows that own them.
        options: {
          mode,
          acknowledge_loss: false,
          acknowledge_parse_warnings: false,
          allow_recovery: false,
          tolerance_profile: "default",
        },
      },
    });
    if (error || !data) {
      setSubmitError(toErrorEnvelope(error, "CONVERT_SUBMIT_FAILED", "Could not start the conversion."));
      return;
    }
    router.push(`/convert/${data.job_id}`);
  }

  return (
    <main className="space-y-8">
      {inspection.status === "loading" ? (
        <p className="text-slate-600" role="status">
          Inspecting this file…
        </p>
      ) : inspection.status === "error" ? (
        <div className="space-y-4">
          <ErrorEnvelope envelope={inspection.error} />
          <Link href="/convert" className="text-slate-600 underline">
            Upload a different file
          </Link>
        </div>
      ) : (
        <>
          <FileHeader report={inspection.report} override={override} onOverride={setOverride} />
          <StructureSummary report={inspection.report} />
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
