/**
 * The advisory seam (MASTER_SPEC Part 7 §3.1, deliverable 8; slice M31-S3).
 *
 * When the v0.5 usage aggregation returns data for an option, this surfaces it as a plain-language
 * note **on that option** — how others converting the same pair tended to decide. It is advisory
 * only: a note, never a control, so it can never become a default or a preselection (the recovery
 * bright line). Surfacing that data is a **pre-authorized cut to post-1.0** — a fresh 1.0 instance
 * has no aggregation — so in shipped 1.0 this always renders nothing. It exists as the wired seam:
 * a post-1.0 slice populates {@link Advisory} from the aggregation query and the note appears with no
 * other change to the card.
 */
export interface Advisory {
  /** A plain-language advisory to show on the option; empty/absent renders nothing. */
  note: string;
}

export function AdvisoryNote({ advisory }: { advisory?: Advisory | null }) {
  if (!advisory?.note.trim()) return null;
  return (
    <p role="note" data-testid="advisory-note" className="mt-1 text-xs italic text-slate-500">
      {advisory.note}
    </p>
  );
}
