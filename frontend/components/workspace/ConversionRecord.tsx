"use client";

import Link from "next/link";
import { useState } from "react";
import { CompareTab } from "@/components/CompareTab";
import { DownloadPanel } from "@/components/DownloadPanel";
import { ErrorEnvelope } from "@/components/ErrorEnvelope";
import { Provenance } from "@/components/Provenance";
import { ResolveAndRetry } from "@/components/ResolveAndRetry";
import { StructureTab } from "@/components/StructureTab";
import { useConversionGeometry } from "@/lib/geometry/useGeometry";
import { BackLink } from "@/components/shell/BackLink";
import { ConversionReportPanel } from "@/components/report/ConversionReportPanel";
import { RefusalPanel } from "@/components/report/RefusalPanel";
import { SummaryChips } from "@/components/report/SummaryChips";
import { ValidationReportPanel } from "@/components/report/ValidationReportPanel";
import { conversionQuery, queryKeys, submitRevalidate } from "@/lib/api/queries";
import { toErrorEnvelope } from "@/lib/api/useInspection";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import type {
  ConversionRecord as ConversionRecordModel,
  ErrorEnvelope as ErrorEnvelopeModel,
} from "@/lib/report/types";

/**
 * The conversion record surface (MASTER_SPEC Part 6 §4.4, Part 7 §2.5–§2.6; slice M29-S2, moved
 * into the workspace by UI redesign S2, D244).
 *
 * The consolidated, linkable outcome — the page a collaborator is sent and the page a methods
 * section cites. Everything on it comes from one `GET /v1/conversions/{id}`, which is served from
 * persisted rows alone, so the URL keeps working after the output bytes have expired.
 *
 * **The layout law.** The order is load-bearing, not cosmetic:
 *
 *     outcome header  →  summary chips  →  download panel  →  reports  →  provenance
 *
 * The download control sits *below* the honest quantitative summary of what the conversion kept and
 * lost, so the loss summary is structurally in view before the file can be taken. **The header
 * never celebrates a lossy conversion.** A *refused* conversion renders through the same refusal
 * component the job surface uses, because a refusal is a considered outcome with a record, not an
 * error.
 *
 * The workspace Report tab (`/f/[file_id]/report/[cid]`) renders this in-workspace (the rail +
 * tabs navigate); the legacy `/conversions/[id]` route renders it standalone for a shared link
 * whose source upload is no longer live (the record carries no `file_id`, Part 6 §4.4).
 */

function outcomeHeadline(record: ConversionRecordModel): string {
  const report = record.conversion_report;
  if (report.status === "refused") return "Refused — no file was written";

  const removed = report.removed.length;
  const assumptions = report.assumptions.length;
  const parts: string[] = [];
  if (removed > 0) parts.push(`${removed} field${removed === 1 ? "" : "s"} removed`);
  if (assumptions > 0) {
    parts.push(`${assumptions} assumption${assumptions === 1 ? "" : "s"} recorded`);
  }
  // Nothing lost and nothing assumed is the only case that may be stated plainly as complete.
  if (parts.length === 0) return "Converted — nothing was lost or assumed";
  return `Converted — ${parts.join(", ")}`;
}

/** The validation line beside the headline: what was *verified*, or plainly that nothing was. */
function validationHeadline(record: ConversionRecordModel): string {
  const validation = record.validation_report;
  if (record.conversion_report.status === "refused") {
    return "No validation: nothing was written, so there was nothing to check.";
  }
  if (validation === null) return "Validation has not been recorded for this conversion.";
  const failed = validation.checks.filter((c) => c.status === "fail").length;
  const warned = validation.checks.filter((c) => c.status === "warn").length;
  const skipped = validation.checks.filter((c) => c.status === "skipped").length;
  const detail = [
    failed > 0 ? `${failed} failed` : null,
    warned > 0 ? `${warned} warned` : null,
    skipped > 0 ? `${skipped} skipped` : null,
  ]
    .filter(Boolean)
    .join(", ");
  const total = validation.checks.length;
  return detail
    ? `Validation ${validation.status}: ${total} checks — ${detail}.`
    : `Validation ${validation.status}: all ${total} checks passed.`;
}

export function ConversionRecord({
  conversionId,
  fileId,
  inWorkspace,
}: {
  conversionId: string;
  /** The source file when known; the record itself carries no `file_id` (Part 6 §4.4). */
  fileId: string | null;
  /** In the workspace the rail + tabs navigate; the legacy standalone route renders a back link. */
  inWorkspace: boolean;
}) {
  const queryClient = useQueryClient();

  const [revalidateError, setRevalidateError] = useState<ErrorEnvelopeModel | null>(null);
  const [revalidating, setRevalidating] = useState(false);
  const [profile, setProfile] = useState("default");
  // The viewer tab switch (M62-S1): one visualization surface at a time — the M60 Structure tab
  // (output) is the default, the M62 Compare tab (source + output side by side) is one toggle away.
  const [vizTab, setVizTab] = useState<"structure" | "compare">("structure");

  const query = useQuery(conversionQuery(conversionId));

  // The conversion's **output** geometry (M60-S1): the Structure tab renders the result — the
  // bytes the user downloads — fed straight from `GET /v1/conversions/{id}/geometry?side=output`
  // at the default frame (D232).
  const outputGeometry = useConversionGeometry(conversionId, "output");

  async function handleRevalidate() {
    setRevalidateError(null);
    setRevalidating(true);
    const result = await submitRevalidate(conversionId, profile);
    setRevalidating(false);
    if (!result.ok) {
      setRevalidateError(
        toErrorEnvelope(result.error, "REVALIDATE_FAILED", "Could not re-validate this conversion."),
      );
      return;
    }
    await queryClient.invalidateQueries({ queryKey: queryKeys.conversion(conversionId) });
  }

  if (query.isError) {
    return (
      <main className="space-y-4">
        {!inWorkspace ? <BackLink href="/history" label="History" /> : null}
        <ErrorEnvelope
          envelope={toErrorEnvelope(query.error, "NETWORK_ERROR", "Could not load this conversion.")}
        />
        <Link href="/" className="text-sm text-muted underline">
          Start a new conversion
        </Link>
      </main>
    );
  }

  const record = query.data as ConversionRecordModel | undefined;
  if (!record) {
    return (
      <main>
        <p role="status" className="text-muted">
          Loading this conversion record…
        </p>
      </main>
    );
  }

  const report = record.conversion_report;
  const refused = report.status === "refused";
  // The consistent back affordance for the legacy standalone route: the file this record came from
  // when we know it, otherwise the history list (a shared link carries no file_id).
  const back = fileId
    ? { href: `/f/${fileId}`, label: "Inspection" }
    : { href: "/history", label: "History" };

  return (
    <main className="space-y-6">
      {!inWorkspace ? <BackLink href={back.href} label={back.label} /> : null}
      {/* 1. Outcome header — quantitative, never celebratory. */}
      <header className="space-y-2">
        <h1 className="text-2xl font-semibold tracking-tight text-strong">
          {outcomeHeadline(record)}
        </h1>
        <p className="text-sm text-body">
          <span className="font-medium">{record.source.filename ?? "source"}</span>{" "}
          <span className="text-faint">({record.source.format_id})</span>
          <span aria-hidden="true"> → </span>
          <span className="text-faint">({record.target.format_id})</span>
        </p>
        <p className="text-sm text-body">{validationHeadline(record)}</p>
      </header>

      {/* 2. Summary chips — the loss summary, above the download by law (see the docstring). */}
      {refused ? null : (
        <div data-testid="summary-chips">
          <SummaryChips report={report} />
        </div>
      )}

      {/* A refusal is a considered outcome with a record; it renders here, not as an error. */}
      {refused ? (
        <div className="space-y-4">
          <RefusalPanel report={report} />
          {/* Not a dead-end: re-enter the cards with the same source and target (M32-S2). */}
          <ResolveAndRetry record={record} fileId={fileId} />
        </div>
      ) : null}

      {/* 3. Download — structurally below the summary a reader has just passed. */}
      <DownloadPanel record={record} />

      {/* 4. The two reports: side by side on a wide screen, stacked on a narrow one. */}
      <div data-testid="report-columns" className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <ConversionReportPanel report={report} />
        {record.validation_report ? (
          <ValidationReportPanel report={record.validation_report} />
        ) : (
          <section
            aria-label="Validation report"
            className="space-y-2 rounded-lg border border-line p-4"
          >
            <h2 className="text-lg font-semibold text-strong">Validation report</h2>
            <p className="text-sm text-body">
              {refused
                ? "None — the conversion was refused, so no output was written and nothing was measured."
                : "None recorded for this conversion yet."}
            </p>
          </section>
        )}
      </div>

      {/* The Structure / Compare viewer tabs (M60-S1 + M62-S1, Part 7 §6). A **refused**
          conversion has no output bytes, so no viewer — the RefusalPanel above is the substance. */}
      {refused ? null : (
        <section aria-label="Structure and Compare">
          <div
            role="tablist"
            aria-label="Structure and Compare"
            className="flex flex-wrap gap-1 border-b border-line"
          >
            <button
              type="button"
              role="tab"
              id="tab-structure"
              aria-selected={vizTab === "structure"}
              aria-controls="panel-structure"
              onClick={() => setVizTab("structure")}
              className="rounded-t border border-b-0 border-line px-3 py-1.5 text-sm font-medium text-body aria-selected:bg-well aria-selected:text-strong"
            >
              Structure
            </button>
            <button
              type="button"
              role="tab"
              id="tab-compare"
              aria-selected={vizTab === "compare"}
              aria-controls="panel-compare"
              onClick={() => setVizTab("compare")}
              className="rounded-t border border-b-0 border-line px-3 py-1.5 text-sm font-medium text-body aria-selected:bg-well aria-selected:text-strong"
            >
              Compare
            </button>
          </div>
          {vizTab === "structure" ? (
            <div
              role="tabpanel"
              id="panel-structure"
              aria-labelledby="tab-structure"
              className="pt-3"
            >
              <StructureTab
                geometryState={outputGeometry}
                conversionReport={report}
                trajectorySource={{ kind: "conversion", conversionId, side: "output" }}
              />
            </div>
          ) : (
            <div
              role="tabpanel"
              id="panel-compare"
              aria-labelledby="tab-compare"
              className="pt-3"
            >
              <CompareTab
                conversionId={conversionId}
                conversionReport={report}
                validationReport={record.validation_report ?? undefined}
              />
            </div>
          )}
        </section>
      )}

      {/* Re-validate: appends, never replaces (Part 6 §2), and works after the bytes are gone. */}
      {record.validation_report ? (
        <section aria-label="Re-validate" className="space-y-2">
          <div className="flex flex-wrap items-center gap-2">
            <label className="flex items-center gap-2 text-sm text-body">
              <span>Tolerance profile</span>
              <select
                value={profile}
                onChange={(e) => setProfile(e.target.value)}
                disabled={revalidating}
                className="rounded-md border border-line px-2 py-1 disabled:opacity-60"
              >
                <option value="default">default</option>
                <option value="strict">strict (100× tighter)</option>
                <option value="loose">loose (100× looser)</option>
              </select>
            </label>
            <button
              type="button"
              onClick={handleRevalidate}
              disabled={revalidating}
              className="rounded-md border border-line px-3 py-1.5 text-sm text-body hover:bg-raised disabled:opacity-60"
            >
              {revalidating ? "Re-validating…" : "Re-validate"}
            </button>
          </div>
          <p className="text-xs text-faint">
            Re-validation re-thresholds the measurements already recorded — it does not re-read the
            file, and it <strong>adds</strong> a report rather than replacing this one.
          </p>
          {revalidateError ? <ErrorEnvelope envelope={revalidateError} /> : null}
        </section>
      ) : null}

      {/* 5. Provenance — the citable facts. */}
      <Provenance record={record} />

      <nav className="flex flex-wrap gap-4 text-sm">
        <Link
          href={fileId ? `/f/${fileId}/convert` : "/"}
          className="text-muted underline"
        >
          {fileId ? "Convert again with different choices" : "Convert another file"}
        </Link>
      </nav>
    </main>
  );
}
