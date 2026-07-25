"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { limitsQuery } from "@/lib/api/queries";
import { useUpload } from "@/lib/api/useUpload";
import { UploadDropzone } from "@/components/upload/UploadDropzone";

/**
 * Upload (`/convert`) — the first wizard step (MASTER_SPEC Part 7 §2.2).
 *
 * A client route: it fetches the instance limits so the drop zone can show the size ceiling *before*
 * an upload fails (Part 6 §5), runs the transfer through {@link useUpload} with real progress, and on
 * a `201` routes to the file resource at `/files/[file_id]` — where M28-S2 submits `POST /v1/inspect`.
 * Failures render in place through the shared error envelope; the user stays on the page and retries.
 */
export default function ConvertPage() {
  const router = useRouter();
  const { data: limits } = useQuery(limitsQuery());
  const { status, progress, error, result, upload } = useUpload();

  async function onFile(file: File) {
    const outcome = await upload(file);
    if (outcome.ok) router.push(`/files/${outcome.data.file_id}`);
  }

  return (
    <main className="space-y-6">
      <div className="space-y-2">
        <h1 className="text-2xl font-semibold tracking-tight">Convert a file</h1>
        <p className="max-w-2xl text-slate-600">
          Upload a source file to inspect what it contains, then choose a target format. Every
          conversion produces a report of exactly what was kept, dropped, or assumed.
        </p>
      </div>

      <UploadDropzone
        maxUploadBytes={limits?.max_upload_bytes ?? null}
        status={status}
        progress={progress}
        error={error}
        fileName={result?.filename ?? null}
        onFile={onFile}
      />

      <p className="text-sm text-slate-500">
        <Link href="/" className="underline">
          Back to home
        </Link>
      </p>
    </main>
  );
}
