"use client";

import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
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
 * The live conversion job page (MASTER_SPEC Part 6 §3.2, Part 7 §2.4; slice M29-S1).
 *
 * Everything on this page comes from the long-polled job envelope — there is no client-side model
 * of what "should" be happening. That is the whole design: the envelope carries the truth, the UI
 * renders it, and every state the state machine can reach has an honest card here rather than a
 * spinner that never resolves:
 *
 *  - `queued` / `running` — the phase indicator, with **no invented progress** (`JobPhase`).
 *  - `awaiting_recovery` — the interactive recovery step (`RecoveryStep`, M31): the decision cards,
 *    the visible deadline stated as a refusal, and a first-class decline. It replaces v0.6's
 *    read-only placeholder and still never reads as "a default was picked".
 *  - `completed` — the Conversion Report, or the refusal panel when the engine **declined**. A
 *    refusal is a completed job at HTTP 200, not an error (Part 6 §1), and is rendered as the
 *    considered outcome it is.
 *  - `failed` — the service's own error envelope, code verbatim.
 *  - `expired` — the pause's deadline passed: the conversion was **refused for want of a decision**.
 *    Never worded as if a default were applied (Part 7 §2.4).
 *  - `cancelled` — a card saying no report exists, because none does. Not an empty report shell.
 *
 * Cancel is offered in every non-terminal state and is described as best-effort, because it is: the
 * server may already have finished, and a cancel that loses that race must not overwrite the
 * recorded outcome. So the click re-reads the job rather than assuming it won.
 */

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
    <Link href="/convert" className="text-sm text-muted underline">
      Convert another file
    </Link>
  );
}

export default function ConversionJobPage() {
  const params = useParams<{ job_id: string }>();
  const jobId = params.job_id;
  // Handed forward by `/files/[file_id]` so the record can offer a re-convert; absent on a shared link.
  const fileId = useSearchParams().get("file_id");
  const queryClient = useQueryClient();

  // The consistent back affordance goes to this job's own parent: the file it came from when we know
  // it, otherwise the upload step (a shared link carries no file_id). Never raw browser-back.
  const back = fileId
    ? { href: `/files/${fileId}`, label: "Inspection" }
    : { href: "/convert", label: "Upload" };

  const [cancelError, setCancelError] = useState<ErrorEnvelopeModel | null>(null);
  const [cancelling, setCancelling] = useState(false);

  const job = useQuery(jobQuery(jobId));

  // The completion signal (v1.1 M39-S4, C1): chime + browser Notification, fired once when this
  // job makes the non-terminal → terminal transition, honoring the persisted mute toggle. It fires
  // only for a job the user launched (armed by the Convert submit and consumed here), so a refresh
  // of — or a shared link to — an already-finished job stays silent. The audio was armed by the
  // Convert click (`unlockAudio`, TargetPicker) so it plays even when the tab is backgrounded.
  useCompletionSignal(job.data?.state, jobId);

  async function handleCancel() {
    setCancelError(null);
    setCancelling(true);
    const result = await cancelJob(jobId);
    setCancelling(false);
    if (!result.ok) {
      // A cancel can legitimately fail — `JOB_ALREADY_TERMINAL` when the job finished first. That is
      // information, not noise: show the service's code and let the refreshed envelope tell the rest.
      setCancelError(
        toErrorEnvelope(result.error, "CANCEL_FAILED", "Could not cancel this job."),
      );
    }
    // Either way, re-read the job — the server's state is the answer, not our optimism.
    await queryClient.invalidateQueries({ queryKey: queryKeys.job(jobId) });
  }

  // A recovery resume returns the server's next envelope (re-paused for the rest, or completed). We
  // do not trust that shape directly: invalidate the poll so the page re-renders from a fresh GET,
  // the same "server state is the answer" rule as cancel.
  async function handleResumed() {
    await queryClient.invalidateQueries({ queryKey: queryKeys.job(jobId) });
  }

  if (job.isError) {
    return (
      <main className="space-y-4">
        <BackLink href={back.href} label={back.label} />
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
        <BackLink href={back.href} label={back.label} />
        <p role="status" className="text-muted">
          Loading this conversion…
        </p>
      </main>
    );
  }

  const state = envelope.state;
  const terminal = isTerminalJobState(state);
  // A `batch_convert` parent is an ordinary job whose `result` is the aggregate (Part 6 §3, v1.5
  // M58) and whose `children` projection names each fanned-out child job — both rendered below in
  // the batch branch. Everything else on this page is the single-file contract unchanged.
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
      <BackLink href={back.href} label={back.label} />
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

      {/*
        The batch parent's pause (v1.5 M58-S2): a `batch_convert` parent carries **no recovery
        block of its own** — per-file consent stays per-file, so the batch waits on the children
        that still need a decision, each answered on the child's own ordinary record. The
        `children` projection (present in every state) is rendered as-is: every child's honest
        state, with a link to its record.
      */}
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
                  File {i + 1} ·{" "}
                  <code className="font-mono text-xs">{child.state}</code>
                </span>
                <Link
                  href={`/convert/${child.job_id}`}
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

      {/*
        The completed batch record (v1.5 M58-S2): the parent tallies — the reused library
        `BatchTallies`/`LabelPresence`, rendered as the counts they are — above the per-file
        links, so the honest summary is structurally in view before any reader follows a child
        to its record (the layout law: summary above download, and the downloads live only on the
        children's own records). Each entry links to the **ordinary** child conversion record the
        existing convert page already renders; nothing here re-computes a report or a tally.
      */}
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
                    File {i + 1} ·{" "}
                    <code className="font-mono text-xs">{entry.status}</code>
                  </span>
                  <Link
                    href={`/convert/${entry.child_job_id}`}
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
          {/*
            The job is transient; the record is the durable, linkable outcome — and the only place
            the download lives, deliberately below the loss summary (M29-S2). A refusal routes there
            too: it is a recorded outcome, not a dead end. `file_id` is handed forward because
            neither the envelope nor the record carries it.
          */}
          {result?.conversion_id ? (
            <Link
              href={
                fileId
                  ? `/conversions/${result.conversion_id}?file_id=${encodeURIComponent(fileId)}`
                  : `/conversions/${result.conversion_id}`
              }
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
          {/* The service's own body: code `RECOVERY_REQUIRED`, and the refused conversion's id. */}
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
              You cancelled this batch, so <strong>no aggregate result exists for it</strong> —
              not an empty one, none at all. The individual conversions it had already launched
              are ordinary jobs and keep their own records.
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

      {/* A terminal state the UI does not have a card for is still named, never rendered blank. */}
      {terminal && state !== "completed" && !["failed", "expired", "cancelled"].includes(state) ? (
        <Card title={`Job ${state}`}>
          <p className="text-sm text-body">
            The service reported this job as <code className="font-mono">{state}</code>.
          </p>
        </Card>
      ) : null}

      {!batch && state === "completed" && !report ? (
        <Card title="Completed">
          <p className="text-sm text-body">
            This job completed but carried no conversion report.
          </p>
        </Card>
      ) : null}

      {/*
        The footer cancel serves the states with no other exit (`queued`, `running`). A paused job
        has a first-class decline *inside* the recovery step, so it is suppressed here — one decline,
        in the decision surface, rather than two identical buttons.
      */}
      {!terminal && state !== "awaiting_recovery" ? (
        <div className="space-y-2">
          <button
            type="button"
            onClick={handleCancel}
            disabled={cancelling}
            className="rounded-md border border-line px-3 py-1.5 text-sm text-body hover:bg-raised disabled:opacity-60"
          >
            {cancelling
              ? "Cancelling…"
              : batch
                ? "Cancel this batch"
                : "Cancel this conversion"}
          </button>
          <p className="text-xs text-faint">
            {batch
              ? "Cancelling abandons the batch's aggregate; the conversions it already launched keep their own records."
              : "Cancelling is best-effort: work already underway may finish first, and a conversion that has already produced its result keeps it."}
          </p>
          {cancelError ? <ErrorEnvelope envelope={cancelError} /> : null}
        </div>
      ) : null}
    </main>
  );
}
