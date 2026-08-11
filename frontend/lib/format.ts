/**
 * Human-readable size, e.g. 52428800 → "50 MB".
 *
 * Extracted from `UploadDropzone` (v1.1 M39-S1) so a **server** component (the demo banner's
 * `/v1/limits` read) can format the same bytes with the same words as the client dropzone — a
 * pure function with no `"use client"` boundary. Exported by `UploadDropzone` for its existing
 * unit test, which is unchanged.
 */
export function humanBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  const kb = bytes / 1024;
  if (kb < 1024) return `${Math.round(kb)} KB`;
  const mb = kb / 1024;
  if (mb < 1024) return `${Number.isInteger(mb) ? mb : mb.toFixed(1)} MB`;
  const gb = mb / 1024;
  return `${Number.isInteger(gb) ? gb : gb.toFixed(1)} GB`;
}
