"use client";

import { useRef, useState, type DragEvent } from "react";
import { Button } from "@/components/ui/Button";
import { ErrorEnvelope } from "@/components/ErrorEnvelope";
import type { ErrorEnvelope as ErrorEnvelopeModel } from "@/lib/report/types";
import { humanBytes } from "@/lib/format";
import type { UploadProgress } from "@/lib/api/upload";
import type { UploadStatus } from "@/lib/api/useUpload";

export { humanBytes };

/**
 * The upload drop zone (MASTER_SPEC Part 7 §2.2, the M28-S1 front door to a file resource).
 *
 * It takes the instance's limits and the current upload phase as props and calls `onFile` once —
 * the network transfer, the routing on success, and the limits fetch all live in the page. That
 * keeps the load-bearing rule here directly testable: **the instance's size limit is shown inline
 * *before* a failure**, not discovered by hitting it (Part 6 §5 read before you hit it). A failed
 * upload renders through the one {@link ErrorEnvelope} component, so the server's `code` reaches
 * the user verbatim.
 *
 * The one refusal the drop zone owns is the **client-side size pre-check** (v1.1 M39-S4, A2): when
 * the live limit is known (`maxUploadBytes != null`) and the chosen file is already over it, no
 * bytes are uploaded at all — the same `FILE_TOO_LARGE` funnel renders as if the server had
 * answered 413, because the server (behind the proxy) would be an opaque transport failure for
 * exactly this file, never its honest 413 (the D112 proxy-ceiling rule). The server's 413 stays
 * the backstop for the in-limits window and for when the limit is unknown.
 *
 * Progress, when shown, is the real fraction of bytes sent (or an indeterminate bar when the length
 * is not computable) — never a fabricated easing animation (Part 7 §2.4).
 */


export function UploadDropzone({
  maxUploadBytes,
  uploadRetentionHours,
  outputRetentionHours,
  status,
  progress,
  error,
  fileName,
  onFile,
}: {
  /** From `GET /v1/limits`; `null` while unknown (the limit line is then omitted, never faked). */
  maxUploadBytes: number | null;
  /** From `GET /v1/limits`: hours uploaded bytes / converted outputs are kept; `null` = unknown. */
  uploadRetentionHours?: number | null;
  outputRetentionHours?: number | null;
  status: UploadStatus;
  progress: UploadProgress | null;
  error: ErrorEnvelopeModel | null;
  /** Name of the file currently uploading / uploaded, shown beside progress. */
  fileName?: string | null;
  onFile: (file: File) => void;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [clientError, setClientError] = useState<ErrorEnvelopeModel | null>(null);
  const busy = status === "uploading";

  function handleFiles(files: FileList | null) {
    // A fresh selection clears any previous client-side refusal (the funnel never lingers).
    setClientError(null);
    const file = files?.[0];
    if (!file) return;
    // The client-side size gate (v1.1 M39-S4, A2): the live limit is known and this file already
    // exceeds it, so uploading would only die at the Next proxy as an opaque 500/ECONNRESET — never
    // reaching the backend's honest 413 (the D112 proxy-ceiling rule). Refuse here instead, through
    // the same FILE_TOO_LARGE funnel the server 413 renders. `request_id` is "client-side" because
    // no request was made — honest, and distinct from any server reference. When the limit is
    // unknown (`null`), fall through to the server-gated behaviour unchanged.
    if (maxUploadBytes !== null && file.size > maxUploadBytes) {
      setClientError({
        error: {
          code: "FILE_TOO_LARGE",
          message: `Upload exceeds the ${maxUploadBytes}-byte limit.`,
          details: { limit_bytes: maxUploadBytes },
          request_id: "client-side",
          documentation_url: "",
        },
      });
      return;
    }
    onFile(file);
  }

  function onDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    setDragging(false);
    if (!busy) handleFiles(event.dataTransfer.files);
  }

  const pct = progress?.fraction != null ? Math.round(progress.fraction * 100) : null;

  // The error to render: the client-side size refusal (which has precedence — the user acted last)
  // or the server's envelope. Both flow through the one ErrorEnvelope + funnel render path.
  const activeError = clientError ?? (status === "error" ? error : null);

  // Revision 1.4 / D31: the oversize path is a funnel to the free local path, not a dead end —
  // the cap is this instance's posture, not the tool's (Part 7 §2.2).
  const rawSelfHostingUrl = activeError?.error.details?.self_hosting_url;
  const selfHostingUrl = typeof rawSelfHostingUrl === "string" ? rawSelfHostingUrl : null;

  return (
    <div className="space-y-4">
      <div
        onDragOver={(e) => {
          e.preventDefault();
          if (!busy) setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
        className={`rounded-xl border-2 border-dashed p-8 text-center transition-colors ${
          dragging ? "border-line-strong bg-raised" : "border-line"
        } ${busy ? "opacity-70" : ""}`}
      >
        <p className="text-base font-medium text-strong">
          Drop a structure or trajectory file here
        </p>
        <p className="mt-1 text-sm text-muted">
          XYZ, extXYZ, CIF, POSCAR, CONTCAR, XDATCAR, or an ASE trajectory.
        </p>

        <Button
          disabled={busy}
          onClick={() => inputRef.current?.click()}
          className="mt-4"
        >
          {busy ? "Uploading…" : "Choose a file"}
        </Button>
        <input
          ref={inputRef}
          type="file"
          className="sr-only"
          aria-label="Choose a file to convert"
          disabled={busy}
          onChange={(e) => handleFiles(e.target.files)}
        />

        {/* The limit, shown before any attempt — a reader knows the ceiling before hitting it. The
            §2.2 rule is that *both halves* (size and retention) are visible before failure is
            possible, so a reader knows the posture up front rather than discovering it. */}
        {maxUploadBytes !== null ? (
          <p className="mt-4 text-xs text-faint">
            Files up to {humanBytes(maxUploadBytes)} on this instance
            {uploadRetentionHours != null
              ? ` · uploads deleted after ${uploadRetentionHours} hours`
              : ""}
            {outputRetentionHours != null
              ? ` · outputs deleted after ${outputRetentionHours} hours`
              : ""}
            .
          </p>
        ) : null}
      </div>

      {busy ? (
        <div className="space-y-1" aria-live="polite">
          <div className="flex items-center justify-between text-xs text-muted">
            <span className="truncate">{fileName ?? "Uploading…"}</span>
            {pct !== null ? <span className="tabular-nums">{pct}%</span> : null}
          </div>
          <div
            role="progressbar"
            aria-label="Upload progress"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={pct ?? undefined}
            className="h-2 overflow-hidden rounded-full bg-well"
          >
            <div
              className={`h-full bg-inverse transition-[width] ${pct === null ? "w-1/3 animate-pulse" : ""}`}
              style={pct !== null ? { width: `${pct}%` } : undefined}
            />
          </div>
        </div>
      ) : null}

      {activeError ? <ErrorEnvelope envelope={activeError} /> : null}

      {activeError?.error.code === "FILE_TOO_LARGE" ? (
        <p className="text-sm text-body" data-testid="size-funnel">
          This cap is this instance&rsquo;s, not the tool&rsquo;s — run Xtalate locally and there is
          no size limit at all.{" "}
          {selfHostingUrl ? (
            <a
              href={selfHostingUrl}
              className="underline underline-offset-2"
              target="_blank"
              rel="noreferrer"
            >
              Install the CLI or self-host
            </a>
          ) : null}
        </p>
      ) : null}
    </div>
  );
}
