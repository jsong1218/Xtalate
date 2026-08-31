"use client";

/**
 * The reserved empty seams of the workspace shell (UI redesign S6, D247; design spec §7, P6).
 *
 * Analysis, File Repair, and an AI Assistant are named, deliberate **non-goals** of this version:
 * each is reserved as a clearly-labelled "coming later" seat so the deferred work (v1.8's analysis
 * overlays, a repair flow at the conversion seam, an assistant) attaches without re-architecting
 * the shell — and so the product never lets an affordance that does nothing pretend to be a
 * feature. The **Analysis** seam is its own route (`/f/[file_id]/analysis`); this component is the
 * two **non-route** seams of the workspace shell: **File Repair** (an action affordance, inert) and
 * **Assistant** (a side-panel slot, inert).
 *
 * Both render nothing actionable — no link, no `onClick`, no hidden behavior. Yet each is a real,
 * focus-safe presence: File Repair is a genuinely `disabled` button (a keyboard/screen-reader user
 * learns from the disabled state + the adjacent note that the action exists but does nothing yet,
 * instead of blaming a dead control, and it cannot be activated), and Assistant is a plain labelled
 * box, not a control. **S6 is the guard against secondary-goal creep (P6)** — the seams stay empty.
 */
export function FutureSeams() {
  return (
    <section
      aria-label="Coming in a later version"
      data-testid="future-seams"
      className="mt-8 space-y-3 border-t border-line pt-4"
    >
      <h2 className="text-sm font-semibold text-strong">Coming in a later version</h2>
      <p className="text-sm text-muted">
        These seats are reserved so later work can attach without re-architecting the workspace.
        Nothing here runs yet.
      </p>
      <div className="flex flex-wrap gap-3">
        {/* File Repair — reserved as an action affordance at the conversion seam; inert (disabled). */}
        <div
          data-testid="seam-repair"
          className="flex items-center gap-2 rounded-md border border-dashed border-line px-3 py-2"
        >
          <button
            type="button"
            disabled
            className="cursor-not-allowed rounded border border-line px-2 py-1 text-sm text-faint"
          >
            File repair
          </button>
          <span className="text-sm text-faint">coming later</span>
        </div>
        {/* Assistant — reserved as a side-panel slot; not a control, just a labelled seat. */}
        <div
          data-testid="seam-assistant"
          className="flex items-center gap-2 rounded-md border border-dashed border-line px-3 py-2"
        >
          <span className="text-sm font-medium text-body">Assistant</span>
          <span className="text-sm text-faint">coming later</span>
        </div>
      </div>
    </section>
  );
}