/**
 * The workbench status bar (bottom row of `WorkbenchLayout`, design spec §"Shell architecture").
 *
 * A minimal stub for Task 7 (shell scaffold): the region exists with the right landmark role and
 * chrome tokens so the grid layout is real from the start, but its real contents — file · format ·
 * atoms · frames · job state · demo/auto-expire indicator — are Task 11's job. Do not add real
 * content here ahead of that task.
 */
export function StatusBar() {
  return (
    <footer
      role="contentinfo"
      className="flex h-8 items-center border-t border-wb-hairline bg-wb-status px-4 text-xs text-muted"
    >
      <span className="sr-only">Status bar</span>
    </footer>
  );
}
