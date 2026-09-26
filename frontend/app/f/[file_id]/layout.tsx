"use client";

import { useParams } from "next/navigation";
import { WorkspaceTabs } from "@/components/shell/WorkspaceTabs";
import { FutureSeams } from "@/components/shell/FutureSeams";

/**
 * The file-centric workspace shell (UI redesign S2, D244; design spec §3, D-R1/D-R2).
 *
 * Every `/f/[file_id]` tab renders inside one layout: the tabbed main column
 * (`Inspect · Structure · Convert · Report · Analysis`), then the reserved **empty seams** of the
 * shell (S6, D247) below the active tab's content — the File Repair action and the Assistant
 * side-panel slot, each an inert "coming later" seat (see `FutureSeams`) — P6.
 *
 * The pinned **source rail** this layout used to render inline (filename, format + confidence,
 * counts, the guided-spine Convert CTA) moved out in the v2.0 addendums workbench redesign (Task 9):
 * the shell's `WorkbenchLayout` now owns a single, persistent Sources rail
 * (`components/shell/SourceRail.tsx`) across every route, so a second per-file rail here would be a
 * competing "Sources" landmark. The per-file facts it used to show either already live in the
 * `Toolbar` (Open/Upload, Convert — Task 8) or are reserved for the Inspector (format + confidence,
 * counts — Task 10); see `SourceRail.tsx`'s reconciliation note.
 */
export default function WorkspaceLayout({ children }: { children: React.ReactNode }) {
  const { file_id } = useParams<{ file_id: string }>();
  return (
    <div className="min-w-0">
      <WorkspaceTabs fileId={file_id} />
      <div className="mt-5">{children}</div>
      <FutureSeams />
    </div>
  );
}
