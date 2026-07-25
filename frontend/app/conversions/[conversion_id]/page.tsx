"use client";

import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import { useState } from "react";
import { DownloadPanel } from "@/components/DownloadPanel";
import { ErrorEnvelope } from "@/components/ErrorEnvelope";
import { Provenance } from "@/components/Provenance";
import { ConversionReportPanel } from "@/components/report/ConversionReportPanel";
import { RefusalPanel } from "@/components/report/RefusalPanel";
import { SummaryChips } from "@/components/report/SummaryChips";
import { ValidationReportPanel } from "@/components/report/ValidationReportPanel";
import { conversionQuery, queryKeys, submitRevalidate } from "@/lib/api/queries";
import { toErrorEnvelope } from "@/lib/api/useInspection";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import type {
  ConversionRecord,
  ErrorEnvelope as ErrorEnvelopeModel,
} from "@/lib/report/types";

/**
 * The conversion record page (MASTER_SPEC Part 6 §4.4, Part 7 §2.5–§2.6; slice M29-S2).
 *
 * The consolidated, linkable outcome — the page a collaborator is sent and the page a methods
 * section cites. Everything on it comes from one `GET /v1/conversions/{id}`, which is served from
 * persisted rows alone, so the URL keeps working after the output bytes have expired.
 *
 * **The layout law.** The order of this page is load-bearing, not cosmetic:
 *
 *     outcome header  →  summary chips  →  download panel  →  reports  →  provenance
 *
 * The download control sits *below* the honest quantitative summary of what the conversion kept and
 * lost, so the loss summary is structurally in view before the file can be taken. A reader cannot
 * reach the button without passing what it cost. This is the one thing in the slice that is never
 * cut; a "download" button in the header would technically work and would quietly undo the entire
 * point of the product (P1).
 *
 * **The header never celebrates a lossy conversion.** Its wording is derived from the report's own
 * counts, so "Converted — 3 fields removed" is what a lossy run says. There is no success styling
 * that outranks the numbers, and no "Done!" that a reader could take as "nothing happened to my
 * data". A *refused* conversion routes here too and renders through the same refusal component the
 * job page uses, because a refusal is a considered outcome with a record, not an error.
 *
 * Re-validation is offered because a stored conversion can be re-thresholded long after its bytes
 * are gone (Part 6 §2) — and it **appends** a report rather than replacing one, which the page says
 * out loud. Choosing the profile is this slice's declared cut line (v0.7): the request always sends
 * `default`, so no bar is ever changed without the user having asked for it.
 */

function outcomeHeadline(record: ConversionRecord): string {
  const report = record.conversion_report;
  if (report.status === "refused") return "Refused — no file was written";

  const removed = report.removed.length;
  const assumptions = report.assumptions.length;
  const parts: string[] = [];
  if (removed > 0) parts.push(`${removed} field${removed === 1 ? "" : "s"} removed`);
  if (assumptions > 0) {
    parts.push(`${assumptions} assumption${assumptions === 1 ? "" : "s"} recorded`);
  }
  // Nothing lost and nothing assumed is the only case that may be stated plainly as complete —
  // and even then it is a statement about the data, not a congratulation.
  if (parts.length === 0) return "Converted — nothing was lost or assumed";
  return `Converted — ${parts.join(", ")}`;
}

/** The validation line beside the headline: what was *verified*, or plainly that nothing was. */
function validationHeadline(record: ConversionRecord): string {
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

export default function ConversionRecordPage() {
  const params = useParams<{ conversion_id: string }>();
  const conversionId = params.conversion_id;
  // The record does not carry a `file_id` (the service reduces source/target to format + filename),
  // so "convert again" can only return to the file page when the caller that linked here knew it.
  // Absent that, we send the reader to a fresh upload rather than fabricating an id that 404s.
  const fileId = useSearchParams().get("file_id");
  const queryClient = useQueryClient();

  const [revalidateError, setRevalidateError] = useState<ErrorEnvelopeModel | null>(null);
  const [revalidating, setRevalidating] = useState(false);

  const query = useQuery(conversionQuery(conversionId));

  async function handleRevalidate() {
    setRevalidateError(null);
    setRevalidating(true);
    const result = await submitRevalidate(conversionId);
    setRevalidating(false);
    if (!result.ok) {
      setRevalidateError(
        toErrorEnvelope(result.error, "REVALIDATE_FAILED", "Could not re-validate this conversion."),
      );
      return;
    }
    // The re-validation runs as a job; re-read the record so the appended report appears when done.
    await queryClient.invalidateQueries({ queryKey: queryKeys.conversion(conversionId) });
  }

  if (query.isError) {
    return (
      <main className="space-y-4">
        <ErrorEnvelope
          envelope={toErrorEnvelope(query.error, "NETWORK_ERROR", "Could not load this conversion.")}
        />
        <Link href="/" className="text-sm text-slate-600 underline">
          Start a new conversion
        </Link>
      </main>
    );
  }

  const record = query.data as ConversionRecord | undefined;
  if (!record) {
    return (
      <main>
        <p role="status" className="text-slate-600">
          Loading this conversion record…
        </p>
      </main>
    );
  }

  const report = record.conversion_report;
  const refused = report.status === "refused";

  return (
    <main className="space-y-6">
      {/* 1. Outcome header — quantitative, never celebratory. */}
      <header className="space-y-2">
        <h1 className="text-2xl font-semibold tracking-tight text-slate-900">
          {outcomeHeadline(record)}
        </h1>
        <p className="text-sm text-slate-700">
          <span className="font-medium">{record.source.filename ?? "source"}</span>{" "}
          <span className="text-slate-500">({record.source.format_id})</span>
          <span aria-hidden="true"> → </span>
          <span className="text-slate-500">({record.target.format_id})</span>
        </p>
        <p className="text-sm text-slate-700">{validationHeadline(record)}</p>
      </header>

      {/* 2. Summary chips — the loss summary, above the download by law (see the docstring). */}
      {refused ? null : (
        <div data-testid="summary-chips">
          <SummaryChips report={report} />
        </div>
      )}

      {/* A refusal is a considered outcome with a record; it renders here, not as an error. */}
      {refused ? <RefusalPanel report={report} /> : null}

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
            className="space-y-2 rounded-lg border border-slate-200 p-4"
          >
            <h2 className="text-lg font-semibold text-slate-900">Validation report</h2>
            <p className="text-sm text-slate-700">
              {refused
                ? "None — the conversion was refused, so no output was written and nothing was measured."
                : "None recorded for this conversion yet."}
            </p>
          </section>
        )}
      </div>

      {/* Re-validate: appends, never replaces (Part 6 §2), and works after the bytes are gone. */}
      {record.validation_report ? (
        <section aria-label="Re-validate" className="space-y-2">
          <button
            type="button"
            onClick={handleRevalidate}
            disabled={revalidating}
            className="rounded-md border border-slate-300 px-3 py-1.5 text-sm text-slate-700 hover:bg-slate-50 disabled:opacity-60"
          >
            {revalidating ? "Re-validating…" : "Re-validate (default tolerances)"}
          </button>
          <p className="text-xs text-slate-500">
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
          href={fileId ? `/files/${fileId}` : "/"}
          className="text-slate-600 underline"
        >
          {fileId ? "Convert again with different choices" : "Convert another file"}
        </Link>
      </nav>
    </main>
  );
}
