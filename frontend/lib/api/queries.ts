import { infiniteQueryOptions, queryOptions } from "@tanstack/react-query";
import { apiClient, type Schemas } from "./client";

/** The job envelope, verbatim from the generated schema (Part 6 §3.2). */
export type JobEnvelope = Schemas["JobEnvelope"];

/** The byte-exact Assumption preview a paused job returns for a choice set (Part 6 §3.2, M31). */
export type RecoveryPreviewResponse = Schemas["RecoveryPreviewResponse"];

/**
 * One scenario's decision as the wizard submits it — the `{choice, parameters}` the engine reads.
 * The open index signature matches the generated wire type (each decision is an untyped object on
 * the schema), while keeping `choice`/`parameters` named for the components that build it.
 */
export interface RecoveryDecision {
  choice: string;
  parameters: Record<string, unknown>;
  [key: string]: unknown;
}

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
  inspect: (fileId: string, formatOverride?: string) =>
    ["inspect", fileId, formatOverride ?? null] as const,
  job: (jobId: string) => ["jobs", jobId] as const,
  conversion: (conversionId: string) => ["conversions", conversionId] as const,
  history: ["history"] as const,
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

/**
 * `POST /v1/inspect` — submit a Discovery Engine run for an uploaded file, returning the job
 * envelope (Part 6 §2). Modeled as a `queryOptions` factory, not a mutation, because inspect is
 * **idempotent** per `(file, override, registry)` (the endpoint docstring): re-issuing it returns the
 * same job, so caching by `(file_id, format_override)` fires exactly one submit per distinct target
 * and lets refresh / back reconstruct it. The returned `job_id` feeds {@link jobQuery} for polling;
 * `useInspection` composes the two. A `format_override` re-inspection is just a new key here.
 */
export function inspectSubmitQuery(fileId: string, formatOverride?: string) {
  return queryOptions({
    queryKey: queryKeys.inspect(fileId, formatOverride),
    queryFn: async ({ signal }) => {
      const { data, error } = await apiClient.POST("/v1/inspect", {
        body: { file_id: fileId, format_override: formatOverride ?? null },
        signal,
      });
      if (error) throw error;
      return data;
    },
    // The submit result (a job handle) is stable for a given (file, override) — never re-submit.
    staleTime: Infinity,
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

/**
 * `GET /v1/conversions/{conversion_id}` — the durable conversion record (Part 6 §4.4).
 *
 * The record page's single source of truth: both reports verbatim plus the `download` block. It is
 * served from persisted rows alone, so this resolves after the bytes have expired — which is exactly
 * why the page must render `download.available === false` as *expired*, never as *not found*.
 *
 * Cached under the client's `staleTime: Infinity` default: a record's reports never mutate
 * (re-validation **appends**, Part 6 §2), so nothing here changes on its own. The one part that does
 * age is `download` — the byte lifecycle — and a stale `available: true` resolves honestly, because
 * the download endpoint itself re-checks and answers `410 OUTPUT_EXPIRED`, which the panel renders.
 * Re-validating invalidates this key explicitly rather than polling for a change that has no clock.
 */
export function conversionQuery(conversionId: string) {
  return queryOptions({
    queryKey: queryKeys.conversion(conversionId),
    queryFn: async ({ signal }) => {
      const { data, error } = await apiClient.GET("/v1/conversions/{conversion_id}", {
        params: { path: { conversion_id: conversionId } },
        signal,
      });
      if (error) throw error;
      return data;
    },
  });
}

/**
 * The conversion semantics a retry must carry forward from the record it retries (Part 6 §2.1;
 * v0.7 review F6). Both default to the file page's values, so an ordinary convert passes nothing —
 * only "resolve and retry" fills them, from the record's *own* fields, so it re-runs under the same
 * rules the user is looking at rather than silently re-thresholding to the file-page defaults.
 */
export interface RetryConvertOptions {
  /** The conversion mode the record ran under (`conversion_report.mode`); defaults to `permissive`. */
  mode?: "strict" | "permissive";
  /** The record's tolerance profile name (from its Validation Report); defaults to `default`. */
  toleranceProfile?: string;
}

/**
 * `POST /v1/convert` — start a conversion of an uploaded file into a target format (Part 6 §3.1).
 *
 * The interactive-recovery submission the v0.7 UI makes: `allow_recovery: true`, so a conversion that
 * needs a decision **pauses** (`awaiting_recovery`) and the job page renders the M31 decision cards,
 * rather than refusing outright (D95, lifted). Recovery is about missing-required data, a separate
 * axis from loss-acknowledgement.
 *
 * `options` carries the record's own `mode`/`tolerance_profile` on a resolve-and-retry so the retry
 * runs under the same rules as the record (v0.7 review F6); the file page omits it and gets the
 * permissive / `default` defaults it always used. Used for "resolve and retry" from a refused
 * record: the refused row is immutable history, so this creates a **fresh** job for the same
 * `file_id` + `target_format_id` rather than editing it. Returns the new job envelope to route to,
 * or the server's error body (e.g. an expired upload).
 */
export async function submitConvert(
  fileId: string,
  targetFormatId: string,
  options: RetryConvertOptions = {},
): Promise<{ ok: true; envelope: JobEnvelope } | { ok: false; error: unknown }> {
  const { data, error } = await apiClient.POST("/v1/convert", {
    body: {
      file_id: fileId,
      target_format_id: targetFormatId,
      options: {
        mode: options.mode ?? "permissive",
        acknowledge_loss: false,
        acknowledge_parse_warnings: false,
        allow_recovery: true,
        tolerance_profile: options.toleranceProfile ?? "default",
      },
    },
  });
  if (error || !data) return { ok: false, error };
  return { ok: true, envelope: data };
}

/**
 * `POST /v1/validate` — re-threshold a stored conversion under a different tolerance profile
 * (Part 6 §2). This is **not** a re-parse: it re-evaluates the already-measured values, so it works
 * long after the bytes are gone, and it *appends* a new Validation Report rather than replacing the
 * old one. Returns the job envelope to poll, or the server's error body.
 *
 * The caller passes the profile it chose from the record page's picker (M32-S2): the request sends
 * that name (defaulting to `"default"`), so the re-thresholding is always under a bar the user
 * explicitly selected, never a silent one.
 */
export async function submitRevalidate(
  conversionId: string,
  toleranceProfile = "default",
): Promise<{ ok: true; envelope: JobEnvelope } | { ok: false; error: unknown }> {
  const { data, error } = await apiClient.POST("/v1/validate", {
    body: { conversion_id: conversionId, tolerance_profile: toleranceProfile },
  });
  if (error || !data) return { ok: false, error };
  return { ok: true, envelope: data };
}

/**
 * `POST /v1/jobs/{job_id}/recovery` — resume a paused convert with the user's interactive choices
 * (Part 6 §3.2, M31). The choices are `{scenario: {choice, parameters}}` — the same shape the engine
 * validated in v0.5 — and land in the report as `origin: "user"`. Returns the server's next envelope
 * (re-paused for the rest, or completed) or its error body; the caller re-reads the job from the poll
 * rather than assuming, exactly like {@link cancelJob}. An unoffered choice is `422
 * INVALID_RECOVERY_CHOICE`, whose envelope names the `offered_choices` for the card to render.
 */
export async function submitRecovery(
  jobId: string,
  choices: Record<string, RecoveryDecision>,
): Promise<{ ok: true; envelope: JobEnvelope } | { ok: false; error: unknown }> {
  const { data, error } = await apiClient.POST("/v1/jobs/{job_id}/recovery", {
    params: { path: { job_id: jobId } },
    body: { choices },
  });
  if (error || !data) return { ok: false, error };
  return { ok: true, envelope: data };
}

/**
 * `POST /v1/jobs/{job_id}/recovery/preview` — the byte-exact Assumption preview (Part 6 §3.2, M31).
 *
 * Returns the exact `description` sentences the resume *would* record for `choices`, generated by the
 * engine's real apply path — never re-derived client-side (P2). It does not advance the job: the UI
 * shows a user the provenance they are about to create before they confirm it (P4). Recovery is
 * all-or-nothing, so an incomplete set returns no `previews` and names the `unresolved` scenarios;
 * a bad choice is the same `422 INVALID_RECOVERY_CHOICE` the resume gives.
 */
export async function previewRecovery(
  jobId: string,
  choices: Record<string, RecoveryDecision>,
): Promise<{ ok: true; preview: RecoveryPreviewResponse } | { ok: false; error: unknown }> {
  const { data, error } = await apiClient.POST("/v1/jobs/{job_id}/recovery/preview", {
    params: { path: { job_id: jobId } },
    body: { choices },
  });
  if (error || !data) return { ok: false, error };
  return { ok: true, preview: data };
}

/**
 * `POST /v1/jobs/{job_id}/cancel` — request cancellation (Part 6 §3.2, §5).
 *
 * Cancellation is **best-effort and honest about it**: the server moves a `queued`,
 * `running`, or `awaiting_recovery` job to `cancelled`, but a job that reached a terminal state
 * first keeps that outcome (`JOB_ALREADY_TERMINAL`) — in particular an already-`expired` pause has
 * resolved to a *refusal*, which a cancel must never erase. So this returns the server's envelope
 * or its error body and the caller re-reads state from the poll; the UI never assumes the cancel won.
 * A repeated cancel of an already-`cancelled` job is an idempotent 200, not an error.
 */
export async function cancelJob(
  jobId: string,
): Promise<{ ok: true; envelope: JobEnvelope } | { ok: false; error: unknown }> {
  const { data, error } = await apiClient.POST("/v1/jobs/{job_id}/cancel", {
    params: { path: { job_id: jobId } },
  });
  if (error || !data) return { ok: false, error };
  return { ok: true, envelope: data };
}

/**
 * `GET /v1/history` — the durable list of past conversions, newest first (Part 6 §4.4; slice
 * M33-S2). Pagination is **keyset over the server's opaque `next_cursor`**, never a client-side
 * offset: each page hands its `next_cursor` back as `?cursor=` for the following page, and the last
 * page omits it (`getNextPageParam` returns `undefined`, which stops `useInfiniteQuery`). Because the
 * cursor names a fixed point in the `(created_at, conversion_id)` ordering, a conversion added
 * between fetches never shifts or duplicates a row the way an offset would.
 *
 * Unlike the report queries, history is **live** state — a new conversion appears, and deleting a
 * source file removes that row's `file_id` (re-convert/delete fall away while the report stays) — so
 * this overrides the client's immutable `staleTime` default to refetch on focus and after a delete.
 */
export function historyInfiniteQuery(pageSize = 25) {
  return infiniteQueryOptions({
    queryKey: queryKeys.history,
    queryFn: async ({ pageParam, signal }) => {
      const { data, error } = await apiClient.GET("/v1/history", {
        params: { query: { limit: pageSize, cursor: pageParam } },
        signal,
      });
      if (error) throw error;
      return data;
    },
    initialPageParam: null as string | null,
    getNextPageParam: (lastPage) => lastPage.next_cursor ?? undefined,
    staleTime: 0,
  });
}

/**
 * `DELETE /v1/files/{file_id}` — delete an uploaded source file now, rather than waiting out its
 * retention window (Part 6 §4.3; slice M33-S2). The conversion **record and its report survive** —
 * only the source bytes go — which is the reports-outlive-bytes guarantee made a user action: after
 * this, the history row loses its `file_id` (no more re-convert), but "open record" still resolves.
 * A `204` carries no body; the caller re-reads history (invalidates {@link queryKeys.history})
 * rather than mutating the cache, so the list reflects the server, not an optimistic guess.
 */
export async function deleteFile(
  fileId: string,
): Promise<{ ok: true } | { ok: false; error: unknown }> {
  const { error } = await apiClient.DELETE("/v1/files/{file_id}", {
    params: { path: { file_id: fileId } },
  });
  if (error) return { ok: false, error };
  return { ok: true };
}
