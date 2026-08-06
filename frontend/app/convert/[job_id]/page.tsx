"use client";

import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import { useState } from "react";
import { ErrorEnvelope } from "@/components/ErrorEnvelope";
import { JobPhase } from "@/components/JobPhase";
import { RecoveryStep } from "@/components/recovery/RecoveryStep";
import { ConversionReportPanel } from "@/components/report/ConversionReportPanel";
import { RefusalPanel } from "@/components/report/RefusalPanel";
import { cancelJob, isTerminalJobState, jobQuery, queryKeys } from "@/lib/api/queries";
import { toErrorEnvelope } from "@/lib/api/useInspection";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import type {
  AwaitingRecoveryBlock,
  ConversionReport,
  ErrorEnvelope as ErrorEnvelopeModel,
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

  const [cancelError, setCancelError] = useState<ErrorEnvelopeModel | null>(null);
  const [cancelling, setCancelling] = useState(false);

  const job = useQuery(jobQuery(jobId));

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
      <main>
        <p role="status" className="text-muted">
          Loading this conversion…
        </p>
      </main>
    );
  }

  const state = envelope.state;
  const terminal = isTerminalJobState(state);
  const result = (envelope.result ?? null) as {
    conversion_id?: string;
    conversion_report?: ConversionReport;
  } | null;
  const report = result?.conversion_report;

  return (
    <main className="space-y-6">
      <header className="space-y-1">
        <h1 className="text-2xl font-semibold tracking-tight">Conversion</h1>
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
              className="inline-block text-sm font-medium text-strong underline"
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

      {state === "expired" ? (
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

      {state === "cancelled" ? (
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

      {state === "completed" && !report ? (
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
            {cancelling ? "Cancelling…" : "Cancel this conversion"}
          </button>
          <p className="text-xs text-faint">
            Cancelling is best-effort: work already underway may finish first, and a conversion that
            has already produced its result keeps it.
          </p>
          {cancelError ? <ErrorEnvelope envelope={cancelError} /> : null}
        </div>
      ) : null}
    </main>
  );
}
