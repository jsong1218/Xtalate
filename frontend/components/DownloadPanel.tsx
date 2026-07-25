"use client";

import { useState } from "react";
import { ErrorEnvelope } from "@/components/ErrorEnvelope";
import { LossIcon } from "@/components/loss/icons";
import { downloadOutput, saveBlob } from "@/lib/api/download";
import type { ConversionRecord, ErrorEnvelope as ErrorEnvelopeModel } from "@/lib/report/types";

/**
 * The output-download panel on a conversion record (MASTER_SPEC Part 6 §4.3, Part 7 §2.5; M29-S2).
 *
 * **Where this sits on the page is part of its meaning.** The record page renders the outcome header
 * and the summary chips *above* this panel, so the loss summary is structurally in view before the
 * file can be taken — a reader cannot reach the button without passing what the conversion cost.
 * That ordering is a layout law, not a style preference (see the page's own docstring).
 *
 * Four states, each named rather than blanked:
 *
 *  - **available** — filename, size, and the byte-lifecycle expiry, so "download later" is an
 *    informed choice rather than a broken link later.
 *  - **requires_ack** — validation *failed*. The failing checks are listed here in the engine's own
 *    words, and the first click deliberately requests **without** acknowledgement so the service's
 *    `409 VALIDATION_ACK_REQUIRED` is rendered verbatim. Only then is the acknowledged retry offered.
 *    The unverified file is reachable — Xtalate does not hide a user's own output — but never by
 *    accident and never without the service having said, in its own words, why.
 *  - **expired** — the bytes passed their lifecycle window. The record and both reports survive
 *    (reports-outlive-bytes), so this reads as *expired*, not *not found*, and says the reports remain.
 *  - **refused** — there is no output because the engine declined to write one. Not an empty
 *    download; an absent one, with the reason living in the refusal panel above.
 */

function Panel({
  tone = "neutral",
  children,
}: {
  tone?: "neutral" | "warning" | "muted";
  children: React.ReactNode;
}) {
  const border =
    tone === "warning"
      ? "border-cb-fail bg-cb-fail-bg"
      : tone === "muted"
        ? "border-slate-200 bg-slate-50"
        : "border-slate-200 bg-white";
  return (
    <section
      aria-labelledby="download-heading"
      data-testid="download-panel"
      className={`space-y-3 rounded-lg border p-4 ${border}`}
    >
      <h2 id="download-heading" className="text-lg font-semibold text-slate-900">
        Download
      </h2>
      {children}
    </section>
  );
}

/** Bytes in the units a person reads, without pretending to more precision than the number has. */
export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} bytes`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/** An ISO timestamp as the local-time string a reader can act on; the raw value stays in `title`. */
export function formatTimestamp(iso: string): string {
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? iso : date.toLocaleString();
}

export function DownloadPanel({ record }: { record: ConversionRecord }) {
  const { download } = record;
  const refused = record.conversion_report.status === "refused";

  const [error, setError] = useState<ErrorEnvelopeModel | null>(null);
  const [busy, setBusy] = useState(false);
  // Set once the service has answered 409: the acknowledged retry is offered only *after* the user
  // has been shown the refusal, never as a pre-ticked shortcut past it.
  const [ackOffered, setAckOffered] = useState(false);

  async function handleDownload(acknowledgeValidationFailure: boolean) {
    setError(null);
    setBusy(true);
    const result = await downloadOutput(record.conversion_id, {
      acknowledgeValidationFailure,
      fallbackFilename: download.filename,
    });
    setBusy(false);
    if (!result.ok) {
      setError(result.error);
      if (result.error.error.code === "VALIDATION_ACK_REQUIRED") setAckOffered(true);
      return;
    }
    saveBlob(result.blob, result.filename);
  }

  if (refused) {
    return (
      <Panel tone="muted">
        <p className="text-sm text-slate-800">
          <strong>There is no file to download.</strong> Xtalate refused this conversion, so no
          output was ever written — the reason is in the refusal above.
        </p>
      </Panel>
    );
  }

  if (!download.available) {
    return (
      <Panel tone="muted">
        <p className="text-sm text-slate-800">
          <strong>The converted file has expired.</strong> Output bytes are kept for a limited window
          and this one&rsquo;s has closed, so{" "}
          <span className="font-mono text-slate-700">{download.filename}</span> is no longer
          retrievable.
        </p>
        <p className="text-sm text-slate-700">
          The record itself has not expired: both reports below are exactly as they were written, so
          what this conversion kept, lost, and assumed is still fully auditable. Converting the
          source again reproduces the file.
        </p>
      </Panel>
    );
  }

  const failedChecks = (record.validation_report?.checks ?? []).filter(
    (check) => check.status === "fail",
  );

  return (
    <Panel tone={download.requires_ack ? "warning" : "neutral"}>
      {download.requires_ack ? (
        <div className="space-y-2">
          <p className="flex items-start gap-2 text-sm text-slate-900">
            <LossIcon kind="fail" />
            <span>
              <strong>Validation failed for this output.</strong> Xtalate re-parsed the file it wrote
              and the result does not match the source within tolerance. The file exists and you can
              take it, but it is <strong>unverified</strong>.
            </span>
          </p>
          {failedChecks.length > 0 ? (
            <ul data-testid="failed-checks" className="space-y-1 pl-6 text-sm text-slate-800">
              {failedChecks.map((check) => (
                <li key={check.check_id}>
                  <span className="font-mono text-xs text-slate-600">{check.check_id}</span>{" "}
                  {/* The engine's own sentence, verbatim — quantitative, never paraphrased. */}
                  {check.message}
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}

      <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-sm">
        <dt className="text-slate-500">File</dt>
        <dd className="font-mono text-slate-800">{download.filename}</dd>
        {download.size_bytes !== null ? (
          <>
            <dt className="text-slate-500">Size</dt>
            <dd className="text-slate-800">{formatBytes(download.size_bytes)}</dd>
          </>
        ) : null}
        {download.expires_at !== null ? (
          <>
            <dt className="text-slate-500">Available until</dt>
            <dd className="text-slate-800" title={download.expires_at}>
              {formatTimestamp(download.expires_at)}
            </dd>
          </>
        ) : null}
      </dl>

      <button
        type="button"
        onClick={() => handleDownload(false)}
        disabled={busy}
        className="rounded-md bg-slate-900 px-3 py-1.5 text-sm font-medium text-white hover:bg-slate-700 disabled:opacity-60"
      >
        {busy ? "Preparing…" : `Download ${download.filename}`}
      </button>

      {error ? <ErrorEnvelope envelope={error} /> : null}

      {ackOffered ? (
        <div className="space-y-2 border-t border-slate-200 pt-3">
          <p className="text-sm text-slate-800">
            To take the file anyway, acknowledge that its fidelity was <em>not</em> verified:
          </p>
          <button
            type="button"
            onClick={() => handleDownload(true)}
            disabled={busy}
            className="rounded-md border border-cb-fail px-3 py-1.5 text-sm font-medium text-slate-900 hover:bg-white disabled:opacity-60"
          >
            Download the unverified output
          </button>
        </div>
      ) : null}
    </Panel>
  );
}
