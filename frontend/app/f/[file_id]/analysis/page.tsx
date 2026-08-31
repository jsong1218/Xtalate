/**
 * The workspace's Analysis tab — a reserved seam (UI redesign S2, D244; design spec §7, P6).
 *
 * Analysis is a named, **empty** affordance in this redesign: it renders a clearly-labelled
 * placeholder and does nothing. No engine work, no compute, no edit — the seam exists so the later
 * work (v1.8's analysis overlays) attaches without re-architecting the shell. S6 owns the polish
 * of the seam copy; this slice just makes the tab honest.
 */
export default function AnalysisTabPage() {
  return (
    <main className="space-y-3">
      <h1 className="text-2xl font-semibold tracking-tight">Analysis</h1>
      <p className="max-w-2xl text-sm text-muted">
        This tab is reserved for per-atom and trajectory analysis — coming in a later version. Your
        file and its reports are untouched; nothing here runs yet.
      </p>
    </main>
  );
}
