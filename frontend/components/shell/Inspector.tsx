/**
 * The workbench inspector rail (right side of `WorkbenchLayout`, design spec §"Shell architecture").
 *
 * A minimal stub for Task 7 (shell scaffold): the region exists with the right landmark role and
 * chrome tokens so the grid layout is real from the start, but its real contents — contextual
 * summary chips + cell + provenance on Report, atom/cell props + legend on Structure, collapsible —
 * are Task 10's job. Do not add real content here ahead of that task.
 */
export function Inspector() {
  return (
    <aside
      aria-label="Inspector"
      role="complementary"
      className="hidden w-64 shrink-0 border-l border-wb-hairline bg-wb-panel p-4 lg:block"
    >
      <h2 className="text-sm font-semibold text-strong">Inspector</h2>
    </aside>
  );
}
