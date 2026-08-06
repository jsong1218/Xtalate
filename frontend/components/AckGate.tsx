"use client";

import { useId, useState } from "react";
import { ErrorEnvelope } from "@/components/ErrorEnvelope";
import { LossIcon } from "@/components/loss/icons";
import { downloadOutput, saveBlob } from "@/lib/api/download";
import type { ConversionRecord, ErrorEnvelope as ErrorEnvelopeModel } from "@/lib/report/types";

/**
 * The failed-validation acknowledgment gate (MASTER_SPEC Part 7 §2.5 item 2, Part 5 §2; slice
 * M32-S1). Rendered by {@link import("./DownloadPanel").DownloadPanel} in place of the plain
 * download button whenever `record.download.requires_ack` is set.
 *
 * The service will answer `409 VALIDATION_ACK_REQUIRED` to an unacknowledged download of an output
 * whose validation failed; the v0.6 interim surfaced that wall only *after* a click, by rendering
 * the `409` the normal download button provoked. This gate states the wall **first**: it names the
 * failing checks in the engine's own words (read straight off the record's Validation rows, never
 * re-derived — Part 7 §2 rule 2), says plainly what taking the file would mean, and then — and only
 * then — offers a single, self-describing download that re-requests with
 * `acknowledge_validation_failure=true`.
 *
 * Two rules make it a gate rather than a speed bump:
 *  - **Nothing is preselected.** The acknowledgment checkbox starts unticked and the download stays
 *    disabled until it is ticked, so taking an unverified file is always a deliberate act (P4's
 *    "recorded choice, not a silent default" carried onto the download surface).
 *  - **There is no unacknowledged path.** No ordinary download button, no bare `<a href>` to the
 *    endpoint — the gate cannot be skipped by URL knowledge or a stray click. Acknowledgment gates
 *    *access*; it does not rewrite *history*, so the record goes on recording the failure.
 */
export function AckGate({ record }: { record: ConversionRecord }) {
  const failedChecks = (record.validation_report?.checks ?? []).filter(
    (check) => check.status === "fail",
  );

  const [acknowledged, setAcknowledged] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ErrorEnvelopeModel | null>(null);
  const ackId = useId();

  async function handleDownload() {
    setError(null);
    setBusy(true);
    const result = await downloadOutput(record.conversion_id, {
      acknowledgeValidationFailure: true,
      fallbackFilename: record.download.filename,
    });
    setBusy(false);
    if (!result.ok) {
      setError(result.error);
      return;
    }
    saveBlob(result.blob, result.filename);
  }

  return (
    <div className="space-y-3">
      <p className="flex items-start gap-2 text-sm text-strong">
        <LossIcon kind="fail" />
        <span>
          <strong>Validation failed for this output.</strong> Xtalate re-parsed the file it wrote and
          the result does not match the source within tolerance. The file exists and you may take it,
          but it is <strong>unverified</strong>.
        </span>
      </p>

      {failedChecks.length > 0 ? (
        <ul data-testid="failed-checks" className="space-y-1 pl-6 text-sm text-strong">
          {failedChecks.map((check, i) => (
            // Index-suffixed like the report panels: check_id alone is not a guaranteed-unique key
            // (a trajectory can carry the same catalog check per frame), and a duplicate React key
            // silently drops rows — never lose a reported check to a key collision (the v0.7 review).
            <li key={`${check.check_id}-${i}`}>
              <span className="font-mono text-xs text-muted">{check.check_id}</span>{" "}
              {/* The engine's own sentence, verbatim — quantitative, never paraphrased. */}
              {check.message}
            </li>
          ))}
        </ul>
      ) : null}

      <label htmlFor={ackId} className="flex items-start gap-2 text-sm text-strong">
        <input
          id={ackId}
          type="checkbox"
          checked={acknowledged}
          onChange={(event) => setAcknowledged(event.target.checked)}
          className="mt-1"
        />
        <span>
          I understand this file <strong>failed verification</strong>, and that the record will
          continue to say so.
        </span>
      </label>

      <button
        type="button"
        onClick={handleDownload}
        disabled={!acknowledged || busy}
        className="rounded-md border border-cb-fail px-3 py-1.5 text-sm font-medium text-strong hover:bg-surface disabled:cursor-not-allowed disabled:opacity-60"
      >
        {busy ? "Preparing…" : "Download the unverified file"}
      </button>

      {error ? <ErrorEnvelope envelope={error} /> : null}
    </div>
  );
}
