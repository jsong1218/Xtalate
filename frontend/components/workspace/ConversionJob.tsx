"use client";

import Link from "next/link";
import { useState } from "react";
import { ErrorEnvelope } from "@/components/ErrorEnvelope";
import { JobPhase } from "@/components/JobPhase";
import { BackLink } from "@/components/shell/BackLink";
import { RecoveryStep } from "@/components/recovery/RecoveryStep";
import { ConversionReportPanel } from "@/components/report/ConversionReportPanel";
import { RefusalPanel } from "@/components/report/RefusalPanel";
import { buttonClasses } from "@/components/ui/Button";
import { cancelJob, isTerminalJobState, jobQuery, queryKeys } from "@/lib/api/queries";
import { toErrorEnvelope } from "@/lib/api/useInspection";
import { useCompletionSignal } from "@/lib/notify/useCompletionSignal";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import type {
  AwaitingRecoveryBlock,
  BatchConvertResult,
  ConversionReport,
  ErrorEnvelope as ErrorEnvelopeModel,
  JobChildRef,
} from "@/lib/report/types";

/**
 * The live conversion job surface (MASTER_SPEC Part 6 §3.2, Part 7 §2.4; slice M29-S1, moved into
 * the workspace by UI redesign S2, D244).
 *
 * Everything on this page comes from the long-polled job envelope — there is no client-side model
 * of what "should" be happening. That is the whole design: the envelope carries the truth, the UI
 * renders it, and every state the state machine can reach has an honest card here rather than a
 * spinner that never resolves:
 *
 *  - `queued` / `running` — the phase indicator, with **no invented progress** (`JobPhase`).
 *  - `awaiting_recovery` — the interactive recovery step (`RecoveryStep`, M31): the decision cards,
 *    the visible deadline stated as a refusal, and a first-class decline.
 *  - `completed` — the Conversion Report, or the refusal panel when the engine **declined**.
 *  - `failed` / `expired` / `cancelled` — each a named, honest card.
 *
 * The workspace Convert tab (`/f/[file_id]/convert?job=…`) renders this in-workspace (no back link
 * — the rail + tabs navigate); the legacy `/convert/[job_id]` route renders it standalone for a
 * shared job link that carries no file context (the job envelope carries no `file_id` on the wire,
 * Part 6 §3.2).
 */

/** A job link inside the workspace — or the legacy path when no file context is known. */
export function jobHref(jobId: string, fileId: string | null): string {
  return fileId ? `/f/${fileId}/convert?job=${encodeURIComponent(jobId)}` : `/convert/${jobId}`;
}

/** A conversion record link — the workspace Report tab, or the legacy record path. */
export function recordHref(conversionId: string, fileId: string | null): string {
  return fileId ? `/f/${fileId}/report/${conversionId}` : `/conversions/${conversionId}`;
}

function Card({
  title,
  tone = "neutral",
  children,
}: {
  title: string;
  tone?: "neutral" | "fail";
  children?: React.ReactNode;
}) {
  const border = tone === "fail" ? "border-cb-fail bg-cb-fail-bg" : "border-line bg-surface";
  return (
    <section aria-label={title} className={`space-y-2 rounded-lg border p-4 ${border}`}>
      <h2 className="text-lg font-semibold text-strong">{title}</h2>
      {children}
    </section>
  );
}

function StartOver() {
  return (
    <Link href="/" className="text-sm text-muted underline">
      Convert another file
    </Link>
  );
}

export function ConversionJob({
  jobId,
  fileId,
  back,
}: {
  jobId: string;
  /** The file this job belongs to, when known; the job envelope carries no `file_id` (Part 6 §3.2). */
  fileId: string | null;
  /** Legacy standalone mode renders a back affordance; the workspace relies on the rail + tabs. */
  back?: { href: string; label: string } | null;
}) {
  const queryClient = useQueryClient();

  const [cancelError, setCancelError] = useState<ErrorEnvelopeModel | null>(null);
  const [cancelling, setCancelling] = useState(false);

  const job = useQuery(jobQuery(jobId));

  // The completion signal (v1.1 M39-S4, C1): chime + browser Notification, fired once when this
  // job makes the non-terminal → terminal transition, honoring the persisted mute toggle. It fires
  // only for a job the user launched (armed by the Convert submit and consumed here), so a refresh
  // of — or a shared link to — an already-finished job stays silent.
  useCompletionSignal(job.data?.state, jobId);

  async function handleCancel() {
    setCancelError(null);
    setCancelling(true);
    const result = await cancelJob(jobId);
    setCancelling(false);
    if (!result.ok) {
      setCancelError(
        toErrorEnvelope(result.error, "CANCEL_FAILED", "Could not cancel this job."),
      );
    }
    await queryClient.invalidateQueries({ queryKey: queryKeys.job(jobId) });
  }

  async function handleResumed() {
    await queryClient.invalidateQueries({ queryKey: queryKeys.job(jobId) });
  }

  if (job.isError) {
    return (
      <main className="space-y-4">
        {back ? <BackLink href={back.href} label={back.label} /> : null}
        <ErrorEnvelope
          envelope={toErrorEnvelope(job.error, "NETWORK_ERROR", "Could not reach this job.")}
        />
        <StartOver />
      </main>
    );
  }

  const envelope = job.data;
  if (!envelope) {
    return (
      <main className="space-y-6">
        {back ? <BackLink href={back.href} label={back.label} /> : null}
        <p role="status" className="text-muted">
          Loading this conversion…
        </p>
      </main>
    );
  }

  const state = envelope.state;
  const terminal = isTerminalJobState(state);
  const batch = envelope.kind === "batch_convert";
  const children = (envelope.children ?? []) as JobChildRef[];
  const batchResult = (envelope.result ?? null) as BatchConvertResult | null;
  const result = (envelope.result ?? null) as {
    conversion_id?: string;
    conversion_report?: ConversionReport;
  } | null;
  const report = result?.conversion_report;

  return (
    <main className="space-y-6">
      {back ? <BackLink href={back.href} label={back.label} /> : null}
      <header className="space-y-1">
        <h1 className="text-2xl font-semibold tracking-tight">
          {batch ? "Batch conversion" : "Conversion"}
        </h1>
        <p className="font-mono text-xs text-faint">job {envelope.job_id}</p>
      </header>

      {state === "queued" || state === "running" ? <JobPhase envelope={envelope} /> : null}

      {state === "awaiting_recovery" && envelope.awaiting_recovery ? (
        <RecoveryStep
          block={envelope.awaiting_recovery as unknown as AwaitingRecoveryBlock}
          jobId={envelope.job_id}
          expiresAt={envelope.expires_at}
          onResumed={handleResumed}
          onDecline={handleCancel}
          declining={cancelling}
          declineError={cancelError}
        />
      ) : null}

      {batch && state === "awaiting_recovery" ? (
        <Card title="Waiting on a decision">
          <p className="text-sm text-body">
            This batch made no choice for any file — each decision belongs to the conversion it
            concerns. The batch waits on the conversions below that still need a decision, and
            completes once every one of them is settled.
          </p>
          <ul className="space-y-2">
            {children.map((child, i) => (
              <li
                key={child.job_id}
                className="flex items-center justify-between gap-4 text-sm"
              >
                <span className="text-strong">
                  File {i + 1} · <code className="font-mono text-xs">{child.state}</code>
                </span>
                <Link
                  href={jobHref(child.job_id, child.file_id ?? fileId)}
                  className="text-sm text-accent underline"
                >
                  {child.state === "awaiting_recovery"
                    ? "Answer on this conversion's record"
                    : "View this conversion"}
                </Link>
              </li>
            ))}
          </ul>
        </Card>
      ) : null}

      {batch && state === "completed" && batchResult ? (
        <div className="space-y-4">
          <Card title="Batch result">
            <p className="text-sm text-body">
              This batch converted {batchResult.tallies.converted} of{" "}
              {batchResult.tallies.total} file{batchResult.tallies.total === 1 ? "" : "s"};
              every file&rsquo;s own record keeps its full report, and each of the links below
              resolves to it.
            </p>
            <dl className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
              <div>
                <dt className="text-muted">Total</dt>
                <dd className="font-semibold text-strong">{batchResult.tallies.total}</dd>
              </div>
              <div>
                <dt className="text-muted">Converted</dt>
                <dd className="font-semibold text-strong">{batchResult.tallies.converted}</dd>
              </div>
              <div>
                <dt className="text-muted">Refused</dt>
                <dd className="font-semibold text-strong">{batchResult.tallies.refused}</dd>
              </div>
              <div>
                <dt className="text-muted">Failed</dt>
                <dd className="font-semibold text-strong">{batchResult.tallies.failed}</dd>
              </div>
            </dl>
            <p className="text-sm text-muted">
              Outputs carrying each label: energy ×{batchResult.tallies.label_presence.energy},{" "}
              forces ×{batchResult.tallies.label_presence.forces}, stress ×
              {batchResult.tallies.label_presence.stress}.
            </p>
          </Card>
          <Card title="Per-file conversions">
            <ul className="space-y-2">
              {batchResult.entries.map((entry, i) => (
                <li
                  key={entry.child_job_id}
                  className="flex items-center justify-between gap-4 text-sm"
                >
                  <span className="text-strong">
                    File {i + 1} · <code className="font-mono text-xs">{entry.status}</code>
                  </span>
                  <Link
                    href={jobHref(entry.child_job_id, entry.file_id ?? fileId)}
                    className="text-sm text-accent underline"
                  >
                    View this file&rsquo;s conversion record
                  </Link>
                </li>
              ))}
            </ul>
          </Card>
        </div>
      ) : null}

      {state === "completed" && report ? (
        <div className="space-y-4">
          {report.status === "refused" ? (
            <RefusalPanel report={report} />
          ) : (
            <ConversionReportPanel report={report} />
          )}
          {result?.conversion_id ? (
            <Link
              href={recordHref(result.conversion_id, fileId)}
              className={buttonClasses("primary", "md")}
            >
              View the full record{report.status === "refused" ? "" : " and download the file"}
            </Link>
          ) : null}
        </div>
      ) : null}

      {state === "failed" ? (
        <div className="space-y-3">
          <ErrorEnvelope
            envelope={toErrorEnvelope(envelope.error, "JOB_FAILED", "This conversion failed.")}
          />
          <StartOver />
        </div>
      ) : null}

      {!batch && state === "expired" ? (
        <div className="space-y-3">
          <Card title="Refused — no recovery choice was made" tone="fail">
            <p className="text-sm text-strong">
              This conversion needed a decision before it could be written, and the window for
              supplying one closed. Xtalate <strong>refused the conversion</strong> rather than
              choosing on your behalf: no default was applied, no value was invented, and no output
              file was written.
            </p>
            <p className="text-sm text-body">
              The refusal itself is recorded — the reference below identifies it — so the outcome is
              auditable rather than merely absent. Converting again lets you supply the choices up
              front.
            </p>
          </Card>
          <ErrorEnvelope
            envelope={toErrorEnvelope(
              envelope.error,
              "RECOVERY_REQUIRED",
              "The recovery window expired and the conversion was refused.",
            )}
          />
          <StartOver />
        </div>
      ) : null}

      {batch && state === "cancelled" ? (
        <div className="space-y-3">
          <Card title="Cancelled">
            <p className="text-sm text-strong">
              You cancelled this batch, so <strong>no aggregate result exists for it</strong> — not
              an empty one, none at all. Files it had not yet launched were never started; the
              conversions already launched are ordinary jobs and keep their own records.
            </p>
          </Card>
          <StartOver />
        </div>
      ) : null}

      {!batch && state === "cancelled" ? (
        <div className="space-y-3">
          <Card title="Cancelled">
            <p className="text-sm text-strong">
              You cancelled this conversion, so <strong>no report exists for it</strong> — not an
              empty one, none at all. Nothing was written and nothing was measured.
            </p>
          </Card>
          <StartOver />
        </div>
      ) : null}

      {terminal && state !== "completed" && !["failed", "expired", "cancelled"].includes(state) ? (
        <Card title={`Job ${state}`}>
          <p className="text-sm text-body">
            The service reported this job as <code className="font-mono">{state}</code>.
          </p>
        </Card>
      ) : null}

      {!batch && state === "completed" && !report ? (
        <Card title="Completed">
          <p className="text-sm text-body">This job completed but carried no conversion report.</p>
        </Card>
      ) : null}

      {!terminal && state !== "awaiting_recovery" ? (
        <div className="space-y-2">
          <button
            type="button"
            onClick={handleCancel}
            disabled={cancelling}
            className="rounded-md border border-line px-3 py-1.5 text-sm text-body hover:bg-raised disabled:opacity-60"
          >
            {cancelling ? "Cancelling…" : batch ? "Cancel this batch" : "Cancel this conversion"}
          </button>
          <p className="text-xs text-faint">
            {batch
              ? "Cancelling stops the batch from launching any remaining files; conversions already launched keep their own records."
              : "Cancelling is best-effort: work already underway may finish first, and a conversion that has already produced its result keeps it."}
          </p>
          {cancelError ? <ErrorEnvelope envelope={cancelError} /> : null}
        </div>
      ) : null}
    </main>
  );
}
