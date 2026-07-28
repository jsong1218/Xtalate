"use client";

import { useQuery } from "@tanstack/react-query";
import { clientErrorEnvelope } from "./upload";
import { inspectSubmitQuery, isTerminalJobState, jobQuery } from "./queries";
import type { DiscoveryReport, ErrorBody, ErrorEnvelope } from "@/lib/report/types";

/**
 * The inspect data flow, composed into one hook (MASTER_SPEC Part 6 §2–§3; slice M28-S2).
 *
 * `/v1/inspect` is an async job like every long operation: POST submits it (idempotent, so one
 * submit per file+override), then the job is long-polled to a terminal state, and the Discovery
 * Report arrives in the completed envelope's `result.discovery_report`. This hook chains
 * {@link inspectSubmitQuery} → {@link jobQuery} and projects the pair into one honest state a page
 * can render directly, with no report shape or error handling re-derived at the call site.
 *
 * Failure is rendered, never swallowed: a submit rejection (e.g. the upload expired) and a
 * `failed` job both carry the service's own error body, coerced to the one {@link ErrorEnvelope}
 * the shared error component renders verbatim — the machine `code` is never paraphrased.
 */

export type InspectionState =
  | { status: "loading" }
  | { status: "error"; error: ErrorEnvelope }
  | { status: "ready"; report: DiscoveryReport };

/**
 * Coerce whatever an error path yields into a full {@link ErrorEnvelope}. `apiClient` throws the
 * parsed non-2xx body (already `{ error: {...} }`); a `failed` job stores the bare inner
 * {@link ErrorBody} (Part 6 §6). Anything unrecognizable becomes an honest client-side envelope
 * rather than a swallowed or mislabelled failure.
 */
export function toErrorEnvelope(raw: unknown, fallbackCode: string, fallbackMessage: string): ErrorEnvelope {
  if (raw && typeof raw === "object") {
    const obj = raw as Record<string, unknown>;
    const inner = obj.error;
    if (inner && typeof inner === "object" && "code" in inner) {
      return obj as unknown as ErrorEnvelope;
    }
    if ("code" in obj && "message" in obj) {
      return { error: obj as unknown as ErrorBody };
    }
  }
  return clientErrorEnvelope(fallbackCode, fallbackMessage);
}

export function useInspection(fileId: string, formatOverride?: string): InspectionState {
  const submit = useQuery(inspectSubmitQuery(fileId, formatOverride));
  const jobId = submit.data?.job_id;

  const job = useQuery({
    ...jobQuery(jobId ?? ""),
    enabled: Boolean(jobId),
  });

  // The submit itself failed (bad file_id, expired upload, …) — the service error body, verbatim.
  if (submit.isError) {
    return {
      status: "error",
      error: toErrorEnvelope(submit.error, "INSPECT_SUBMIT_FAILED", "Could not start inspection."),
    };
  }

  // A poll error is transport-level (the long-poll GET itself failed), distinct from a `failed` job.
  if (job.isError) {
    return {
      status: "error",
      error: toErrorEnvelope(job.error, "NETWORK_ERROR", "Could not reach the inspection job."),
    };
  }

  const envelope = job.data;
  if (!jobId || !envelope) return { status: "loading" };

  if (envelope.state === "failed") {
    return {
      status: "error",
      error: toErrorEnvelope(envelope.error, "PARSE_ERROR", "Inspection failed."),
    };
  }

  if (envelope.state === "cancelled") {
    return {
      status: "error",
      error: clientErrorEnvelope(
        "INSPECTION_CANCELLED",
        "This inspection was cancelled before it produced a report.",
      ),
    };
  }

  if (envelope.state === "completed") {
    const report = (envelope.result as { discovery_report?: DiscoveryReport } | null)
      ?.discovery_report;
    if (report) return { status: "ready", report };
    // Completed with no report is a contract violation, not a blank screen — say so.
    return {
      status: "error",
      error: clientErrorEnvelope("MALFORMED_RESPONSE", "Inspection completed without a report."),
    };
  }

  // Any *other* terminal state without a report (a future state-machine addition, an expired
  // pause) is named rather than spun on — polling stops at terminal states, so falling through
  // to "loading" here would be a spinner that never resolves (Part 7 §2.4).
  if (isTerminalJobState(envelope.state)) {
    return {
      status: "error",
      error: clientErrorEnvelope(
        "INSPECTION_NOT_COMPLETED",
        `The inspection job ended in state "${envelope.state}" without a report.`,
      ),
    };
  }

  // queued / running / any non-terminal state → still working.
  return { status: "loading" };
}
