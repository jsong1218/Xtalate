"use client";

import { LossIcon } from "@/components/loss/icons";
import { ErrorEnvelope } from "@/components/ErrorEnvelope";
import { SummaryChips } from "@/components/report/SummaryChips";
import { formatUtc } from "@/lib/format/datetime";
import { RecoveryWizard } from "./RecoveryWizard";
import {
  previewRecovery as defaultPreview,
  submitRecovery as defaultSubmit,
  type JobEnvelope,
} from "@/lib/api/queries";
import type {
  AwaitingRecoveryBlock,
  ErrorEnvelope as ErrorEnvelopeModel,
} from "@/lib/report/types";

/**
 * The recovery **step** (MASTER_SPEC Part 7 §3.1; slice M31-S2).
 *
 * When a convert job pauses `awaiting_recovery`, this is the full-width surface that replaces the
 * v0.6 read-only placeholder — a scientific decision page, not a modal. It composes four things and
 * owns none of the decision logic itself:
 *
 *  1. **The framing.** One line naming how many decisions the conversion still owes, so the user
 *     knows the size of what they are being asked before they scroll.
 *  2. **The deadline, stated as a refusal.** When `expires_at` passes with no choice, the conversion
 *     is *refused for want of a decision* — no default, no invented value (Part 4 §3.2). The copy
 *     never reads as "we'll pick something." It is shown up front, not buried under the form.
 *  3. **The pre-flight draft as §4 summary chips.** The decisions are made in full view of what this
 *     conversion will already keep and drop — the chips come straight off `block.draft_report`, the
 *     client never recomputes loss (Part 7 §2).
 *  4. **The {@link RecoveryWizard}**, which turns the choices into the exact `POST …/recovery` body.
 *
 * **Decline is first-class** (deliverable 7): a "Cancel conversion" control lives inside the step, so
 * the user is never trapped between deciding and leaving. It is the same best-effort cancel the page
 * offers elsewhere — an `awaiting_recovery` job is cancellable — surfaced here as an equal option.
 * Decline logic (and the resume re-read) live on the page; this component takes them as callbacks so
 * it stays a pure presentation of the paused envelope.
 */
export function RecoveryStep({
  block,
  jobId,
  expiresAt,
  onResumed,
  onDecline,
  declining = false,
  declineError = null,
  submit = defaultSubmit,
  preview = defaultPreview,
}: {
  block: AwaitingRecoveryBlock;
  jobId: string;
  /** The pause's TTL horizon from the job envelope; `null` when the service reported none. */
  expiresAt?: string | null;
  /** Called with the server's next envelope after a successful resume (the page re-reads the job). */
  onResumed: (envelope: JobEnvelope) => void;
  /** First-class decline — the page cancels the job and re-reads state from the poll. */
  onDecline: () => void;
  declining?: boolean;
  declineError?: ErrorEnvelopeModel | null;
  submit?: React.ComponentProps<typeof RecoveryWizard>["submit"];
  preview?: React.ComponentProps<typeof RecoveryWizard>["preview"];
}) {
  const n = block.unresolved_scenarios.length;

  return (
    <section
      aria-label="Recovery decisions"
      data-testid="recovery-step"
      className="space-y-5 rounded-lg border border-cb-assumption bg-cb-assumption-bg p-5"
    >
      <div className="space-y-3">
        <div className="flex flex-wrap items-center gap-2">
          <LossIcon kind="assumption" />
          <h2 className="text-xl font-semibold text-strong">
            This conversion needs {n} {n === 1 ? "decision" : "decisions"} before it can proceed
          </h2>
          <code className="rounded bg-raised px-1.5 py-0.5 font-mono text-xs font-semibold text-cb-assumption">
            awaiting_recovery
          </code>
        </div>
        <p className="text-sm text-strong">
          The target format needs information this file does not contain. Xtalate paused rather than
          filling it in, because anything it invented would be data you never supplied — so nothing
          is written until you decide.
        </p>

        {/* The deadline, said plainly and up front — expiry refuses, it does not choose. */}
        <p className="text-sm text-body" data-testid="recovery-deadline">
          {expiresAt ? (
            <>
              This pause is held until{" "}
              <time dateTime={expiresAt} className="font-medium text-strong">
                {formatUtc(expiresAt)}
              </time>
              .{" "}
            </>
          ) : null}
          If the deadline passes with no choice supplied, the conversion is <strong>refused</strong>{" "}
          — no default is applied and no value is invented. Nothing is written until you decide.
        </p>
      </div>

      {/* Rule 3: decide in full view of what this conversion already keeps and drops. */}
      <div className="space-y-2">
        <h3 className="text-sm font-semibold text-body">
          What this conversion will keep and drop, before your decisions
        </h3>
        <SummaryChips report={block.draft_report} />
      </div>

      <div className="rounded-lg border border-line bg-surface p-4">
        <RecoveryWizard
          block={block}
          jobId={jobId}
          onResumed={onResumed}
          submit={submit}
          preview={preview}
        />
      </div>

      {/* Decline is first-class, not a trap: an equal way out that records the honest outcome. */}
      <div className="space-y-1 border-t border-cb-assumption/30 pt-4">
        <button
          type="button"
          onClick={onDecline}
          disabled={declining}
          className="rounded-md border border-line bg-surface px-3 py-1.5 text-sm text-body hover:bg-raised disabled:opacity-60"
        >
          {declining ? "Cancelling…" : "Cancel conversion"}
        </button>
        <p className="text-xs text-faint">
          Cancelling writes nothing and records that you cancelled — not an empty report, none at
          all. You can convert again with your choices supplied up front.
        </p>
        {declineError ? <ErrorEnvelope envelope={declineError} /> : null}
      </div>
    </section>
  );
}
