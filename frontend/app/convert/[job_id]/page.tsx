"use client";

import { useEffect } from "react";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { ConversionJob } from "@/components/workspace/ConversionJob";

/**
 * Legacy route (UI redesign S2, D244): the live job surface now lives at
 * `/f/[file_id]/convert?job=…` (the workspace's Convert tab). The job envelope carries no
 * `file_id` on the wire (Part 6 §3.2), so this route can only resolve the workspace when the caller
 * handed one forward (`?file_id=`, as the app always does) — then it redirects. A bare bookmarked
 * job URL renders the job standalone (the same content, with a back affordance) rather than 404ing:
 * behaviour preserved, never a broken link.
 */
export default function LegacyConversionJobPage() {
  const params = useParams<{ job_id: string }>();
  const jobId = params.job_id;
  const fileId = useSearchParams().get("file_id");
  const router = useRouter();

  useEffect(() => {
    if (fileId) {
      router.replace(`/f/${fileId}/convert?job=${encodeURIComponent(jobId)}`);
    }
  }, [fileId, jobId, router]);

  return (
    <ConversionJob
      jobId={jobId}
      fileId={fileId}
      back={{
        href: fileId ? `/f/${fileId}` : "/",
        label: fileId ? "Inspection" : "Upload",
      }}
    />
  );
}
