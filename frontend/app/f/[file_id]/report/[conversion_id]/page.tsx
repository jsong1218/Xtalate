"use client";

import { useParams } from "next/navigation";
import { ConversionRecord } from "@/components/workspace/ConversionRecord";

/**
 * The workspace's Report tab (UI redesign S2, D244; design spec §3, D-R1) — a specific conversion's
 * durable record inside the file's workspace (`/f/[file_id]/report/[cid]`). S3 redesigns the report
 * panels themselves; S2 moves the surface. The file id rides in the URL (the record carries none of
 * its own, Part 6 §4.4), so the rail can pin the source context beside the outcome.
 */
export default function ReportTabPage() {
  const params = useParams<{ file_id: string; conversion_id: string }>();
  return (
    <ConversionRecord
      conversionId={params.conversion_id}
      fileId={params.file_id}
      inWorkspace
    />
  );
}
