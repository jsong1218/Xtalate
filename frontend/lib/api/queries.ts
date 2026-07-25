import { queryOptions } from "@tanstack/react-query";
import { apiClient } from "./client";

/**
 * TanStack Query wiring over the typed client (MASTER_SPEC Part 7 §5.1).
 *
 * The wizard's authoritative state is server state — the job envelope, the conversion record —
 * addressed by the resource ID in each page's URL. These `queryOptions` factories are the single
 * definition of how each resource is fetched and cached; pages call them so refresh / back / shared
 * links all reconstruct from a `GET`. The report resources are cached immutable (the client's
 * `staleTime: Infinity` default, `lib/query/client.ts`) because reports never mutate — re-validation
 * appends (Part 6 §2). Job polling opts back into refetching via the `?wait=5` long-poll below.
 */

/** Stable, hierarchical query keys — one namespace per resource kind. */
export const queryKeys = {
  capabilities: ["capabilities"] as const,
  limits: ["limits"] as const,
  file: (fileId: string) => ["files", fileId] as const,
  job: (jobId: string) => ["jobs", jobId] as const,
  conversion: (conversionId: string) => ["conversions", conversionId] as const,
} as const;

/**
 * The terminal job states (Part 6 §3.2 state machine). A refusal arrives as a **completed** job
 * (`ConversionReport.status === "refused"`, Part 6 §1), so `completed` is terminal here; the
 * refusal is a report-level outcome, not a job state.
 */
const TERMINAL_JOB_STATES = new Set(["completed", "failed", "cancelled", "expired"]);

export function isTerminalJobState(state: string): boolean {
  return TERMINAL_JOB_STATES.has(state);
}

/** `GET /v1/capabilities` — the Capability Matrix (landing format count, target picker, /formats). */
export function capabilitiesQuery() {
  return queryOptions({
    queryKey: queryKeys.capabilities,
    queryFn: async ({ signal }) => {
      const { data, error } = await apiClient.GET("/v1/capabilities", { signal });
      if (error) throw error;
      return data;
    },
  });
}

/** `GET /v1/limits` — instance limits, shown pre-upload so failure is visible before it happens. */
export function limitsQuery() {
  return queryOptions({
    queryKey: queryKeys.limits,
    queryFn: async ({ signal }) => {
      const { data, error } = await apiClient.GET("/v1/limits", { signal });
      if (error) throw error;
      return data;
    },
  });
}

/**
 * `GET /v1/jobs/{job_id}?wait=5` — the long-poll job query (Part 6 §3.1). The server holds the
 * request up to `wait` seconds for a terminal state, so the client re-issues immediately while the
 * job is non-terminal and stops once it is terminal. There is no fixed interval and no fake
 * progress: the envelope carries the truth, the UI renders it (Part 7 §2.4).
 */
export function jobQuery(jobId: string, waitSeconds = 5) {
  return queryOptions({
    queryKey: queryKeys.job(jobId),
    queryFn: async ({ signal }) => {
      const { data, error } = await apiClient.GET("/v1/jobs/{job_id}", {
        params: { path: { job_id: jobId }, query: { wait: waitSeconds } },
        signal,
      });
      if (error) throw error;
      return data;
    },
    // Long-poll: re-fetch as soon as the previous response returns, until the job is terminal.
    refetchInterval: (query) => {
      const state = query.state.data?.state;
      return state && isTerminalJobState(state) ? false : 0;
    },
    // Job envelopes are live state, not immutable reports — always considered stale.
    staleTime: 0,
  });
}
