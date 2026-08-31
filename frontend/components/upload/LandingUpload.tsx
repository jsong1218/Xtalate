"use client";

import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { limitsQuery } from "@/lib/api/queries";
import { useUpload } from "@/lib/api/useUpload";
import { UploadDropzone } from "./UploadDropzone";

/**
 * The upload affordance on the landing (UI redesign S2, D244; design spec §3): with `/convert`
 * redirected to `/`, upload lives here (and, from S4, on the empty workspace). A client island over
 * the same {@link useUpload} + {@link UploadDropzone} pair the old `/convert` page used — moved, not
 * rewritten — routing a successful upload into the file's workspace at `/f/[file_id]`.
 */
export function LandingUpload() {
  const router = useRouter();
  const { data: limits } = useQuery(limitsQuery());
  const { status, progress, error, result, upload } = useUpload();

  async function onFile(file: File) {
    const outcome = await upload(file);
    if (outcome.ok) router.push(`/f/${outcome.data.file_id}`);
  }

  return (
    <UploadDropzone
      maxUploadBytes={limits?.max_upload_bytes ?? null}
      uploadRetentionHours={limits?.upload_retention_hours ?? null}
      outputRetentionHours={limits?.output_retention_hours ?? null}
      status={status}
      progress={progress}
      error={error}
      fileName={result?.filename ?? null}
      onFile={onFile}
    />
  );
}
