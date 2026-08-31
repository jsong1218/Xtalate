"use client";

import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { limitsQuery } from "@/lib/api/queries";
import { SamplePicker } from "@/components/samples/SamplePicker";
import { useUpload } from "@/lib/api/useUpload";
import { UploadDropzone } from "./UploadDropzone";

/**
 * The upload affordance on the landing (UI redesign S2, D244; design spec §3): with `/convert`
 * redirected to `/`, upload lives here. A client island over the same {@link useUpload} +
 * {@link UploadDropzone} pair the old `/convert` page used — moved, not rewritten — routing a
 * successful upload into the file's workspace at `/f/[file_id]`. From S4 (D246) it also offers the
 * "Start with a sample" affordance: a {@link SamplePicker} whose vendored fixture feeds the **same**
 * upload path (`onFile`), so a one-click sample is indistinguishable from a dropped file — no
 * special-case backend route.
 */
export function LandingUpload() {
  const router = useRouter();
  const { data: limits } = useQuery(limitsQuery());
  const { status, progress, error, result, upload } = useUpload();

  async function onFile(file: File) {
    if (status === "uploading") return;
    const outcome = await upload(file);
    if (outcome.ok) router.push(`/f/${outcome.data.file_id}`);
  }

  return (
    <div className="space-y-5">
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
      {/* One-click samples (S4) — same upload path, no special-case backend. */}
      <SamplePicker onPick={onFile} />
    </div>
  );
}
