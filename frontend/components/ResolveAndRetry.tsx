"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { ErrorEnvelope } from "@/components/ErrorEnvelope";
import { submitConvert } from "@/lib/api/queries";
import { toErrorEnvelope } from "@/lib/api/useInspection";
import type { ConversionRecord, ErrorEnvelope as ErrorEnvelopeModel } from "@/lib/report/types";

/**
 * "Resolve and retry" from a refused record (MASTER_SPEC Part 7; slice M32-S2).
 *
 * A refused conversion's record is **immutable history**, but a `RECOVERY_REQUIRED` refusal is not a
 * dead-end: the same source and target can be re-submitted *with interactive recovery*, turning the
 * scenarios that were unresolved back into M31 decision cards. This is the action v0.6 could not offer
 * — it had no cards to send the user to, so a refused record ended in "you'll have to start over".
 *
 * Three rules are load-bearing (and tested):
 *
 *  1. It creates **new history** — a fresh `POST /v1/convert` for the same `file_id` +
 *     `target_format_id`, never a mutation of the refused row (standing rule 1: the bright line
 *     reaches the pixels). The refused record's own id is never sent.
 *  2. "Same file and target" extends to **same rules**: the retry re-runs under the record's own
 *     `mode` and tolerance profile (v0.7 review F6), read off the very fields the provenance strip
 *     renders — `conversion_report.mode` and the Validation Report's profile name — never the file
 *     page's permissive/`default` defaults. Retrying a refused *strict-mode* record under permissive
 *     would silently re-threshold what the user is looking at; instead the copy states the mode so
 *     the sameness is visible, not just true.
 *  3. The retry needs the **source upload still in hand**. The record carries no `file_id` of its own
 *     (Part 6 §4.4), so it is threaded forward from the page that linked here; absent it, the honest
 *     path is a fresh upload, not a link that would 404.
 *  4. A refusal with **no unresolved scenarios** (e.g. `UNACKNOWLEDGED_LOSS`) has no cards to
 *     re-enter, so no retry is offered — this component renders nothing.
 */
export function ResolveAndRetry({
  record,
  fileId,
}: {
  record: ConversionRecord;
  /** The source upload id, threaded forward from the file/job page; `null` if not in hand here. */
  fileId: string | null;
}) {
  const router = useRouter();
  const [error, setError] = useState<ErrorEnvelopeModel | null>(null);
  const [busy, setBusy] = useState(false);

  const report = record.conversion_report;
  const refusal = report.refusal;
  const targetFormatId = record.target.format_id;

  // Carry the record's own semantics forward, from the same fields the provenance strip renders
  // (never re-derived): the mode is on the Conversion Report; the tolerance profile name is on the
  // Validation Report, which a refused conversion has none of — so it stays undefined and the retry
  // uses the `default` profile, exactly as this record's (never-run) validation would have.
  const mode = report.mode;
  const profileName =
    typeof record.validation_report?.tolerance_profile?.name === "string"
      ? record.validation_report.tolerance_profile.name
      : undefined;

  // Only a recovery refusal has decisions to re-enter; without unresolved scenarios (or a target to
  // aim at) there is nothing the cards could resolve, so this offers nothing rather than a false path.
  if (
    report.status !== "refused" ||
    refusal === null ||
    refusal.unresolved_scenarios.length === 0 ||
    targetFormatId === null
  ) {
    return null;
  }

  async function handleRetry() {
    setError(null);
    setBusy(true);
    const result = await submitConvert(fileId as string, targetFormatId as string, {
      mode,
      toleranceProfile: profileName,
    });
    if (!result.ok) {
      setBusy(false);
      setError(
        toErrorEnvelope(result.error, "RESOLVE_RETRY_FAILED", "Could not start a new conversion."),
      );
      return;
    }
    // The new job carries the file_id forward, exactly as the file page does, so its own record can
    // offer this action again if it too refuses.
    router.push(`/convert/${result.envelope.job_id}?file_id=${encodeURIComponent(fileId as string)}`);
  }

  return (
    <section aria-label="Resolve and retry" className="space-y-2">
      <p className="text-sm text-slate-700">
        This refusal is preserved as-is. To get a converted file, re-run the conversion of the same
        source into <span className="font-mono text-slate-800">{targetFormatId}</span> in{" "}
        <span className="font-medium text-slate-800">{mode}</span> mode
        {profileName ? (
          <>
            {" "}
            under the <span className="font-mono text-slate-800">{profileName}</span> tolerance
            profile
          </>
        ) : null}{" "}
        — the same rules as this record — and make the{" "}
        {refusal.unresolved_scenarios.length === 1 ? "decision" : "decisions"} it needs — a fresh
        conversion, not a change to this record.
      </p>
      {fileId ? (
        <button
          type="button"
          onClick={handleRetry}
          disabled={busy}
          className="rounded-md bg-slate-900 px-3 py-1.5 text-sm font-medium text-white hover:bg-slate-700 disabled:opacity-60"
        >
          {busy ? "Starting…" : "Resolve and retry"}
        </button>
      ) : (
        <p className="text-sm text-slate-600">
          The uploaded source is no longer in hand here, so it must be provided again.{" "}
          <Link href="/convert" className="text-slate-700 underline">
            Upload the file again to resolve
          </Link>
          .
        </p>
      )}
      {error ? <ErrorEnvelope envelope={error} /> : null}
    </section>
  );
}
