"use client";

import { useState } from "react";
import { deleteFile } from "@/lib/api/queries";

/** The instance's retention windows, in the plain units the confirmation states (Part 6 §5). */
export interface RetentionPolicy {
  uploadHours: number;
  reportDays: number | null;
}

/**
 * Delete an uploaded source file, behind a confirmation that **names the retention policy in plain
 * words** (Part 7 §2.6; slice M33-S2).
 *
 * Two honesty rules shape it. (1) It never deletes on the first click: the confirmation states what
 * *survives* — the conversion report stays readable, reports-outlive-bytes — and what the automatic
 * windows would otherwise have been, so the user is choosing to bring a deletion *forward*, not
 * discovering later that a link died. (2) It reports a failed delete instead of silently assuming
 * success; only a real `204` calls `onDeleted`, which the parent uses to re-read history from the
 * server (the row keeps its report but loses its re-convert/delete affordances).
 */
function retentionSentence(retention: RetentionPolicy | null): string {
  const base = "This deletes the uploaded source file now. Its conversion report stays readable.";
  if (retention === null) return base;
  const reports =
    retention.reportDays === null
      ? "reports are kept indefinitely"
      : `reports for ${retention.reportDays} days`;
  return `${base} Otherwise, this instance keeps uploads for ${retention.uploadHours} h and ${reports}.`;
}

export function DeleteFileControl({
  fileId,
  retention,
  onDeleted,
}: {
  fileId: string;
  retention: RetentionPolicy | null;
  onDeleted: () => void;
}) {
  const [confirming, setConfirming] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [failed, setFailed] = useState(false);

  if (!confirming) {
    return (
      <button
        type="button"
        onClick={() => {
          setFailed(false);
          setConfirming(true);
        }}
        className="text-sm text-muted underline underline-offset-2 hover:text-strong"
      >
        Delete file
      </button>
    );
  }

  async function confirmDelete() {
    setDeleting(true);
    setFailed(false);
    const result = await deleteFile(fileId);
    setDeleting(false);
    if (result.ok) {
      setConfirming(false);
      onDeleted();
    } else {
      setFailed(true);
    }
  }

  return (
    <div className="space-y-2 rounded-md border border-line bg-raised p-3">
      <p className="text-sm text-body">{retentionSentence(retention)}</p>
      {failed ? (
        <p className="text-sm text-cb-fail" role="alert">
          The file could not be deleted — nothing was removed. Please try again.
        </p>
      ) : null}
      <div className="flex items-center gap-3">
        <button
          type="button"
          onClick={confirmDelete}
          disabled={deleting}
          className="rounded-md bg-cb-fail-solid px-3 py-1 text-sm font-medium text-white disabled:opacity-60"
        >
          {deleting ? "Deleting…" : "Delete"}
        </button>
        <button
          type="button"
          onClick={() => setConfirming(false)}
          disabled={deleting}
          className="text-sm text-muted underline underline-offset-2"
        >
          Cancel
        </button>
      </div>
    </div>
  );
}
