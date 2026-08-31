"use client";

import { useMemo, useState } from "react";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { ErrorEnvelope } from "@/components/ErrorEnvelope";
import { TargetPicker } from "@/components/TargetPicker";
import { ConversionJob } from "@/components/workspace/ConversionJob";
import { apiClient } from "@/lib/api/client";
import { capabilitiesQuery } from "@/lib/api/queries";
import { toErrorEnvelope, useInspection } from "@/lib/api/useInspection";
import { writableTargets, type CapabilitiesMap } from "@/lib/capabilities/types";
import { armCompletionSignal } from "@/lib/notify/completionSignal";
import type { ErrorEnvelope as ErrorEnvelopeModel } from "@/lib/report/types";

/**
 * The workspace's Convert tab (UI redesign S2, D244; design spec §3, D-R1/D-R5).
 *
 * Two modes on one surface:
 *
 *  - **Idle** (`/f/[file_id]/convert`): today's target-select + pre-flight loss preview
 *    (`TargetPicker`, moved from the old file page) — the reader picks a target, sees exactly what
 *    it would drop/recover, and commits on the explicit confirm step (B2).
 *  - **Active job** (`/f/[file_id]/convert?job=…`): the live conversion (ported job page) — phases,
 *    the interactive recovery step, and the completed record link. The Convert submit routes here
 *    with the job id, so the whole flow stays in the workspace; the rail's guided-spine CTA is the
 *    door in.
 */
export default function ConvertTabPage() {
  const params = useParams<{ file_id: string }>();
  const router = useRouter();
  const fileId = params.file_id;
  const jobId = useSearchParams().get("job");

  const [submitError, setSubmitError] = useState<ErrorEnvelopeModel | null>(null);

  const inspection = useInspection(fileId);
  const capabilities = useQuery(capabilitiesQuery());
  const targets = useMemo(
    () => (capabilities.data ? writableTargets(capabilities.data as CapabilitiesMap) : []),
    [capabilities.data],
  );

  async function handleConvert(targetFormatId: string, mode: "permissive" | "strict") {
    setSubmitError(null);
    const { data, error } = await apiClient.POST("/v1/convert", {
      body: {
        file_id: fileId,
        target_format_id: targetFormatId,
        // v0.7 has the interactive recovery cards (M31), so the button now submits
        // allow_recovery: true: a conversion that needs a decision **pauses** (awaiting_recovery)
        // and the tab renders the decision cards, rather than refusing outright as v0.6 did (D95).
        // Pausing to ask is the explicit-recovery path (P4); nothing is ever defaulted, and an
        // unanswered pause still expires to a refusal. Strict-mode loss likewise refuses.
        options: {
          mode,
          acknowledge_loss: false,
          acknowledge_parse_warnings: false,
          allow_recovery: true,
          tolerance_profile: "default",
        },
      },
    });
    if (error || !data) {
      setSubmitError(toErrorEnvelope(error, "CONVERT_SUBMIT_FAILED", "Could not start the conversion."));
      return;
    }
    // Arm this job's completion signal (v1.1 M39-S4, C1): only a job the user just launched may
    // chime when it finishes, so a later refresh of — or a shared link to — the finished job stays
    // silent.
    armCompletionSignal(data.job_id);
    router.push(`/f/${fileId}/convert?job=${encodeURIComponent(data.job_id)}`);
  }

  if (jobId) {
    return (
      <main>
        <ConversionJob jobId={jobId} fileId={fileId} />
      </main>
    );
  }

  return (
    <main className="space-y-6">
      <header className="space-y-1">
        <h1 className="text-2xl font-semibold tracking-tight">Convert</h1>
        <p className="max-w-2xl text-sm text-muted">
          Choose a target format. The preview below names exactly what the target cannot express,
          what it would drop, and what would need a recovery decision — nothing converts silently.
        </p>
      </header>
      {inspection.status === "loading" ? (
        <p className="text-muted" role="status">
          Inspecting this file…
        </p>
      ) : inspection.status === "error" ? (
        <div className="space-y-4">
          <ErrorEnvelope envelope={inspection.error} />
          <Link href="/" className="text-muted underline">
            Upload a different file
          </Link>
        </div>
      ) : (
        <>
          {submitError ? <ErrorEnvelope envelope={submitError} /> : null}
          {targets.length > 0 ? (
            <TargetPicker
              discovery={inspection.report}
              targets={targets}
              onConvert={handleConvert}
            />
          ) : null}
        </>
      )}
    </main>
  );
}
