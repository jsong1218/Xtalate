"use client";

import { useCallback, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { apiClient } from "./client";
import { jobQuery } from "./queries";
import { toErrorEnvelope } from "./useInspection";
import { clientErrorEnvelope } from "./upload";
import type { ErrorEnvelope } from "@/lib/report/types";

/**
 * The analyze data flow, composed into one hook (v1.8 M70; MASTER_SPEC Part 6 §2–§3, Part 7 §6).
 *
 * Unlike inspect, analyze is a **user action, not an idempotent lookup**: the user picks one of the
 * installed analysis plugins and runs it, and each `POST /v1/analyze` creates a fresh job (the
 * endpoint mints a new id per submit). So this mirrors the *convert* flow — a submit mutation that
 * yields a `job_id`, then the same `?wait=5` long-poll every long operation uses — and projects the
 * pair into one state the Analysis tab renders directly.
 *
 * Analysis carries its own transport report (the library produces no `ConversionReport` for it): a
 * completed job embeds `result.analysis_report`, and **both** its outcomes are a completed job at
 * HTTP 200 — `status: "ok"` (the plugin annotated the object) and `status: "error"` (the plugin ran
 * and failed, leaving the object untouched — the analysis analogue of a refused conversion, D268).
 * Both are `status: "ready"` here; `AnalysisResults` renders the error outcome honestly. A *parse*
 * failure is different — nothing could be read to analyze — and surfaces as a failed job → an error
 * envelope, exactly as inspect/convert would.
 */

/** The `analysis_report` a completed analyze job embeds (backend `AnalysisReport`, Part 6 §6). */
export interface AnalysisReport {
  status: "ok" | "error";
  plugin: string;
  plugin_version: string;
  results: Record<string, unknown> | null;
  record: Record<string, unknown> | null;
  message: string | null;
}

export type AnalysisState =
  | { status: "idle" }
  | { status: "running"; plugin: string }
  | { status: "error"; error: ErrorEnvelope }
  | { status: "ready"; report: AnalysisReport };

export interface UseAnalysis {
  state: AnalysisState;
  /** Submit an analyze job for `plugin` against this file; replaces any prior run. */
  run: (plugin: string) => void;
  /** Return to the picker (drop the current run without touching the file). */
  reset: () => void;
}

export function useAnalysis(fileId: string): UseAnalysis {
  const [jobId, setJobId] = useState<string | null>(null);
  const [running, setRunning] = useState<string | null>(null);

  const submit = useMutation({
    mutationFn: async (plugin: string) => {
      const { data, error } = await apiClient.POST("/v1/analyze", {
        body: { file_id: fileId, plugin, format_override: null },
      });
      if (error || !data) throw error ?? new Error("analyze submit returned no job");
      return data;
    },
    onSuccess: (envelope) => setJobId(envelope.job_id),
  });

  const job = useQuery({
    ...jobQuery(jobId ?? ""),
    enabled: Boolean(jobId),
  });

  const run = useCallback(
    (plugin: string) => {
      setRunning(plugin);
      setJobId(null);
      submit.reset();
      submit.mutate(plugin);
    },
    [submit],
  );

  const reset = useCallback(() => {
    setRunning(null);
    setJobId(null);
    submit.reset();
  }, [submit]);

  return { state: project(), run, reset };

  function project(): AnalysisState {
    if (running === null) return { status: "idle" };

    // The submit itself failed (expired upload, unknown plugin race, …) — the service error, verbatim.
    if (submit.isError) {
      return {
        status: "error",
        error: toErrorEnvelope(submit.error, "ANALYZE_SUBMIT_FAILED", "Could not start analysis."),
      };
    }

    // A poll error is transport-level (the long-poll GET itself failed), distinct from a failed job.
    if (job.isError) {
      return {
        status: "error",
        error: toErrorEnvelope(job.error, "NETWORK_ERROR", "Could not reach the analysis job."),
      };
    }

    const envelope = job.data;
    if (!jobId || !envelope) return { status: "running", plugin: running };

    if (envelope.state === "failed") {
      return {
        status: "error",
        error: toErrorEnvelope(envelope.error, "PARSE_ERROR", "Analysis failed: the file could not be parsed."),
      };
    }

    if (envelope.state === "cancelled") {
      return {
        status: "error",
        error: clientErrorEnvelope(
          "ANALYSIS_CANCELLED",
          "This analysis was cancelled before it produced a report.",
        ),
      };
    }

    if (envelope.state === "completed") {
      const report = (envelope.result as { analysis_report?: AnalysisReport } | null)
        ?.analysis_report;
      if (report) return { status: "ready", report };
      return {
        status: "error",
        error: clientErrorEnvelope("MALFORMED_RESPONSE", "Analysis completed without a report."),
      };
    }

    // queued / running / any non-terminal state → still working.
    return { status: "running", plugin: running };
  }
}
