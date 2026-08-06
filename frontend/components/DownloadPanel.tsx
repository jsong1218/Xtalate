"use client";

import { useState } from "react";
import { AckGate } from "@/components/AckGate";
import { Button } from "@/components/ui/Button";
import { ErrorEnvelope } from "@/components/ErrorEnvelope";
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
 *  - **requires_ack** — validation *failed*. The plain download button is **replaced** by the
 *    {@link AckGate}: it names the failing checks in the engine's own words, states what taking the
 *    file would mean, and gates the download behind an explicit, unticked acknowledgment that
 *    re-requests with `acknowledge_validation_failure=true`. The unverified file is reachable —
 *    Xtalate does not hide a user's own output — but never by accident and never without the record
 *    having said, in its own words, why (slice M32-S1, retiring the v0.6 click-then-`409` interim).
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
        ? "border-line bg-raised"
        : "border-line bg-surface";
  return (
    <section
      aria-labelledby="download-heading"
      data-testid="download-panel"
      className={`space-y-3 rounded-lg border p-4 ${border}`}
    >
      <h2 id="download-heading" className="text-lg font-semibold text-strong">
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

  // The plain, verified download. A failed-validation output never reaches this path — it is gated
  // by the AckGate below — so this request is always unacknowledged, and legitimately so.
  async function handleDownload() {
    setError(null);
    setBusy(true);
    const result = await downloadOutput(record.conversion_id, {
      acknowledgeValidationFailure: false,
      fallbackFilename: download.filename,
    });
    setBusy(false);
    if (!result.ok) {
      setError(result.error);
      return;
    }
    saveBlob(result.blob, result.filename);
  }

  if (refused) {
    return (
      <Panel tone="muted">
        <p className="text-sm text-strong">
          <strong>There is no file to download.</strong> Xtalate refused this conversion, so no
          output was ever written — the reason is in the refusal above.
        </p>
      </Panel>
    );
  }

  if (!download.available) {
    return (
      <Panel tone="muted">
        <p className="text-sm text-strong">
          <strong>The converted file has expired.</strong> Output bytes are kept for a limited window
          and this one&rsquo;s has closed, so{" "}
          <span className="font-mono text-body">{download.filename}</span> is no longer
          retrievable.
        </p>
        <p className="text-sm text-body">
          The record itself has not expired: both reports below are exactly as they were written, so
          what this conversion kept, lost, and assumed is still fully auditable. Converting the
          source again reproduces the file.
        </p>
      </Panel>
    );
  }

  return (
    <Panel tone={download.requires_ack ? "warning" : "neutral"}>
      <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-sm">
        <dt className="text-faint">File</dt>
        <dd className="font-mono text-strong">{download.filename}</dd>
        {download.size_bytes !== null ? (
          <>
            <dt className="text-faint">Size</dt>
            <dd className="text-strong">{formatBytes(download.size_bytes)}</dd>
          </>
        ) : null}
        {download.expires_at !== null ? (
          <>
            <dt className="text-faint">Available until</dt>
            <dd className="text-strong" title={download.expires_at}>
              {formatTimestamp(download.expires_at)}
            </dd>
          </>
        ) : null}
      </dl>

      {download.requires_ack ? (
        // Validation failed: the plain button is replaced by the gate (slice M32-S1).
        <AckGate record={record} />
      ) : (
        <>
          <Button size="sm" onClick={handleDownload} disabled={busy}>
            {busy ? "Preparing…" : `Download ${download.filename}`}
          </Button>
          {error ? <ErrorEnvelope envelope={error} /> : null}
        </>
      )}
    </Panel>
  );
}
