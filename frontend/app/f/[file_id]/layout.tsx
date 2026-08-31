"use client";

import { useParams } from "next/navigation";
import { SourceRail } from "@/components/shell/SourceRail";
import { WorkspaceTabs } from "@/components/shell/WorkspaceTabs";
import { FutureSeams } from "@/components/shell/FutureSeams";

/**
 * The file-centric workspace shell (UI redesign S2, D244; design spec §3, D-R1/D-R2).
 *
 * Every `/f/[file_id]` tab renders inside one layout: a pinned **source rail** (filename, format +
 * confidence, counts, the guided-spine Convert CTA) beside the tabbed main column
 * (`Inspect · Structure · Convert · Report · Analysis`). The rail collapses to a top summary bar on
 * narrow screens — the layout stacks instead of scrolling sideways. Below the active tab's content
 * sit the reserved **empty seams** of the shell (S6, D247): the File Repair action and the
 * Assistant side-panel slot, each an inert "coming later" seat (see `FutureSeams`) — P6.
 */
export default function WorkspaceLayout({ children }: { children: React.ReactNode }) {
  const { file_id } = useParams<{ file_id: string }>();
  return (
    <div className="flex flex-col gap-6 md:flex-row md:items-start">
      <SourceRail fileId={file_id} />
      <div className="min-w-0 flex-1">
        <WorkspaceTabs fileId={file_id} />
        <div className="mt-5">{children}</div>
        <FutureSeams />
      </div>
    </div>
  );
}
